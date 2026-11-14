"""Loop ReAct dell'agente: Reason -> Act -> Observe fino a una risposta finale o al limite di passi della modalità.

`run_agent_loop` è il punto d'ingresso; lo stato di un turno vive in `AgentLoop` (osservazioni, cache delle
chiamate, anti-loop, ragionamenti accumulati) e ogni fase è un metodo. I testi dei prompt stanno in
`agent_prompts.py`.

Ogni risultato di tool è tenuto due volte: intero per la sintesi finale e accorciato a AGENT_OBSERVATION_LIMIT
nello storico che i passi di selezione rileggono, così un elenco lungo non fa crescere ogni prompt successivo.

Lo storico arriva al modello in due forme, a seconda del profilo del modello (`interleaved`):
- testo in coda al messaggio utente (`Step N: tool(args) -> risultato`): il pensiero dei passi precedenti si perde;
- messaggi dopo il messaggio utente: per ogni passo l'assistente con il suo pensiero (`reasoning_content`) e il JSON di
  selezione, poi un messaggio `tool` per ogni risultato. Il template conserva il pensiero dei passi del turno e il
  prompt cresce solo in coda (docs/reasoning/INTERLEAVED_THINKING.md).

Un'uscita di dati che la destinazione non può ricevere (memoria privata nel turno, ricerca pubblica) non chiede subito
conferma: prima gli argomenti li riscrive una chiamata che vede solo ciò che la destinazione può ricevere (`_clean_call`,
design della sensibilità 9.4, opzione 3). Se non basta, resta la conferma con gli argomenti originali.

Una richiesta di approvazione sospende il loop: `checkpoint` ne salva lo stato con l'id della richiesta (turn_checkpoints) e
`AgentLoop.restore` + `resume` lo riprendono dal passo dopo, con il tool eseguito o con il rifiuto come risultato del passo.

Funzioni LLM attese dal chiamante:
- `call_llm_fn(prompt, system_prompt=..., thinking=..., reasoning_phase=...)` -> {"content", "reasoning_content"}
- `call_llm_structured_fn(prompt=..., system_prompt=..., schema_cls=..., ..., thinking=..., images=..., history=...)` -> ToolSelection

Il livello di ragionamento (`thinking`) è quello della fase nella `ThinkingPolicy` della modalità: `select` per la
scelta dei tool, `answer` per risposte e sintesi.
"""
import json
import logging
import re
from typing import Any, Callable, Collection, Dict, List, Optional, Tuple

from app.agent import agent_prompts as prompts
from app.agent import turn_checkpoints
from app.agent.llm_calls import stream_queue
from app.agent.mode_policy import get_mode_policy
from app.agent.stream_session import current_session_var
from app.agent.tool_catalog import format_catalog_for_prompt, format_dynamic_catalog_response
from app.agent.tool_schemas import CleanArguments, ToolSelection, validate_tool_args
from app.core.config import settings
from app.core.text_utils import clean_synthesis_content
from app.llm.providers import LLMUnavailableError
from app.registry.manager import get_registry_manager
from app.registry.search_security import GUARD_CLOSE, GUARD_OPEN, escape_guard_delimiters, wrap_untrusted_web_evidence
from app.security import approvals, detectors, flows, policy
from app.security.flows import Tag
from app.security.provenance import Provenance, guarded_spans

logger = logging.getLogger("agent_loop")

# Query web con similarità di Jaccard almeno pari a questa soglia contano come la stessa ricerca
SEARCH_SIMILARITY_THRESHOLD = 0.80
SESSION_PAUSE_TIMEOUT_SECONDS = 300
SELECTION_MAX_TOKENS = 4096


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


# Il tag di linguaggio è una parola seguita da un a capo (o `json`): in ```docker_ps``` la parola è il contenuto
_CODE_BLOCK = re.compile(r"```(?:json\b|[\w-]+\n)?\s*(.*?)\s*(?:```|$)", re.S)
_CALL_KEYS = {"tool", "tool_name", "function", "arguments", "parameters"}
_CALL_LIKE = re.compile(r"^[A-Za-z_][\w.-]*(\(.*\))?$", re.S)


# Tool di sola lettura che possono chiedere un'approvazione a runtime (host non ammesso): mai in parallelo
SEQUENTIAL_ONLY_TOOLS = frozenset({"http_get", "inspect_image"})


def _pending_or_blocked(res: Any) -> bool:
    # "blocked": host rifiutato dal controllo di rete; può cambiare se l'utente lo aggiunge alla lista durante il turno
    return isinstance(res, dict) and bool(res.get("approval_required") or res.get("blocked_by_guardrail") or res.get("blocked"))


