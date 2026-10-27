"""Loop ReAct dell'agente: Reason -> Act -> Observe fino a una risposta finale o al limite di passi della modalità.

`run_agent_loop` è il punto d'ingresso; lo stato di un turno vive in `AgentLoop` (osservazioni, cache delle
chiamate, anti-loop, ragionamenti accumulati) e ogni fase è un metodo. I testi dei prompt stanno in
`agent_prompts.py`.

Ogni risultato di tool è tenuto due volte: intero per la sintesi finale e accorciato a AGENT_OBSERVATION_LIMIT
nello storico che i passi di selezione rileggono, così un elenco lungo non fa crescere ogni prompt successivo.

Funzioni LLM attese dal chiamante:
- `call_llm_fn(prompt, system_prompt=..., reasoning_budget=..., reasoning_phase=...)` -> {"content", "reasoning_content"}
- `call_llm_structured_fn(prompt=..., system_prompt=..., schema_cls=..., ..., images=...)` -> ToolSelection
"""
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.agent import agent_prompts as prompts
from app.agent.llm_calls import stream_queue
from app.agent.mode_policy import get_mode_policy
from app.agent.stream_session import current_session_var
from app.agent.tool_catalog import format_catalog_for_prompt, format_dynamic_catalog_response
from app.agent.tool_schemas import ToolSelection, validate_tool_args
from app.core.config import settings
from app.core.text_utils import clean_synthesis_content
from app.llm.providers import LLMUnavailableError
from app.registry.manager import get_registry_manager
from app.registry.search_security import GUARD_CLOSE, GUARD_OPEN, escape_guard_delimiters, wrap_untrusted_web_evidence
from app.security import policy

logger = logging.getLogger("agent_loop")

# Query web con similarità di Jaccard almeno pari a questa soglia contano come la stessa ricerca
SEARCH_SIMILARITY_THRESHOLD = 0.80
SESSION_PAUSE_TIMEOUT_SECONDS = 300
SELECTION_MAX_TOKENS = 4096
SELECTION_REASONING_CAP = 1024
SYNTHESIS_REASONING_CAP = 512


def is_tools_discovery_query(query: str) -> bool:
    """Verifica se l'utente sta chiedendo informazioni sui tool o server MCP disponibili.

    ATTENZIONE: deve essere una DOMANDA SUL CATALOGO (es. "quali tool hai?"),
    NON un task che menziona i tool come mezzo (es. "cerca X usando il web search").
    """
    q = query.lower().strip()

    # Marker di TASK: se presenti, la query è un'azione da eseguire, non una
    # domanda sul catalogo — anche se menziona "tool"/"web search".
    task_markers = [
        "dammi", "cerca", "trova", "usando", "utilizzando", "utilizza", "usa ",
        "informazioni su", "notizie", "analizza", "esegui", "crea ", "lancia",
        "aggiornate", "aggiornati", "latest",
    ]
    if any(m in q for m in task_markers):
        return False

    has_target = any(k in q for k in ["mcp", "tool", "tools", "strumenti", "capacità", "funzioni", "comandi"])
    has_intent = any(k in q for k in [
        "quali", "quale", "elenco", "elenca", "lista dei", "lista dei tool",
        "mostra i", "mostrami i", "cosa puoi fare", "hai a disposizione", "di che tool",
    ])
    return has_target and has_intent


def _normalize_call_signature(tool_name: str, arguments: Dict[str, Any]) -> str:
    if tool_name == "web_search":
        q = str(arguments.get("query", "")).lower().strip().strip('"\'')
        q = " ".join(q.split())
        return f"web_search:{q}"
    return f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"


def _query_jaccard_similarity(q1: str, q2: str) -> float:
    tokens1 = set(re.findall(r"\w+", q1.lower()))
    tokens2 = set(re.findall(r"\w+", q2.lower()))
    if not tokens1 or not tokens2:
        return 0.0
    return len(tokens1 & tokens2) / len(tokens1 | tokens2)