def is_pseudo_tool_call(text: Optional[str]) -> bool:
    """`final_answer` che non è una risposta ma le chiamate che il modello voleva fare (ISS-28): solo codice, che è un
    JSON con chiavi da chiamata (`tool`, `arguments`…) o un nome in stile funzione (`docker_ps`, `list_x(...)`).
    Una risposta in prosa con comandi o un blocco di comandi shell resta una risposta."""
    text = (text or "").strip()
    blocks = _CODE_BLOCK.findall(text)
    if blocks and _CODE_BLOCK.sub("", text).strip():
        return False
    body = "\n".join(blocks).strip() if blocks else text
    try:
        parsed = json.loads(body)
    except ValueError:
        # JSON di chiamate troncato dal limite di token, o un nome di funzione da solo in un blocco
        if body[:1] in "[{" and re.search(r'"(tool|tool_name|function)"\s*:', body):
            return True
        return bool(blocks) and "\n" not in body and bool(_CALL_LIKE.match(body))
    items = parsed if isinstance(parsed, list) else [parsed]
    return bool(items) and all(isinstance(i, dict) and _CALL_KEYS & set(i) for i in items)


def _content(res: Any) -> Tuple[str, str]:
    """(content, reasoning_content) di una risposta LLM."""
    if isinstance(res, dict):
        return res.get("content", "") or "", res.get("reasoning_content", "") or ""
    return (res or ""), ""


# Ciò che il loop ha accumulato: si salva quando si sospende e si ripristina quando riprende
_PROGRESS_FIELDS = ("now", "prefetch_block", "execution_trace", "observations", "history", "turn_messages", "history_truncated",
                    "reasonings", "call_cache", "call_counts", "search_queries", "pseudo_call_retried", "clean_context",
                    "untrusted_texts")

# La chiamata che riscrive gli argomenti di un'uscita: un oggetto JSON piccolo, senza ragionamento
CLEAN_MAX_TOKENS = 1024
# Origini mostrate nella richiesta di conferma quando un comando porta testo letto da fuori, e quanti messaggi
# dell'utente contano come "scritto da lui"
MEMORY_ORIGIN = "fatto ricordato da contenuto esterno"
PREFETCH_ORIGIN = "ricerca web iniziale"
USER_MESSAGES_TRUSTED = 50


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
        interleaved: bool = False,
        *,
        allowed_tools: Optional[Collection[str]] = None,
        allowed_registries: Optional[List[str]] = None,
        max_tool_calls: Optional[int] = None,
        audit: Optional[Dict[str, str]] = None,
        meta: Optional[Dict[str, Any]] = None,
        checkpoint_kind: str = "loop",
        tag: Optional[Any] = None,
        request_tag: Optional[Any] = None,
        recent_turns: Optional[str] = None,
        recent_tag: Optional[Any] = None,
    ):
        """`allowed_tools`, `allowed_registries` e `max_tool_calls` restringono il catalogo e i passi della modalità (step
        delle automazioni). `audit` finisce nelle chiamate ai tool; `meta` serve a chi riprende il loop dopo un'approvazione.
        `tag`: sensibilità di ciò che il turno ha già in contesto (richiesta, memoria, prefetch); sale con ogni risultato
        letto e accompagna ogni chiamata a un modello e a un tool (app.security.flows).
        `request_tag` (la sola richiesta), `recent_turns` e `recent_tag` (gli ultimi messaggi che vede il router): ciò che
        può leggere la chiamata che riscrive un'uscita senza i dati riservati del turno. Senza `request_tag` (automazioni,
        valutazioni vecchie) un'uscita negata chiede subito conferma."""
        self.task = task
        self.mode = mode
        self.memory_context = memory_context
        self.call_llm_fn = call_llm_fn
        self.call_llm_structured_fn = call_llm_structured_fn
        self.thread_id = thread_id
        self.images = images
        self.security_mode = security_mode
        self.interleaved = interleaved
        self.now = prompts.current_time()

        self.policy = get_mode_policy(mode)
        self.manager = get_registry_manager()
        self.allowed_registries = allowed_registries if allowed_registries is not None else self.policy.allowed_registries
        self.allowed_tools = set(allowed_tools) if allowed_tools is not None else None
        self.max_tool_calls = self.policy.max_tool_calls if max_tool_calls is None else min(max_tool_calls, self.policy.max_tool_calls)
        self.audit = audit or {}
        self.meta = meta or {}
        self.checkpoint_kind = checkpoint_kind
        self.available_tools = [t for t in self.manager.get_tools_for_mode(self.allowed_registries) if self._tool_allowed(t["name"])]
        self.tag: Tag = flows.join(tag) if tag else flows.PUBLIC_TAG
        self.request_tag: Optional[Tag] = flows.join(request_tag) if request_tag else None
        self.recent_turns = recent_turns
        self.recent_tag: Optional[Tag] = flows.join(recent_tag) if recent_tag else None
        # Testi che la chiamata pulita può leggere, ognuno con il tag di ciò da cui viene (argomenti e risultato)
        self.clean_context: List[Dict[str, Any]] = []
        self._mcp_flows = flows.mcp_flow_settings()
        self._person_names: Optional[List[str]] = None
        self._user_texts: Optional[List[str]] = None
        # Ciò che il turno ha letto da contenuto scritto da altri, come coppie [origine, testo]: serve a riconoscere
        # un comando già autorizzato che porta testo venuto da lì (app.security.provenance). I fatti ricordati da
        # contenuto esterno arrivano già tra i delimitatori dentro la memoria richiamata
        self.untrusted_texts: List[List[str]] = [
            [MEMORY_ORIGIN, span] for span in guarded_spans(memory_context or "", GUARD_OPEN, GUARD_CLOSE)]
        self.prefetch_block = ""
        if web_prefetch_data and web_prefetch_data.get("summary_text"):
            self.untrusted_texts.append([PREFETCH_ORIGIN, str(web_prefetch_data.get("summary_text", ""))])
            self.tag = flows.join(self.tag, flows.tag_of(flows.Label.PUBLIC, "web_prefetch", untrusted=True))
            self.prefetch_block = wrap_untrusted_web_evidence(
                query=web_prefetch_data.get("query", task),
                formatted_content=web_prefetch_data.get("summary_text", ""),
                sources=web_prefetch_data.get("sources", []),
            )
            # Il prefetch parte solo con una query pubblica: i suoi risultati sono pubblici e non attendibili
            self.clean_context.append({"text": self.prefetch_block,
                                       "tag": flows.tag_of(flows.Label.PUBLIC, "web_prefetch", untrusted=True).to_dict()})

        self.execution_trace: List[Dict[str, Any]] = []
        # Risultati interi per la sintesi e la loro versione accorciata per i passi di selezione
        self.observations: List[str] = []
        self.history: List[str] = []
        # Nel loop interleaved lo stesso storico come messaggi, con il pensiero di ogni passo
        self.turn_messages: List[Dict[str, Any]] = []
        self.history_truncated = False
        self.reasonings: List[Tuple[str, str]] = []
        # Risultati dei tool read-only già eseguiti nel turno, conteggio delle chiamate per l'anti-loop
        self.call_cache: Dict[str, Any] = {}
        self.call_counts: Dict[str, int] = {}
        self.search_queries: List[str] = []
        self.pseudo_call_retried = False
        self.pending: Optional[Dict[str, Any]] = None

    def _tool_allowed(self, tool_name: str) -> bool:
        return self.allowed_tools is None or tool_name in self.allowed_tools

    # --- sospensione e ripresa ------------------------------------------------

    def checkpoint(self, pending: Dict[str, Any]) -> Dict[str, Any]:
        """Stato del loop sospeso sulla chiamata `pending`, serializzabile in JSON."""
        return {
            "pending": pending,
            "constructor": {
                "task": self.task, "mode": self.mode, "memory_context": self.memory_context, "thread_id": self.thread_id,
                "images": self.images, "security_mode": self.security_mode, "interleaved": self.interleaved,
                "allowed_tools": sorted(self.allowed_tools) if self.allowed_tools is not None else None,
                "allowed_registries": self.allowed_registries, "max_tool_calls": self.max_tool_calls,
                "audit": self.audit, "meta": self.meta, "checkpoint_kind": self.checkpoint_kind,
                # Il tag di questo momento, già alzato dai risultati letti: il loop ripreso parte da qui
                "tag": self.tag.to_dict(),
                "request_tag": self.request_tag.to_dict() if self.request_tag else None,
                "recent_turns": self.recent_turns,
                "recent_tag": self.recent_tag.to_dict() if self.recent_tag else None,
            },
            "progress": {name: getattr(self, name) for name in _PROGRESS_FIELDS},
        }

    @classmethod
    def restore(cls, state: Dict[str, Any], call_llm_fn: Optional[Callable[..., Any]],
                call_llm_structured_fn: Optional[Callable[..., Any]]) -> "AgentLoop":
        args = dict(state["constructor"])
        positional = [args.pop(name) for name in ("task", "mode", "memory_context")]
        loop = cls(*positional, call_llm_fn, call_llm_structured_fn, args.pop("thread_id"), None, args.pop("images"),
                   args.pop("security_mode"), args.pop("interleaved"), **args)
        for name, value in state["progress"].items():
            setattr(loop, name, value)
        loop.reasonings = [tuple(r) for r in loop.reasonings]
        loop.pending = state["pending"]
        return loop

    def resume(self, request_id: str, approved: bool) -> Dict[str, Any]:
        """Riprende dopo la decisione sulla richiesta: il tool approvato è il risultato del passo in attesa, un rifiuto
        lo è altrettanto; poi il loop continua dal passo successivo."""
        step_id, tool_name = self.pending["step_id"], self.pending["tool_name"]
        arguments, reasoning = self.pending["arguments"], self.pending["reasoning"]
        # Una chiamata riscritta senza i dati riservati riparte con il tag con cui è stata scritta
        call_tag = flows.join(self.pending["call_tag"]) if self.pending.get("call_tag") else self.tag
        original = self.pending.get("original")
        if self.execution_trace and self.execution_trace[-1].get("approval_required"):
            self.execution_trace.pop()

        if approved:
            res = self._execute_approved(step_id, request_id, tool_name, arguments, call_tag, clean=original is not None)
            if isinstance(res, dict) and res.get("approval_required"):
                return self._approval_result(step_id, tool_name, arguments, res, reasoning, call_tag, original)
            self._record(step_id, tool_name, arguments, res, reasoning, False, call_tag, original)
        else:
            logger.info(f"Step {step_id}: l'utente ha rifiutato '{tool_name}'")
            self.execution_trace.append({"step_id": step_id, "tool_name": tool_name, "args": arguments, "reasoning": reasoning,
                                         "result": {"denied": True}, "error": "Rifiutato dall'utente"})
            self._note(f"Step {step_id}: the user DENIED the call to '{tool_name}' with arguments {arguments}: it was not executed. "
                       "Do not try it again. Continue without it if you can, otherwise tell the user what is done and what is missing.")
        return self._react_guarded(step_id + 1)

    def _execute_approved(self, step_id: int, request_id: str, tool_name: str, arguments: Dict[str, Any], call_tag: Tag,
                          clean: bool = False) -> Any:
        request = approvals.approved_request_for(request_id, tool_name, arguments, self.thread_id, self.mode)
        try:
            return self.manager.execute_tool(tool_name, arguments, self.allowed_registries, thread_id=self.thread_id, mode=self.mode,
                                             security_mode=self.security_mode, task=self.task, approved_request=request,
                                             tag=call_tag, clean=clean, **self.audit)
        except Exception as e:
            logger.error(f"Step {step_id}: eccezione esecuzione tool approvato '{tool_name}': {e}")
            return {"error": f"Eccezione durante l'esecuzione: {str(e)}"}

    # --- risultato ------------------------------------------------------------

    def _reasoning_content(self) -> Optional[str]:
        if not self.reasonings:
            return None
        return "\n\n---\n\n".join(
            f"#### {'🔍' if 'Analisi' in title else '💡'} {title}\n\n{body}" for title, body in self.reasonings
        )

    def _result(self, final_response: str) -> Dict[str, Any]:
        return {"final_response": final_response, "execution_trace": self.execution_trace,
                "reasoning_content": self._reasoning_content(), "tag": self.tag.to_dict()}

    def _observation_text(self) -> str:
        text = "\n".join(self.observations)
        if len(text) > settings.truncation_limit:
            text = text[:settings.truncation_limit] + "\n... [observations truncated for brevity]"
        return text

    def _remember(self, entry: str):
        """Una voce dello storico dei passi di selezione: riga di testo e risultato di tool."""
        self.history.append(entry)
        if self.interleaved:
            self.turn_messages.append({"role": "tool", "content": entry})

    def _note(self, text: str):
        """Annotazione senza risultato di tool (validazione fallita, loop interrotto): uguale nei due storici."""
        self.observations.append(text)
        self._remember(text)

    def _flow_allowed(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """I dati del turno possono andare alla destinazione del tool senza chiedere (chiamate in parallelo)."""
        dest = flows.destination_for_tool(tool_name, arguments, self._mcp_flows)
        return dest is None or flows.can_flow(self.tag, dest).allowed

    def _persons(self) -> List[str]:
        if self._person_names is None:
            try:
                from app.memory import facts
                self._person_names = [e["name"] for e in facts.list_entities(entity_type="person") if e.get("name")]
            except Exception as e:
                logger.warning(f"Nomi delle persone per i rilevatori non disponibili: {e}")
                self._person_names = []
        return self._person_names

    def _provenance(self) -> Provenance:
        """Ciò che il turno ha letto da fuori e ciò che ha scritto l'utente (la richiesta e i suoi messaggi nella
        conversazione): una parola scritta dall'utente non conta come venuta da fuori."""
        if self._user_texts is None:
            self._user_texts = []
            if self.thread_id:
                try:
                    from app.memory import thread_store
                    history = thread_store.get_history(self.thread_id)
                    self._user_texts = [m["content"] for m in history if m.get("role") == "user"][-USER_MESSAGES_TRUSTED:]
                except Exception as e:
                    logger.warning(f"Messaggi dell'utente non letti per la provenienza degli argomenti: {e}")
        return Provenance(tuple((origin, text) for origin, text in self.untrusted_texts), (self.task, *self._user_texts))

    def _observe(self, header: str, tool_name: str, res: Any, arguments: Optional[Dict[str, Any]], call_tag: Tag) -> str:
        """`call_tag`: il tag con cui sono stati scritti gli argomenti. Il risultato entra nel contesto della chiamata
        pulita con l'unione dei due: quello di una chiamata scritta da dati privati resta fuori anche se è pubblico,
        perché può ripetere la query."""
        # Prima di entrare nel contesto: via i segreti; poi l'etichetta del turno sale con quella del risultato
        full, _ = detectors.redact_secrets(_serialize(res))
        if not _pending_or_blocked(res):
            result = flows.join(flows.result_tag(tool_name, arguments, res, self._mcp_flows),
                                detectors.tag_for(full, f"risultato:{tool_name}", self._persons(), detectors.RESULT_KINDS))
            self.tag = flows.join(self.tag, result)
            if result.untrusted:
                self.untrusted_texts.append([tool_name, full])
            short_clean = full if len(full) <= settings.agent_observation_limit else full[:settings.agent_observation_limit] + "\n..."
            self.clean_context.append({"text": f"{header} -> {_guarded(tool_name, short_clean)}",
                                       "tag": flows.join(call_tag, result).to_dict()})
        self.observations.append(f"{header} -> {_guarded(tool_name, full)}")
        limit = settings.agent_observation_limit
        short = full
        if len(full) > limit:
            self.history_truncated = True
            short = (f"{full[:limit]}\n... [result truncated to {limit} of {len(full)} characters. The final answer is written "
                     "separately from the full result: do not call the tool again to read the rest, and if no other tool is "
                     "needed set tool_needed=false with final_answer=null]")
        self._remember(f"{header} -> {_guarded(tool_name, short)}")
        return full

    def _ask_llm(self, prompt: str, system_prompt: str, phase: str) -> str:
        """Risposta testuale (fase `answer`); il ragionamento restituito entra nella traccia del turno con l'etichetta `phase`."""
        res = self.call_llm_fn(prompt, system_prompt=system_prompt, thinking=self.policy.thinking.answer, reasoning_phase=phase,
                               tag=self.tag)
        if isinstance(res, dict) and res.get("error"):
            raise LLMUnavailableError(res["error"])
        content, reasoning = _content(res)
        if reasoning:
            self.reasonings.append((phase, reasoning))
        return clean_synthesis_content(content)

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

        if self.max_tool_calls <= 0 or not self.available_tools:
            return self._answer_without_tools()

        if not self.call_llm_structured_fn:
            return self._plain_answer()

        return self._react_guarded()

    def _react_guarded(self, first_step: int = 1) -> Dict[str, Any]:
        try:
            return self._react(first_step)
        except LLMUnavailableError as e:
            # Nessun altro tentativo: il server è occupato o fermo e una nuova richiesta si accoderebbe
            logger.error(f"Agent loop interrotto: il modello non ha completato la richiesta ({e})")
            return {**self._result(f"Il modello non ha completato la richiesta ({e}). Riprova tra poco o scegli un modello più leggero."),
                    "llm_unavailable": True}

    def _selection_system_prompt(self) -> str:
        return prompts.tool_selection_system_prompt(self.mode, format_catalog_for_prompt(self.available_tools))

    def first_selection(self) -> Optional[ToolSelection]:
        """Prima scelta del modello sul catalogo della modalità, senza eseguire nulla (valutazione dei modelli)."""
        return self._select_tool(1, self._selection_system_prompt())

    def _react(self, first_step: int = 1) -> Dict[str, Any]:
        system_prompt = self._selection_system_prompt()
        for step_id in range(first_step, self.max_tool_calls + 1):
            if self._session_stopped():
                break

            selection = self._select_tool(step_id, system_prompt)
            if not selection or (not selection.tool_needed and not selection.parallel_calls) or not selection.tool_name:
                if selection and is_pseudo_tool_call(selection.final_answer):
                    if self._retry_pseudo_call(step_id, selection.final_answer):
                        continue
                    selection.final_answer = None
                return self._final_answer(selection)

            if self._run_parallel(step_id, selection):
                continue

            tool_name, arguments = selection.tool_name, selection.arguments or {}
            if not self._tool_allowed(tool_name):
                self._reject_tool(step_id, tool_name, arguments, selection.reasoning)
                continue
            if not self._arguments_valid(step_id, tool_name, arguments, selection.reasoning):
                continue
            call_tag, original = self.tag, None
            clean = self._clean_call(tool_name, arguments)
            if clean is not None:
                original = arguments
                arguments, call_tag = clean
            if self._is_repetition(step_id, tool_name, arguments, selection.reasoning):
                break

            res, cached = self._execute(step_id, tool_name, arguments, call_tag, clean=original is not None)
            if isinstance(res, dict) and res.get("approval_required"):
                return self._approval_result(step_id, tool_name, arguments, res, selection.reasoning, call_tag, original)
            self._record(step_id, tool_name, arguments, res, selection.reasoning, cached, call_tag, original)

        return self._synthesize_after_loop()

    # --- risposte senza selezione dei tool ------------------------------------

    def _answer_without_tools(self) -> Dict[str, Any]:
        """Modalità senza tool (es. chat) o catalogo vuoto: una sola chiamata LLM."""
        if self.call_llm_fn:
            res = self.call_llm_fn(
                prompts.no_tools_prompt(self.task, self.now, self.memory_context, self.prefetch_block),
                system_prompt=prompts.no_tools_system_prompt(self.mode),
                thinking=self.policy.thinking.answer,
                reasoning_phase=None,
                tag=self.tag,
            )
            if res:
                raw, reasoning = _content(res)
                return {"final_response": clean_synthesis_content(raw) or raw, "execution_trace": [], "reasoning_content": reasoning,
                        "tag": self.tag.to_dict()}
        return {"final_response": f"Ho ricevuto la tua richiesta: '{self.task}'.", "execution_trace": [], "reasoning_content": None,
                "tag": self.tag.to_dict()}

    def _plain_answer(self) -> Dict[str, Any]:
        """Chiamante senza output strutturato (es. step agentici delle automazioni): risposta diretta."""
        if not self.call_llm_fn:
            return self._result("Richiesta completata.")
        res = self.call_llm_fn(
            prompts.plain_answer_prompt(self.task, self.now, self.memory_context),
            system_prompt=prompts.plain_answer_system_prompt(self.mode),
            thinking=self.policy.thinking.answer,
            reasoning_phase="Elaborazione Risposta Finale",
            tag=self.tag,
        )
        content, reasoning = _content(res)
        return {"final_response": content or "Richiesta completata.", "execution_trace": self.execution_trace,
                "reasoning_content": reasoning, "tag": self.tag.to_dict()}

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
        history = None
        if not self.interleaved:
            history = "\n".join(self.history) if self.history else "Nessuna azione eseguita finora."
        extra = {"history": list(self.turn_messages)} if self.interleaved else {}
        selection = self.call_llm_structured_fn(
            prompt=prompts.tool_selection_prompt(self.task, self.now, self.memory_context, self.prefetch_block,
                                                 len(self.images or []), history),
            system_prompt=system_prompt,
            schema_cls=ToolSelection,
            max_tokens=SELECTION_MAX_TOKENS,
            temperature=0.10,
            max_retries=2,
            thinking=self.policy.thinking.select,
            images=self.images,
            tag=self.tag,
            **extra,
        )
        thinking = getattr(selection, "raw_thinking", "") or ""
        if selection and self.interleaved:
            # Il passo come lo ha scritto il modello: pensiero e JSON (che resta nella forma imposta dalla grammatica)
            message: Dict[str, Any] = {"role": "assistant",
                                       "content": json.dumps(selection.model_dump(exclude={"raw_thinking"}), ensure_ascii=False)}
            if thinking:
                message["reasoning_content"] = thinking
            self.turn_messages.append(message)
        reasoning = thinking or ((selection.reasoning if selection else "") or "")
        if reasoning:
            self.reasonings.append((f"Step {step_id}: Analisi e Selezione Tool" if step_id > 1 else "Analisi e Selezione Tool", reasoning))
        return selection

    def _retry_pseudo_call(self, step_id: int, text: str) -> bool:
        """Una volta per turno, una risposta finale fatta di chiamate a tool torna al modello come errore del passo."""
        logger.warning(f"Step {step_id}: final_answer con chiamate a tool invece della risposta: {text[:120]!r}")
        if self.pseudo_call_retried:
            return False
        self.pseudo_call_retried = True
        self._note(f"Step {step_id}: final_answer rejected: it contains tool calls instead of the answer for the user. "
                   "To use a tool set tool_needed=true and tool_name to an exact name from the catalog; "
                   "otherwise write the answer for the user in prose.")
        return True

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
                "Sintesi Risultati Tool",
            )
            return self._result(answer or "The model processed the information but did not produce a text response. Please retry or adjust mode.")

        answer = self._ask_llm(
            prompts.direct_answer_prompt(self.task, self.now, self.memory_context, self.prefetch_block),
            prompts.direct_answer_system_prompt(self.mode),
            "Elaborazione Risposta Finale",
        )
        return self._result(answer or "Il modello ha elaborato le informazioni ma non ha prodotto una risposta testuale. Riprova o cambia modalità.")

    def _run_parallel(self, step_id: int, selection: ToolSelection) -> bool:
        """Esegue in parallelo le chiamate read-only proposte; False se non ce ne sono almeno due."""
        # I tool che possono chiedere un'approvazione durante l'esecuzione restano sequenziali: qui non si sospende
        calls = [c for c in (selection.parallel_calls or [])
                 if isinstance(c, dict) and c.get("tool_name") and policy.classify_tool(c["tool_name"]) == "safe"
                 and c["tool_name"] not in SEQUENTIAL_ONLY_TOOLS and self._tool_allowed(c["tool_name"])
                 and self._flow_allowed(c["tool_name"], c.get("arguments") or {})]
        if len(selection.parallel_calls or []) <= 1 or len(calls) <= 1:
            return False

        logger.info(f"Step {step_id}: esecuzione parallela di {len(calls)} tool read-only")
        results = self.manager.execute_tools_parallel(
            calls, self.allowed_registries, thread_id=self.thread_id, mode=self.mode, security_mode=self.security_mode,
            task=self.task, tag=self.tag, **self.audit,
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
            self._observe(f"Step {step_id}.{i} [parallelo]: {tool_name}({call.get('arguments')})", tool_name, res, arguments, self.tag)
        return True

    def _reject_tool(self, step_id: int, tool_name: str, arguments: Dict[str, Any], reasoning: Optional[str]) -> None:
        logger.warning(f"Step {step_id}: tool '{tool_name}' fuori dall'allowlist")
        self.execution_trace.append({"step_id": step_id, "tool_name": tool_name, "args": arguments, "reasoning": reasoning,
                                     "error": "Tool non consentito"})
        self._note(f"Step {step_id}: '{tool_name}' is not allowed here: use only tools from the catalog.")

    def _arguments_valid(self, step_id: int, tool_name: str, arguments: Dict[str, Any], reasoning: Optional[str]) -> bool:
        error = validate_tool_args(tool_name, arguments, self.available_tools)
        if not error:
            return True
        logger.warning(f"Step {step_id}: errore validazione argomenti per '{tool_name}': {error}")
        self.execution_trace.append({"step_id": step_id, "tool_name": tool_name, "args": arguments,
                                     "reasoning": reasoning, "error": f"Validazione fallita: {error}"})
        self._note(f"Step {step_id}: Chiamata a '{tool_name}' fallita la validazione -> {error}")
        return False

    def _similar_search(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
        """La ricerca web già fatta nel turno a cui questa somiglia troppo, se c'è."""
        if tool_name != "web_search":
            return None
        query = str(arguments.get("query", "")).strip()
        return next((previous for previous in self.search_queries
                     if _query_jaccard_similarity(query, previous) >= SEARCH_SIMILARITY_THRESHOLD), None)

    def _is_repetition(self, step_id: int, tool_name: str, arguments: Dict[str, Any], reasoning: Optional[str]) -> bool:
        """Anti-loop: una chiamata già fatta nel turno (o una ricerca web quasi uguale) chiude il loop e passa alla sintesi."""
        sig = _normalize_call_signature(tool_name, arguments)
        repeated = sig in self.call_counts
        self.call_counts[sig] = self.call_counts.get(sig, 0) + 1

        if tool_name == "web_search" and not repeated:
            previous = self._similar_search(tool_name, arguments)
            if previous is not None:
                logger.info(f"Step {step_id}: query '{arguments.get('query')}' quasi uguale alla precedente '{previous}', trattata come duplicato")
                repeated = True
            else:
                self.search_queries.append(str(arguments.get("query", "")).strip())

        if repeated:
            logger.warning(f"Step {step_id}: Rilevata ripetizione per '{tool_name}'. Interruzione loop ReAct per prevenire cicli infiniti.")
            self._note(f"Step {step_id}: [LOOP INTERROTTO] L'azione '{tool_name}' è già stata eseguita in precedenza. Si procede alla sintesi finale.")
            self.execution_trace.append({
                "step_id": step_id, "tool_name": tool_name, "args": arguments, "reasoning": reasoning,
                "result": {"warning": "Chiamata duplicata bloccata. Interruzione loop ReAct per convergenza rapida."},
                "cached": True, "duplicate_blocked": True,
            })
        return repeated

    def _execute(self, step_id: int, tool_name: str, arguments: Dict[str, Any], call_tag: Tag,
                 clean: bool = False) -> Tuple[Any, bool]:
        """Esegue il tool tramite il registry (guardrail, approvazione, audit); i read-only finiscono in cache.
        `call_tag`: il tag di chi ha scritto gli argomenti; `clean`: riscritti da `_clean_call` (l'audit lo segna)."""
        cache_key = f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"
        if cache_key in self.call_cache:
            logger.info(f"Step {step_id}: hit cache deduplicazione per '{tool_name}'")
            return self.call_cache[cache_key], True
        try:
            res = self.manager.execute_tool(tool_name, arguments, self.allowed_registries, thread_id=self.thread_id, tag=call_tag,
                                            mode=self.mode, security_mode=self.security_mode, task=self.task, clean=clean,
                                            provenance=self._provenance(), **self.audit)
        except Exception as e:
            logger.error(f"Step {step_id}: eccezione esecuzione tool '{tool_name}': {e}")
            return {"error": f"Eccezione durante l'esecuzione: {str(e)}"}, False
        # Solo i risultati veri: un'approvazione in attesa o un blocco non sono il risultato del tool
        if policy.classify_tool(tool_name) == "safe" and not _pending_or_blocked(res):
            self.call_cache[cache_key] = res
        return res, False

    def _approval_result(self, step_id: int, tool_name: str, arguments: Dict[str, Any], res: Dict[str, Any],
                         reasoning: Optional[str], call_tag: Optional[Tag] = None,
                         original: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Il guardrail chiede conferma: salva lo stato del loop, notifica la UI e sospende il turno in attesa della decisione."""
        logger.info(f"Step {step_id}: Tool '{tool_name}' richiede approvazione esplicita ({res.get('risk_reason')}).")
        message = res.get("message", "Richiesta di approvazione richiesta.")
        approval = {
            "request_id": res.get("request_id"),
            "command_preview": res.get("command_preview"),
            "command_prefix": res.get("command_prefix"),
            "risk_reason": res.get("risk_reason"),
        }
        if approval["request_id"]:
            turn_checkpoints.save(approval["request_id"], self.checkpoint_kind, self.checkpoint(
                {"step_id": step_id, "tool_name": tool_name, "arguments": arguments, "reasoning": reasoning,
                 "call_tag": call_tag.to_dict() if call_tag is not None else None, "original": original}))
        q = stream_queue.get()
        if q:
            q.put({"type": "approval_required", "tool_name": tool_name, "arguments": arguments, "message": message, **approval})

        self.execution_trace.append({"step_id": step_id, "tool_name": tool_name, "args": arguments, "result": res,
                                     "reasoning": reasoning, "approval_required": True, "approval_prompt": message, **approval})
        return {"final_response": message, "execution_trace": self.execution_trace, "reasoning_content": reasoning,
                "approval_required": True, "approval_prompt": message, "tag": self.tag.to_dict(), **approval}

    def _record(self, step_id: int, tool_name: str, arguments: Dict[str, Any], res: Any, reasoning: Optional[str], cached: bool,
                call_tag: Tag, original: Optional[Dict[str, Any]] = None):
        """`original`: gli argomenti scelti dal modello, se `_clean_call` li ha riscritti (nella traccia, per la UI)."""
        header = f"Step {step_id}: {tool_name}({arguments})"
        if original is not None:
            # Il modello che ha scelto la chiamata deve sapere perché gli argomenti non sono i suoi
            header += " [arguments rewritten without the private data of this turn: the destination cannot receive them]"
        observation = self._observe(header, tool_name, res, arguments, call_tag)
        logger.info(f"Step {step_id}: Risultato tool '{tool_name}' ({len(observation)} caratteri): {observation[:200]}...")
        entry = {"step_id": step_id, "tool_name": tool_name, "args": arguments, "result": res,
                 "reasoning": reasoning, "cached": cached, "error": res.get("error") if isinstance(res, dict) else None}
        if original is not None:
            entry["clean_rewrite"] = {"original_args": original, "label": call_tag.label.key, "turn_label": self.tag.label.key}
        self.execution_trace.append(entry)

    # --- uscite di dati senza i dati riservati del turno ------------------------

    def _clean_call(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[Tuple[Dict[str, Any], Tag]]:
        """Opzione 3 del design della sensibilità (9.4). La destinazione del tool non può ricevere i dati del turno: prima
        di chiedere conferma, gli argomenti li riscrive una chiamata che vede solo ciò che la destinazione può ricevere
        (la richiesta, i messaggi recenti se possono, i risultati scritti da dati che possono). Il suo tag è l'unione di
        ciò che ha letto, quindi la destinazione la riceve senza chiedere.

        Solo per i tool di sola lettura: chi riscrive non sa quale container, file o evento intendeva il turno, e
        un'azione con argomenti indovinati non deve partire al posto di una conferma.

        None quando non si può: il tool non è di sola lettura, la richiesta stessa non può andare alla destinazione, il
        modello dice che non basta, gli argomenti non sono validi o ripetono una chiamata già fatta (o una ricerca quasi
        uguale). Resta la conferma con gli argomenti originali."""
        if self.request_tag is None or not self.call_llm_structured_fn or policy.classify_tool(tool_name, arguments) != "safe":
            return None
        dest = flows.destination_for_tool(tool_name, arguments, self._mcp_flows)
        if dest is None or flows.can_flow(self.tag, dest).allowed or not flows.can_flow(self.request_tag, dest).allowed:
            return None
        tool = next((t for t in self.available_tools if t.get("name") == tool_name), None)
        if tool is None:
            return None

        read = [self.request_tag]
        recent = None
        if self.recent_turns and self.recent_tag is not None and flows.can_flow(self.recent_tag, dest).allowed:
            recent = self.recent_turns
            read.append(self.recent_tag)
        results = []
        for entry in self.clean_context:
            entry_tag = flows.join(entry["tag"])
            if flows.can_flow(entry_tag, dest).allowed:
                results.append(entry["text"])
                read.append(entry_tag)
        clean_tag = flows.join(*read)

        try:
            out = self.call_llm_structured_fn(
                prompt=prompts.clean_arguments_prompt(self.task, self.now, tool, recent, results),
                system_prompt=prompts.clean_arguments_system_prompt(),
                schema_cls=CleanArguments,
                max_tokens=CLEAN_MAX_TOKENS,
                temperature=0.1,
                max_retries=1,
                thinking="off",
                reasoning_phase="Argomenti senza dati riservati",
                images=[],
                tag=clean_tag,
            )
        except Exception as e:
            logger.warning(f"Riscrittura degli argomenti di '{tool_name}' non riuscita: {e}")
            return None
        if not out or not getattr(out, "enough_information", False):
            logger.info(f"'{tool_name}': informazioni pubbliche insufficienti per riscrivere gli argomenti, si chiede conferma")
            return None
        clean_args = getattr(out, "arguments", None) or {}
        if validate_tool_args(tool_name, clean_args, self.available_tools):
            return None
        clean_dest = flows.destination_for_tool(tool_name, clean_args, self._mcp_flows)
        if clean_dest is not None and not flows.can_flow(clean_tag, clean_dest).allowed:
            return None
        if _normalize_call_signature(tool_name, clean_args) in self.call_counts or self._similar_search(tool_name, clean_args):
            return None
        logger.info(f"'{tool_name}': argomenti riscritti senza i dati {self.tag.label.key} del turno ({clean_tag.label.key})")
        return clean_args, clean_tag

    def _synthesize_after_loop(self) -> Dict[str, Any]:
        """Passi esauriti, anti-loop o stop: sintesi di quanto osservato."""
        if not (self.observations and self.call_llm_fn):
            return self._result("Richiesta completata.")
        answer = self._ask_llm(
            prompts.final_synthesis_prompt(self.task, self.now, self._observation_text()),
            prompts.final_synthesis_system_prompt(),
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
    interleaved: bool = False,
    **restrictions: Any,
) -> Dict[str, Any]:
    """Esegue il loop ReAct secondo la ModePolicy della modalità.

    Con max_tool_calls == 0 (es. chat) risponde direttamente; altrimenti cicla Reason -> Act -> Observe
    fino a una risposta finale o al limite di passi. `restrictions`: gli argomenti solo per nome di `AgentLoop`.
    """
    return AgentLoop(task, mode, memory_context, call_llm_fn, call_llm_structured_fn, thread_id,
                     web_prefetch_data, images, security_mode, interleaved, **restrictions).run()