def _serialize(res: Any) -> str:
    """Risultato compatto per il prompt.

    I tool MCP che restituiscono un array arrivano come {"content": "<JSON indentato>"}: serializzato di nuovo
    diventerebbe una stringa piena di escape, quasi il doppio dei token e difficile da leggere per i modelli piccoli.
    """
    if isinstance(res, dict) and list(res) == ["content"] and isinstance(res["content"], str):
        try:
            res = json.loads(res["content"])
        except ValueError:
            return res["content"]
    return json.dumps(res, ensure_ascii=False) if isinstance(res, (dict, list)) else str(res)


def _guarded(tool_name: str, text: str) -> str:
    """Il risultato della ricerca web va racchiuso tra delimitatori di contenuto non fidato."""
    if tool_name == "web_search":
        return f"{GUARD_OPEN}\n{escape_guard_delimiters(text)}\n{GUARD_CLOSE}"
    return text


def _content(res: Any) -> Tuple[str, str]:
    """(content, reasoning_content) di una risposta LLM."""
    if isinstance(res, dict):
        return res.get("content", "") or "", res.get("reasoning_content", "") or ""
    return (res or ""), ""


class AgentLoop:
    def __init__(
        self,
        task: str,
        mode: str,
        memory_context: Optional[str],
        call_llm_fn: Optional[Callable[..., Any]],
        call_llm_structured_fn: Optional[Callable[..., Any]],
        thread_id: Optional[str],
        web_prefetch_data: Optional[Dict[str, Any]],
        images: Optional[List[str]],
        security_mode: str,
    ):
        self.task = task
        self.mode = mode
        self.memory_context = memory_context
        self.call_llm_fn = call_llm_fn
        self.call_llm_structured_fn = call_llm_structured_fn
        self.thread_id = thread_id
        self.images = images
        self.security_mode = security_mode
        self.now = prompts.current_time()

        self.policy = get_mode_policy(mode)
        self.manager = get_registry_manager()
        self.available_tools = self.manager.get_tools_for_mode(self.policy.allowed_registries)
        self.prefetch_block = ""
        if web_prefetch_data and web_prefetch_data.get("summary_text"):
            self.prefetch_block = wrap_untrusted_web_evidence(
                query=web_prefetch_data.get("query", task),
                formatted_content=web_prefetch_data.get("summary_text", ""),
                sources=web_prefetch_data.get("sources", []),
            )

        self.execution_trace: List[Dict[str, Any]] = []
        # Risultati interi per la sintesi e la loro versione accorciata per i passi di selezione
        self.observations: List[str] = []
        self.history: List[str] = []
        self.history_truncated = False
        self.reasonings: List[Tuple[str, str]] = []
        # Risultati dei tool read-only già eseguiti nel turno, conteggio delle chiamate per l'anti-loop
        self.call_cache: Dict[str, Any] = {}
        self.call_counts: Dict[str, int] = {}
        self.search_queries: List[str] = []

    # --- risultato ------------------------------------------------------------

    def _reasoning_content(self) -> Optional[str]:
        if not self.reasonings:
            return None
        return "\n\n---\n\n".join(
            f"#### {'🔍' if 'Analisi' in title else '💡'} {title}\n\n{body}" for title, body in self.reasonings
        )

    def _result(self, final_response: str) -> Dict[str, Any]:
        return {"final_response": final_response, "execution_trace": self.execution_trace,
                "reasoning_content": self._reasoning_content()}

    def _observation_text(self) -> str:
        text = "\n".join(self.observations)
        if len(text) > settings.truncation_limit:
            text = text[:settings.truncation_limit] + "\n... [observations truncated for brevity]"
        return text

    def _note(self, text: str):
        """Annotazione senza risultato di tool (validazione fallita, loop interrotto): uguale nei due storici."""
        self.observations.append(text)
        self.history.append(text)

    def _observe(self, header: str, tool_name: str, res: Any) -> str:
        full = _serialize(res)
        self.observations.append(f"{header} -> {_guarded(tool_name, full)}")
        limit = settings.agent_observation_limit
        short = full
        if len(full) > limit:
            self.history_truncated = True
            short = (f"{full[:limit]}\n... [result truncated to {limit} of {len(full)} characters. The final answer is written "
                     "separately from the full result: do not call the tool again to read the rest, and if no other tool is "
                     "needed set tool_needed=false with final_answer=null]")
        self.history.append(f"{header} -> {_guarded(tool_name, short)}")
        return full

    def _ask_llm(self, prompt: str, system_prompt: str, reasoning_budget: int, phase: str) -> str:
        """Chiamata testuale; il ragionamento restituito entra nella traccia del turno con l'etichetta `phase`."""
        res = self.call_llm_fn(prompt, system_prompt=system_prompt, reasoning_budget=reasoning_budget, reasoning_phase=phase)
        if isinstance(res, dict) and res.get("error"):
            raise LLMUnavailableError(res["error"])
        content, reasoning = _content(res)
        if reasoning:
            self.reasonings.append((phase, reasoning))
        return clean_synthesis_content(content)

    def _synthesis_budget(self) -> int:
        return min(self.policy.reasoning_budget, SYNTHESIS_REASONING_CAP) if self.policy.reasoning_budget > 0 else 0

    # --- percorso principale ----------------------------------------------------

    def run(self) -> Dict[str, Any]:
        logger.info(f"Avvio agent loop per mode='{self.mode}' (max_tool_calls={self.policy.max_tool_calls}, registries={self.policy.allowed_registries})")

        if is_tools_discovery_query(self.task):
            logger.info("Query di discovery tool rilevata: formattazione dinamica del catalogo attivo")
            return {
                "final_response": format_dynamic_catalog_response(self.available_tools),
                "execution_trace": [],
                "reasoning_content": f"Elenco dinamico generato con successo per i {len(self.available_tools)} tool attivi.",
            }

        if self.policy.max_tool_calls <= 0 or not self.available_tools:
            return self._answer_without_tools()

        if not self.call_llm_structured_fn:
            return self._plain_answer()

        try:
            return self._react()
        except LLMUnavailableError as e:
            # Nessun altro tentativo: il server è occupato o fermo e una nuova richiesta si accoderebbe
            logger.error(f"Agent loop interrotto: il modello non ha completato la richiesta ({e})")
            return self._result(f"Il modello non ha completato la richiesta ({e}). Riprova tra poco o scegli un modello più leggero.")

    def _react(self) -> Dict[str, Any]:
        system_prompt = prompts.tool_selection_system_prompt(self.mode, format_catalog_for_prompt(self.available_tools))
        for step_id in range(1, self.policy.max_tool_calls + 1):
            if self._session_stopped():
                break

            selection = self._select_tool(step_id, system_prompt)
            if not selection or (not selection.tool_needed and not selection.parallel_calls) or not selection.tool_name:
                return self._final_answer(selection)

            if self._run_parallel(step_id, selection):
                continue

            tool_name, arguments = selection.tool_name, selection.arguments or {}
            if not self._arguments_valid(step_id, tool_name, arguments, selection.reasoning):
                continue
            if self._is_repetition(step_id, tool_name, arguments, selection.reasoning):
                break

            res, cached = self._execute(step_id, tool_name, arguments)
            if isinstance(res, dict) and res.get("approval_required"):
                return self._approval_result(step_id, tool_name, arguments, res, selection.reasoning)
            self._record(step_id, tool_name, arguments, res, selection.reasoning, cached)

        return self._synthesize_after_loop()

    # --- risposte senza selezione dei tool ------------------------------------

    def _answer_without_tools(self) -> Dict[str, Any]:
        """Modalità senza tool (es. chat) o catalogo vuoto: una sola chiamata LLM."""
        if self.call_llm_fn:
            res = self.call_llm_fn(
                prompts.no_tools_prompt(self.task, self.now, self.memory_context, self.prefetch_block),
                system_prompt=prompts.no_tools_system_prompt(self.mode),
                reasoning_budget=self.policy.reasoning_budget,
                reasoning_phase=None,
            )
            if res:
                raw, reasoning = _content(res)
                return {"final_response": clean_synthesis_content(raw) or raw, "execution_trace": [], "reasoning_content": reasoning}
        return {"final_response": f"Ho ricevuto la tua richiesta: '{self.task}'.", "execution_trace": [], "reasoning_content": None}

    def _plain_answer(self) -> Dict[str, Any]:
        """Chiamante senza output strutturato (es. step agentici delle automazioni): risposta diretta."""
        if not self.call_llm_fn:
            return self._result("Richiesta completata.")
        res = self.call_llm_fn(
            prompts.plain_answer_prompt(self.task, self.now, self.memory_context),
            system_prompt=prompts.plain_answer_system_prompt(self.mode),
            reasoning_budget=self.policy.reasoning_budget,
            reasoning_phase="Elaborazione Risposta Finale",
        )
        content, reasoning = _content(res)
        return {"final_response": content or "Richiesta completata.", "execution_trace": self.execution_trace,
                "reasoning_content": reasoning}

    # --- fasi di un passo -----------------------------------------------------

    def _session_stopped(self) -> bool:
        """Rispetta stop e pausa della sessione di streaming (la pausa attende fino a 5 minuti)."""
        sess = current_session_var.get()
        if not sess:
            return False
        if sess.is_stopped():
            logger.info("Agent loop interrotto da session stop")
            return True
        sess.pause_event.wait(timeout=SESSION_PAUSE_TIMEOUT_SECONDS)
        return sess.is_stopped()

    def _select_tool(self, step_id: int, system_prompt: str) -> Optional[ToolSelection]:
        history = "\n".join(self.history) if self.history else "Nessuna azione eseguita finora."
        budget = self.policy.reasoning_budget
        selection = self.call_llm_structured_fn(
            prompt=prompts.tool_selection_prompt(self.task, self.now, self.memory_context, self.prefetch_block,
                                                 len(self.images or []), history),
            system_prompt=system_prompt,
            schema_cls=ToolSelection,
            max_tokens=SELECTION_MAX_TOKENS,
            temperature=0.10,
            max_retries=2,
            reasoning_budget=min(budget, SELECTION_REASONING_CAP) if budget > 0 else SELECTION_REASONING_CAP,
            images=self.images,
        )
        reasoning = (getattr(selection, "raw_thinking", "") or "") or ((selection.reasoning if selection else "") or "")
        if reasoning:
            self.reasonings.append((f"Step {step_id}: Analisi e Selezione Tool" if step_id > 1 else "Analisi e Selezione Tool", reasoning))
        return selection

    def _final_answer(self, selection: Optional[ToolSelection]) -> Dict[str, Any]:
        """Il modello non chiede altri tool: risposta esplicita, sintesi delle osservazioni o risposta diretta.

        Se lo storico di selezione era accorciato, la risposta del modello si basa su dati parziali: si passa
        sempre dalla sintesi sui risultati interi.
        """
        if (selection and selection.final_answer and len(selection.final_answer.strip()) > 10
                and not self.history_truncated):
            final = selection.final_answer.strip()
            # La risposta arriva già completa: la si rimanda alla UI a parole come se fosse in streaming
            q = stream_queue.get()
            if q:
                for word in re.findall(r"\S+|\s+", final):
                    q.put({"type": "content", "delta": word})
            return self._result(final)

        if not self.call_llm_fn:
            return self._result("Richiesta completata.")

        if self.observations:
            answer = self._ask_llm(
                prompts.tool_synthesis_prompt(self.task, self.now, self._observation_text()),
                prompts.tool_synthesis_system_prompt(),
                self._synthesis_budget(),
                "Sintesi Risultati Tool",
            )
            return self._result(answer or "The model processed the information but did not produce a text response. Please retry or adjust mode.")

        answer = self._ask_llm(
            prompts.direct_answer_prompt(self.task, self.now, self.memory_context, self.prefetch_block),
            prompts.direct_answer_system_prompt(self.mode),
            self.policy.reasoning_budget,
            "Elaborazione Risposta Finale",
        )
        return self._result(answer or "Il modello ha elaborato le informazioni ma non ha prodotto una risposta testuale. Riprova o cambia modalità.")

    def _run_parallel(self, step_id: int, selection: ToolSelection) -> bool:
        """Esegue in parallelo le chiamate read-only proposte; False se non ce ne sono almeno due."""
        calls = [c for c in (selection.parallel_calls or [])
                 if isinstance(c, dict) and c.get("tool_name") and policy.classify_tool(c["tool_name"]) == "safe"]
        if len(selection.parallel_calls or []) <= 1 or len(calls) <= 1:
            return False

        logger.info(f"Step {step_id}: esecuzione parallela di {len(calls)} tool read-only")
        results = self.manager.execute_tools_parallel(
            calls, self.policy.allowed_registries, thread_id=self.thread_id, mode=self.mode, security_mode=self.security_mode,
        )
        for i, (call, res) in enumerate(zip(calls, results, strict=True)):
            tool_name, arguments = call["tool_name"], call.get("arguments", {})
            self.execution_trace.append({
                "step_id": step_id,
                "parallel_index": i,
                "tool_name": tool_name,
                "args": arguments,
                "result": res,
                "reasoning": selection.reasoning,
                "parallel": True,
                "error": res.get("error") if isinstance(res, dict) else None,
            })
            if tool_name == "web_search":
                self.search_queries.append(str(arguments.get("query", "")).strip())
            sig = _normalize_call_signature(tool_name, arguments)
            self.call_counts[sig] = self.call_counts.get(sig, 0) + 1
            self._observe(f"Step {step_id}.{i} [parallelo]: {tool_name}({call.get('arguments')})", tool_name, res)
        return True

    def _arguments_valid(self, step_id: int, tool_name: str, arguments: Dict[str, Any], reasoning: Optional[str]) -> bool:
        error = validate_tool_args(tool_name, arguments, self.available_tools)
        if not error:
            return True
        logger.warning(f"Step {step_id}: errore validazione argomenti per '{tool_name}': {error}")
        self.execution_trace.append({"step_id": step_id, "tool_name": tool_name, "args": arguments,
                                     "reasoning": reasoning, "error": f"Validazione fallita: {error}"})
        self._note(f"Step {step_id}: Chiamata a '{tool_name}' fallita la validazione -> {error}")
        return False

    def _is_repetition(self, step_id: int, tool_name: str, arguments: Dict[str, Any], reasoning: Optional[str]) -> bool:
        """Anti-loop: una chiamata già fatta nel turno (o una ricerca web quasi uguale) chiude il loop e passa alla sintesi."""
        sig = _normalize_call_signature(tool_name, arguments)
        repeated = sig in self.call_counts
        self.call_counts[sig] = self.call_counts.get(sig, 0) + 1

        if tool_name == "web_search" and not repeated:
            query = str(arguments.get("query", "")).strip()
            for previous in self.search_queries:
                similarity = _query_jaccard_similarity(query, previous)
                if similarity >= SEARCH_SIMILARITY_THRESHOLD:
                    logger.info(f"Step {step_id}: query '{query}' ha similarità {similarity:.2f} con precedente '{previous}', trattata come duplicato")
                    repeated = True
                    break
            if not repeated:
                self.search_queries.append(query)

        if repeated:
            logger.warning(f"Step {step_id}: Rilevata ripetizione per '{tool_name}'. Interruzione loop ReAct per prevenire cicli infiniti.")
            self._note(f"Step {step_id}: [LOOP INTERROTTO] L'azione '{tool_name}' è già stata eseguita in precedenza. Si procede alla sintesi finale.")
            self.execution_trace.append({
                "step_id": step_id, "tool_name": tool_name, "args": arguments, "reasoning": reasoning,
                "result": {"warning": "Chiamata duplicata bloccata. Interruzione loop ReAct per convergenza rapida."},
                "cached": True, "duplicate_blocked": True,
            })
        return repeated

    def _execute(self, step_id: int, tool_name: str, arguments: Dict[str, Any]) -> Tuple[Any, bool]:
        """Esegue il tool tramite il registry (guardrail, approvazione, audit); i read-only finiscono in cache."""
        cache_key = f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"
        if cache_key in self.call_cache:
            logger.info(f"Step {step_id}: hit cache deduplicazione per '{tool_name}'")
            return self.call_cache[cache_key], True
        try:
            res = self.manager.execute_tool(tool_name, arguments, self.policy.allowed_registries, thread_id=self.thread_id,
                                            mode=self.mode, security_mode=self.security_mode, task=self.task)
        except Exception as e:
            logger.error(f"Step {step_id}: eccezione esecuzione tool '{tool_name}': {e}")
            return {"error": f"Eccezione durante l'esecuzione: {str(e)}"}, False
        if policy.classify_tool(tool_name) == "safe":
            self.call_cache[cache_key] = res
        return res, False

    def _approval_result(self, step_id: int, tool_name: str, arguments: Dict[str, Any], res: Dict[str, Any],
                         reasoning: Optional[str]) -> Dict[str, Any]:
        """Il guardrail chiede conferma: notifica la UI e chiude il turno in attesa della decisione."""
        logger.info(f"Step {step_id}: Tool '{tool_name}' richiede approvazione esplicita ({res.get('risk_reason')}).")
        message = res.get("message", "Richiesta di approvazione richiesta.")
        approval = {
            "request_id": res.get("request_id"),
            "command_preview": res.get("command_preview"),
            "command_prefix": res.get("command_prefix"),
            "risk_reason": res.get("risk_reason"),
        }
        q = stream_queue.get()
        if q:
            q.put({"type": "approval_required", "tool_name": tool_name, "arguments": arguments, "message": message, **approval})

        self.execution_trace.append({"step_id": step_id, "tool_name": tool_name, "args": arguments, "result": res,
                                     "reasoning": reasoning, "approval_required": True, "approval_prompt": message, **approval})
        return {"final_response": message, "execution_trace": self.execution_trace, "reasoning_content": reasoning,
                "approval_required": True, "approval_prompt": message, **approval}

    def _record(self, step_id: int, tool_name: str, arguments: Dict[str, Any], res: Any, reasoning: Optional[str], cached: bool):
        observation = self._observe(f"Step {step_id}: {tool_name}({arguments})", tool_name, res)
        logger.info(f"Step {step_id}: Risultato tool '{tool_name}' ({len(observation)} caratteri): {observation[:200]}...")
        self.execution_trace.append({"step_id": step_id, "tool_name": tool_name, "args": arguments, "result": res,
                                     "reasoning": reasoning, "cached": cached,
                                     "error": res.get("error") if isinstance(res, dict) else None})

    def _synthesize_after_loop(self) -> Dict[str, Any]:
        """Passi esauriti, anti-loop o stop: sintesi di quanto osservato."""
        if not (self.observations and self.call_llm_fn):
            return self._result("Richiesta completata.")
        answer = self._ask_llm(
            prompts.final_synthesis_prompt(self.task, self.now, self._observation_text()),
            prompts.final_synthesis_system_prompt(),
            self._synthesis_budget(),
            "Sintesi Risultati Finali",
        )
        return self._result(answer or "Operazione completata.")


def run_agent_loop(
    task: str,
    mode: str,
    memory_context: Optional[str] = None,
    call_llm_fn: Optional[Callable[..., Any]] = None,
    call_llm_structured_fn: Optional[Callable[..., Any]] = None,
    thread_id: Optional[str] = None,
    web_prefetch_data: Optional[Dict[str, Any]] = None,
    images: Optional[List[str]] = None,
    security_mode: str = "normal",
) -> Dict[str, Any]:
    """Esegue il loop ReAct secondo la ModePolicy della modalità.

    Con max_tool_calls == 0 (es. chat) risponde direttamente; altrimenti cicla Reason -> Act -> Observe
    fino a una risposta finale o al limite di passi.
    """
    return AgentLoop(task, mode, memory_context, call_llm_fn, call_llm_structured_fn, thread_id,
                     web_prefetch_data, images, security_mode).run()
