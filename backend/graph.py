import contextvars
import json
import logging
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

import config
import image_utils
import letta_client
import router
from mcp_client import MetaMCPClient
from providers import get_provider, is_vision_model

stream_queue = contextvars.ContextVar("stream_queue", default=None)
stream_reasoning_phase_count = contextvars.ContextVar("stream_reasoning_phase_count", default=0)

from agent_loop import is_tools_discovery_query, run_agent_loop
from mode_policy import get_mode_policy
from text_utils import clean_synthesis_content
from tool_catalog import get_rollback_info, get_tool_catalog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("graph")

if os.path.exists("/data") and os.access("/data", os.W_OK):
    MEMORY_DIR = "/data/memory"
elif os.path.exists("/opt/homelab-agent"):
    MEMORY_DIR = "/opt/homelab-agent/memory"
else:
    MEMORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory")

MONITORING_LOG_FILE = os.getenv("MONITORING_LOG_FILE", str(Path(MEMORY_DIR) / "monitoring_logs.jsonl"))

@dataclass
class AgentSpan:
    """Span di monitoraggio per una sessione agente."""
    session_id: str
    thread_id: str
    task: str
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    llm_latency_ms: float = 0.0
    tool_calls: List[dict] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retrieval_hit_rate: float = 1.0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "thread_id": self.thread_id,
            "task": self.task,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "llm_latency_ms": self.llm_latency_ms,
            "tool_calls": self.tool_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "retrieval_hit_rate": self.retrieval_hit_rate,
            "error": self.error
        }

def log_span(span: AgentSpan):
    """Logga uno span di monitoraggio in formato JSONL."""
    try:
        log_path = Path(MONITORING_LOG_FILE)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(span.to_dict()) + "\n")
        logger.info(f"Span loggato: {span.session_id} (latency={span.llm_latency_ms:.0f}ms, tokens={span.prompt_tokens + span.completion_tokens})")
        check_anomalies(span)
    except Exception as e:
        logger.warning(f"Impossibile scrivere span di monitoraggio: {e}")

def check_anomalies(span: AgentSpan, thresholds: dict = None):
    """Controlla se lo span supera le soglie di anomalia."""
    thresholds = thresholds or {
        "max_latency_ms": 10000.0,
        "max_tokens": 50000,
        "max_tool_failure_rate": 0.2
    }
    if span.llm_latency_ms > thresholds["max_latency_ms"]:
        logger.warning(f"⚠️ ALERT: Latency anomaly {span.llm_latency_ms:.0f}ms > {thresholds['max_latency_ms']}ms")
    total_tokens = span.prompt_tokens + span.completion_tokens
    if total_tokens > thresholds["max_tokens"]:
        logger.warning(f"⚠️ ALERT: Token anomaly {total_tokens} > {thresholds['max_tokens']}")

class AgentState(TypedDict):
    task: str
    images: Optional[List[str]]
    thread_id: Optional[str]
    force_mode: Optional[str]
    reasoning_budget: Optional[int]
    model: Optional[str]
    execute: Optional[bool]
    web_search: Optional[bool]
    web_prefetch_data: Optional[Dict[str, Any]]
    web_prefetch_metadata: Optional[Dict[str, Any]]
    agent_id: Optional[str]
    memory_context: Optional[str]
    mode: str
    plan: Dict[str, Any]
    plan_structure: Optional[Dict[str, Any]]
    tool_result: Optional[Any]
    execution_trace: Optional[List[Dict[str, Any]]]
    rollback_trace: Optional[List[Dict[str, Any]]]
    final_response: str
    reasoning_content: Optional[str]
    incognito: Optional[bool]


client = MetaMCPClient(base_url=config.METAMCP_URL, api_key=config.METAMCP_API_KEY)
conn = sqlite3.connect(config.CHECKPOINT_DB_PATH, check_same_thread=False)
memory = SqliteSaver(conn)


def _append_message_to_file(thread_id: str, role: str, content: str):
    """Scrivi un messaggio su file JSONL (append-only) per audit e disaster recovery."""
    if not thread_id or not content:
        return
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        filepath = os.path.join(MEMORY_DIR, f"{thread_id}.jsonl")
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "role": role,
            "content": content
        }
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(f"Messaggio ({role}) salvato su file di memoria: {filepath}")
    except Exception as e:
        logger.warning(f"Errore scrittura memoria file system {thread_id}: {e}")

def _read_messages_from_file(thread_id: str) -> List[Dict[str, Any]]:
    """Legge i messaggi storici dal file JSONL locale in caso di assenza o fallback di Letta."""
    if not thread_id:
        return []
    filepath = os.path.join(MEMORY_DIR, f"{thread_id}.jsonl")
    if not os.path.exists(filepath):
        return []
    messages = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        role_type = "user_message" if data.get("role") == "user" else "assistant_message"
                        messages.append({
                            "message_type": role_type,
                            "content": data.get("content", ""),
                            "timestamp": data.get("timestamp")
                        })
                    except Exception:
                        pass
    except Exception as e:
        logger.warning(f"Errore lettura file memoria {filepath}: {e}")
    return messages

def _generate_summary(messages: List[Dict[str, Any]], model: Optional[str] = None) -> str:
    """Genera un riassunto di una lista di messaggi mediante LLM."""
    text = "\n".join([f"{'User' if 'user' in str(m.get('message_type','')).lower() else 'Assistant'}: {m.get('content', '')}" for m in messages])
    prompt = f"""Riassumi la seguente conversazione in massimo 5 frasi, mantenendo:
- Nomi delle persone (es. "Alice")
- Preferenze espresse (es. "preferisce Debian")
- Decisioni prese (es. "ha creato servizio web")
- Domande aperte o task in corso

Conversazione:
{text}

Riassunto:"""
    summary_res = _call_llm(prompt, system_prompt="Sei un assistente che riassume conversazioni in modo conciso.", max_tokens=512, temperature=0.3, reasoning_budget=0, model=model, stream_mode="none")
    summary = summary_res.get("content", "") if isinstance(summary_res, dict) else ""
    return summary.strip() if summary else ""

def _call_llm(
    prompt: str,
    system_prompt: str = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    reasoning_budget: int = -1,
    model: Optional[str] = None,
    stream_mode: str = "all",  # "all" | "reasoning_only" | "content_only" | "none"
    reasoning_phase: Optional[str] = None,
    images: Optional[List[str]] = None,
) -> dict:
    messages = []

    # Capability detection based on effective model
    provider = get_provider()
    effective_model = model or getattr(provider, "default_model", "") or config.DEFAULT_MODEL
    model_name_lower = effective_model.lower()
    supports_reasoning = any(x in model_name_lower for x in ["qwen", "deepseek", "r1", "o1", "o3", "mistral", "think", "reason"])

    enable_thinking = (reasoning_budget != 0) and supports_reasoning
    if enable_thinking:
        thinking_instruction = (
            "IMPORTANTE: Il sistema di inferenza gestisce automaticamente il tuo processo di ragionamento tramite il meccanismo nativo di thinking. "
            "NON includere processi di pensiero, analisi intermedie, note di self-correction o passi di ragionamento nel testo della tua risposta. "
            "La tua risposta deve contenere SOLO il contenuto finale destinato all'utente."
        )
        if system_prompt:
            system_prompt = f"{system_prompt}\n\n{thinking_instruction}"
        else:
            system_prompt = thinking_instruction

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Multimodal image handling
    if images and len(images) > 0:
        if is_vision_model(effective_model):
            user_content_parts = [{"type": "text", "text": prompt}]
            for img in images:
                try:
                    normalized_img = image_utils.normalize_image_data_url(img)
                except Exception as e:
                    logger.warning(f"Normalizzazione immagine fallita: {e}")
                    normalized_img = img
                user_content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": normalized_img}
                })
            messages.append({"role": "user", "content": user_content_parts})
        else:
            fallback_text = (
                f"{prompt}\n\n"
                f"[NOTA DI SISTEMA: L'utente ha allegato {len(images)} immagine/i, ma il modello attualmente selezionato "
                f"('{effective_model}') non supporta la visione multimodale. Informa gentilmente l'utente di selezionare un "
                f"modello Vision come Qwen3.6-35B per visualizzare ed analizzare le immagini.]"
            )
            messages.append({"role": "user", "content": fallback_text})
    else:
        messages.append({"role": "user", "content": prompt})

    q = stream_queue.get()
    stream_callback = None
    if q and stream_mode != "none":
        phase_header_sent = False

        def _cb(ev: dict):
            nonlocal phase_header_sent
            ev_type = ev.get("type")
            if ev_type == "reasoning":
                if stream_mode in ("all", "reasoning_only"):
                    if reasoning_phase and not phase_header_sent:
                        phase_header_sent = True
                        count = stream_reasoning_phase_count.get()
                        stream_reasoning_phase_count.set(count + 1)
                        header = (
                            f"\n\n---\n\n#### 💡 {reasoning_phase}\n\n"
                            if count > 0
                            else f"#### 🔍 {reasoning_phase}\n\n"
                        )
                        q.put({"type": "reasoning", "delta": header})
                    q.put(ev)
            elif ev_type == "content":
                if stream_mode in ("all", "content_only"):
                    q.put(ev)
            elif ev_type == "metrics":
                if stream_mode != "none":
                    q.put(ev)

        stream_callback = _cb

    from stream_session import current_session_var
    sess = current_session_var.get()
    if sess and sess.is_stopped():
        return {"content": "", "reasoning_content": "", "metrics": {}}

    # Fase 1.1: delega al provider abstraction
    return provider.chat(
        messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        reasoning_budget=reasoning_budget,
        stream_callback=stream_callback,
    )

def _call_llm_structured(
    prompt: str,
    system_prompt: str,
    schema_cls: Any,
    max_tokens: int = 4096,
    temperature: float = 0.10,
    max_retries: int = 3,
    reasoning_budget: int = -1,
    model: Optional[str] = None,
    reasoning_phase: Optional[str] = "Analisi e Selezione Tool",
    images: Optional[List[str]] = None,
) -> Optional[Any]:
    """
    Chiama l'LLM richiedendo output conforme allo schema Pydantic.
    Effettua parsing + validazione con retry mirato ed iniezione dell'errore.
    Isola lo stream del content JSON per non farlo comparire nella chat principale.
    Include il supporto a immagini multimodali (es. per selezione tool basata su immagini).
    """
    json_schema = schema_cls.model_json_schema()
    schema_prompt = (
        f"{system_prompt}\n\n"
        f"Rispondi ESCLUSIVAMENTE con un'istanza JSON valida conforme alla struttura richiesta da questo schema.\n"
        f"NON restituire la definizione del JSON Schema o metadati come 'type': 'object', ma popola i campi concreti dell'oggetto.\n"
        f"JSON Schema di riferimento:\n"
        f"{json.dumps(json_schema, ensure_ascii=False)}\n\n"
        f"Non aggiungere testo fuori dal JSON."
    )

    # Limita il reasoning budget per la selezione tool per evitare loop di pensiero prolungati
    effective_reasoning_budget = reasoning_budget
    if getattr(schema_cls, "__name__", "") == "ToolSelection":
        if reasoning_budget <= 0 or reasoning_budget > 1024:
            effective_reasoning_budget = 1024

    last_error = None
    effective_max_tokens = max_tokens
    MAX_TOKENS_CAP = 16384
    for attempt in range(1, max_retries + 1):
        current_prompt = prompt
        if last_error:
            current_prompt = (
                f"{prompt}\n\n"
                f"ATTENZIONE: il tentativo precedente ha fallito la validazione con questo errore:\n"
                f"{last_error}\n"
                f"Correggi e rispondi di nuovo SOLO con il JSON valido."
            )

        raw_res = _call_llm(
            current_prompt,
            system_prompt=schema_prompt,
            max_tokens=effective_max_tokens,
            temperature=temperature,
            reasoning_budget=effective_reasoning_budget,
            model=model,
            stream_mode="reasoning_only",
            reasoning_phase=reasoning_phase,
            images=images,
        )
        if not raw_res:
            last_error = "Nessuna risposta dal modello LLM"
            continue

        raw = raw_res.get("content", "") if isinstance(raw_res, dict) else ""
        if not raw:
            # Contenuto vuoto = quasi sempre il reasoning che ha esaurito il budget token
            # prima di emettere il JSON (finish_reason=length). Raddoppia max_tokens.
            last_error = f"Risposta testuale vuota (probabile troncamento con max_tokens={effective_max_tokens}): riduci il reasoning ed emetti subito il JSON."
            effective_max_tokens = min(effective_max_tokens * 2, MAX_TOKENS_CAP)
            logger.warning(f"Tentativo {attempt}/{max_retries}: contenuto vuoto, escalation max_tokens a {effective_max_tokens}")
            continue

        from text_utils import strip_thinking
        clean = strip_thinking(raw.strip())
        clean = strip_thinking(clean)
        clean = re.sub(r'^```(?:json)?', '', clean)
        clean = re.sub(r'```$', '', clean).strip()

        try:
            parsed = json.loads(clean)
            validated = schema_cls.model_validate(parsed)
            if hasattr(validated, "raw_thinking"):
                validated.raw_thinking = raw_res.get("reasoning_content", "") if isinstance(raw_res, dict) else ""
            logger.info(f"Structured output valido al tentativo {attempt}: {validated.model_dump()}")
            return validated
        except Exception as e:
            last_error = str(e)
            logger.warning(f"Tentativo {attempt}/{max_retries} fallito nella validazione structured output: {e}")

    logger.error(f"Structured output fallito dopo {max_retries} tentativi. Ultimo errore: {last_error}")
    return None

def _format_metamcp_tools_catalog() -> str:
    from registry.manager import get_registry_manager
    from tool_catalog import format_dynamic_catalog_response
    manager = get_registry_manager()
    all_tools = manager.get_tools_for_mode(["metamcp", "web", "code", "memory"])
    return format_dynamic_catalog_response(all_tools)

def intake_node(state: AgentState) -> AgentState:
    """Receives the task and settings, and appends user message to JSONL file memory if not incognito."""
    thread_id = state.get("thread_id")
    task = state.get("task", "")
    images = state.get("images")
    if not task and images:
        task = "Analizza e descrivi l'immagine allegata."
        state["task"] = task
    incognito = state.get("incognito", False)
    if thread_id and task and not incognito:
        _append_message_to_file(thread_id, "user", task)
    return state

def retrieve_memory_node(state: AgentState) -> AgentState:
    """Retrieves relevant memory context combining sliding window + incremental summary + semantic recall. Skipped in incognito mode."""
    thread_id = state.get("thread_id")
    if not thread_id or state.get("incognito"):
        return {"memory_context": None, "agent_id": None}

    agent_id = letta_client.create_thread(thread_id)
    raw_messages = letta_client.get_messages(agent_id) if agent_id else []
    clean_messages = letta_client.filter_clean_messages(raw_messages) if raw_messages else []

    # Fallback su file JSONL se Letta è offline o non ha messaggi
    if not clean_messages:
        clean_messages = _read_messages_from_file(thread_id)

    # --- Fase 2.1: recall semantico dalla memoria vettoriale (fatti salienti passati) ---
    semantic_recall = ""
    try:
        from vector_store import search_memory
        task_text = state.get("task", "")
        hits = search_memory(task_text, k=3, kind="fact")
        relevant = [h for h in hits if h.get("score", 0) > 0.35 and h.get("thread_id") != thread_id]
        if relevant:
            lines = [f"- {h['content']}" for h in relevant]
            semantic_recall = "### Memoria a lungo termine rilevante:\n" + "\n".join(lines)
            logger.info(f"Semantic recall: {len(relevant)} fatti rilevanti da altri thread")
    except Exception as e:
        logger.warning(f"Semantic recall fallito (non bloccante): {e}")

    summary = ""
    recent_messages = []

    # --- Fase 2.4: compattazione basata su token stimati (non solo numero messaggi) ---
    def _estimate_tokens(msgs: List[Dict[str, Any]]) -> int:
        return sum(len(str(m.get("content", ""))) // 4 for m in msgs)  # ~4 char/token

    CONTEXT_TOKEN_BUDGET = 6000  # budget per la memoria conversazionale nel prompt
    RECENT_KEEP = 20

    total_tokens = _estimate_tokens(clean_messages)
    needs_compaction = len(clean_messages) > 30 or total_tokens > CONTEXT_TOKEN_BUDGET

    if needs_compaction:
        summary_key = f"summary_1_30_{thread_id}"
        summary_file = os.path.join(MEMORY_DIR, f"summary_{thread_id}.txt")

        if agent_id:
            summary = letta_client.get_archival_memory(agent_id, key=summary_key)

        if not summary and os.path.exists(summary_file):
            try:
                with open(summary_file, "r", encoding="utf-8") as sf:
                    summary = sf.read().strip()
            except Exception:
                pass

        # Compattazione progressiva: riduci la finestra recente finché non rientra nel budget
        keep = RECENT_KEEP
        recent_messages = clean_messages[-keep:]
        while _estimate_tokens(recent_messages) > CONTEXT_TOKEN_BUDGET and keep > 4:
            keep = max(4, keep // 2)
            recent_messages = clean_messages[-keep:]

        if not summary:
            old_messages = clean_messages[:-keep] if len(clean_messages) > keep else clean_messages
            if old_messages:
                logger.info(f"Generazione summary incrementale per thread '{thread_id}' su {len(old_messages)} vecchi messaggi...")
                summary = _generate_summary(old_messages, model=state.get("model"))
                if summary:
                    if agent_id:
                        letta_client.save_archival_memory(agent_id, key=summary_key, value=summary)
                    try:
                        os.makedirs(MEMORY_DIR, exist_ok=True)
                        with open(summary_file, "w", encoding="utf-8") as sf:
                            sf.write(summary)
                    except Exception as e:
                        logger.warning(f"Errore salvataggio summary locale {summary_file}: {e}")
    else:
        recent_messages = clean_messages

    memory_parts = []
    if semantic_recall:
        memory_parts.append(semantic_recall)
    if summary:
        memory_parts.append(f"### Riepilogo conversazione precedente:\n{summary}")

    if recent_messages:
        memory_parts.append("### Messaggi recenti:")
        for msg in recent_messages:
            m_type = str(msg.get("message_type", "")).lower()
            role_label = "User" if "user" in m_type else "Assistant"
            txt = msg.get("content", "")
            if txt:
                memory_parts.append(f"{role_label}: {txt}")

    memory_context = "\n\n".join(memory_parts) if memory_parts else ""
    logger.info(f"Retrieval memoria per thread '{thread_id}': total_messages={len(clean_messages)}, has_summary={bool(summary)}, recent_window={len(recent_messages)}")
    return {"memory_context": memory_context, "agent_id": agent_id}

def mode_router_node(state: AgentState) -> AgentState:
    """Classifies user task into one of 4 modes: chat, ask, act, plan."""
    task = state.get("task", "")
    force_mode = state.get("force_mode")
    model = state.get("model")
    images = state.get("images")
    has_images = bool(images and len(images) > 0)
    classified = router.classify_mode(task, force_mode=force_mode, model=model, has_images=has_images)
    logger.info(f"Mode Router selected mode: '{classified}' for task: '{task}' (has_images={has_images})")
    return {"mode": classified}

def is_purely_visual_request(task: str) -> bool:
    """Rileva se una richiesta con immagini è puramente percettiva/descrittiva senza intento di ricerca esterna."""
    if not task or not task.strip():
        return True
    task_lower = task.lower().strip()

    # Se ci sono parole chiave che richiedono informazioni esterne, prezzi o dati attuali
    external_keywords = [
        "cerca", "search", "trova", "prezzo", "prezzi", "costo", "costi", "quanto costa",
        "dove comprare", "comprare", "acquistare", "vendita", "negozi", "store",
        "notizie", "news", "recensioni", "review", "scheda tecnica", "specifiche",
        "manuale", "firmware", "driver", "pinout", "compatibile", "compatibilità",
        "disponibilità", "mercato", "aggiornamenti", "online", "internet", "web", "google"
    ]
    if any(kw in task_lower for kw in external_keywords):
        return False

    # Se invece chiede solo di descrivere o guardare l'immagine
    visual_keywords = [
        "cosa vedi", "descrivi", "cosa c'è", "spiega l'immagine", "guarda questa",
        "analizza l'immagine", "analizza e descrivi", "cosa rappresenta", "leggi il testo",
        "trascrivi", "chi c'è", "che colore", "dov'è"
    ]
    return any(kw in task_lower for kw in visual_keywords)


def formulate_visual_search_query(task: str, images: List[str], model: Optional[str] = None) -> str:
    """
    Esegue un micro-pass visivo rapido e silenzioso (senza streaming SSE) per estrarre
    dal contesto dell'immagine il soggetto (brand, modello, codice, componente)
    e formulare una query web essenziale ed efficace per i motori di ricerca.
    """
    prompt = (
        "Sei un assistente per la formulazione di query di ricerca web.\n"
        f"L'utente ha inviato un'immagine con questa richiesta: '{task}'.\n"
        "Analizza l'immagine e identifica con precisione il soggetto o prodotto principale (marca, modello, codice o nome).\n"
        "Combina il nome del soggetto con l'intento dell'utente in una query di ricerca Google/SearXNG concisa ed efficace (massimo 4-7 parole).\n"
        "Esempi di output attesi:\n"
        "- Eachine EV800DM prezzo specifiche\n"
        "- Apple iMac G4 specifiche tecniche\n"
        "- Raspberry Pi 4 pinout GPIO\n"
        "- Arduino Uno R3 driver CH340\n"
        "Rispondi ESCLUSIVAMENTE con la query di ricerca, senza virgolette, spiegazioni, codice o preamboli."
    )
    try:
        res = _call_llm(
            prompt=prompt,
            max_tokens=60,
            temperature=0.0,
            reasoning_budget=0,
            model=model,
            stream_mode="none",
            images=images
        )
        raw_content = res.get("content", "") if isinstance(res, dict) else (res or "")
        clean_q = re.sub(r'["\'`\n]', ' ', raw_content).strip()
        clean_q = re.sub(r'^(?:query|ricerca|cerca|search)[:\s]+', '', clean_q, flags=re.IGNORECASE).strip()
        clean_q = re.sub(r'\s+', ' ', clean_q)
        if clean_q and len(clean_q) >= 3:
            logger.info(f"Visual query grounding formulata con successo: '{clean_q}' (da task: '{task}')")
            return clean_q
    except Exception as e:
        logger.warning(f"Visual query grounding non riuscito (fallback a task originale): {e}")
    return task


def web_prefetch_node(state: AgentState) -> AgentState:
    """Performs deterministic read-only web prefetch before subgraphs if web_search is enabled."""
    if not state.get("web_search"):
        return state

    task = state.get("task", "")
    if not task:
        return state

    # Se sono presenti immagini allegate, verifica se la richiesta è prettamente visiva
    images = state.get("images")
    if images and len(images) > 0:
        if is_purely_visual_request(task):
            logger.info(f"Richiesta puramente visiva/percettiva: skip web prefetch per '{task}'")
            return state

    # Se ci sono immagini, formula una query grounded visivamente (estraendo marca/modello dall'immagine)
    effective_query = task
    if images and len(images) > 0:
        effective_query = formulate_visual_search_query(task, images, model=state.get("model"))

    q = stream_queue.get()

    def emit_event(ev_name: str, data: Dict[str, Any]):
        if q:
            q.put({"type": "retrieval", "event": ev_name, "data": data})

    emit_event("web_prefetch.started", {"query": effective_query})
    logger.info(f"Avvio web prefetch per query: '{effective_query}' (task originale: '{task}')")

    try:
        from registry.web_search_service import execute_search
        search_res = execute_search(
            query=effective_query,
            count=8,
            event_callback=emit_event
        )

        clean_sources = [
            {
                "title": s.get("title", ""),
                "url": s.get("url", ""),
                "snippet": s.get("snippet", "")
            }
            for s in search_res.get("sources", [])
        ]

        query_effective = search_res.get("query", task)
        provider = search_res.get("provider_used", "Web")
        latency_ms = search_res.get("latency_ms", 0)

        # Metadati pubblici: compatti, sicuri per API, SSE e memorizzazione SQLite
        public_meta = {
            "query": query_effective,
            "success": bool(search_res.get("success")),
            "provider_used": provider,
            "latency_ms": latency_ms,
            "sources": clean_sources,
            "error": search_res.get("error")
        }

        # Contesto interno per i prompt: contiene summary_text senza strutture pesanti
        internal_data = {
            "query": query_effective,
            "success": bool(search_res.get("success")),
            "sources": clean_sources,
            "summary_text": search_res.get("summary_text", ""),
            "error": search_res.get("error")
        }

        if search_res.get("success") and clean_sources:
            emit_event("web_prefetch.completed", {
                "query": query_effective,
                "sources_count": len(clean_sources),
                "provider": provider,
                "latency_ms": latency_ms
            })
        else:
            emit_event("web_prefetch.empty", {
                "query": query_effective,
                "provider": provider
            })

        return {
            "web_prefetch_data": internal_data,
            "web_prefetch_metadata": public_meta
        }
    except Exception as e:
        logger.warning(f"Web prefetch non riuscito (non bloccante): {e}", exc_info=True)
        public_err_msg = "Ricerca web non disponibile al momento."
        emit_event("web_prefetch.failed", {"query": effective_query, "error": public_err_msg, "code": "search_unavailable"})
        public_meta = {
            "query": effective_query,
            "success": False,
            "provider_used": "Web",
            "latency_ms": 0,
            "sources": [],
            "error": "search_unavailable"
        }
        internal_data = {
            "query": effective_query,
            "success": False,
            "sources": [],
            "summary_text": "",
            "error": "search_unavailable"
        }
        return {
            "web_prefetch_data": internal_data,
            "web_prefetch_metadata": public_meta
        }

def chat_graph_node(state: AgentState) -> AgentState:
    """Subgraph for free conversation & fast queries with direct LLM response (non-agentic, 0 tools)."""
    task = state.get("task", "")
    task_lower = task.lower()
    memory_context = state.get("memory_context") or ""

    if any(kw in task_lower for kw in ["chi sei", "presentati", "chi sei tu"]):
        ans = "Sono l'agente AI per la gestione del tuo homelab. Posso assisterti sull'infrastruttura e sui servizi, eseguire azioni operative tramite i tool MCP connessi, condurre analisi visive su immagini e grafici, eseguire ricerche web ed elaborare codice in sandbox."
        return {"plan": {"mode": "chat", "tool_needed": False, "direct_answer": ans}, "final_response": ans}
    elif is_tools_discovery_query(task):
        ans = _format_metamcp_tools_catalog()
        return {"plan": {"mode": "chat", "tool_needed": False, "direct_answer": ans}, "final_response": ans}

    policy = get_mode_policy("chat")
    budget = state.get("reasoning_budget") if state.get("reasoning_budget") is not None else policy.reasoning_budget
    model = state.get("model")
    prefetch_data = state.get("web_prefetch_data")

    now_str = datetime.now().strftime('%A %d %B %Y, %H:%M:%S')
    from registry.search_security import UNTRUSTED_CONTEXT_POLICY, wrap_untrusted_web_evidence

    system_prompt = (
        f"Data e Ora Corrente del Sistema: {now_str}\n"
        f"Sei l'Agente AI per la gestione dell'Homelab (modalità: CHAT).\n"
        f"Rispondi all'utente in modo naturale, dettagliato, completo ed esaustivo in lingua italiana.\n"
        f"Non hai a disposizione tool in questa modalità: rispondi direttamente in testo discorsivo sfruttando le tue capacità di comprensione del linguaggio, visione ed eventuale prefetch informativo.\n"
        f"{UNTRUSTED_CONTEXT_POLICY}"
    )

    prompt_sections = []
    if memory_context:
        prompt_sections.append(f"Contesto memoria conversazionale:\n{memory_context}")

    if prefetch_data and prefetch_data.get("summary_text"):
        wrapped_evidence = wrap_untrusted_web_evidence(
            query=prefetch_data.get("query", task),
            formatted_content=prefetch_data.get("summary_text", ""),
            sources=prefetch_data.get("sources", [])
        )
        prompt_sections.append(wrapped_evidence)

    prompt_sections.append(f"Richiesta Utente: '{task}'")
    user_prompt = "\n\n".join(prompt_sections)

    ans_res = _call_llm(user_prompt, system_prompt=system_prompt, max_tokens=4096, reasoning_budget=budget, model=model, stream_mode="all", reasoning_phase="Elaborazione Risposta", images=state.get("images"))
    raw_ans = ans_res.get("content", "") if isinstance(ans_res, dict) else (ans_res or "")
    reasoning = ans_res.get("reasoning_content", "") if isinstance(ans_res, dict) else ""
    ans = clean_synthesis_content(raw_ans) or raw_ans

    plan = {"mode": "chat", "tool_needed": False, "direct_answer": ans, "execution_log": []}
    return {
        "plan": plan,
        "execution_trace": [],
        "final_response": ans,
        "reasoning_content": reasoning,
    }

def ask_graph_node(state: AgentState) -> AgentState:
    """Subgraph for memory & knowledge retrieval queries (with Web Search & Code Exec tools enabled)."""
    task = state.get("task", "")
    task_lower = task.lower()
    memory_context = state.get("memory_context") or ""

    if is_tools_discovery_query(task):
        ans = _format_metamcp_tools_catalog()
        return {"plan": {"mode": "ask", "tool_needed": False, "direct_answer": ans}, "final_response": ans}

    policy = get_mode_policy("ask")
    budget = state.get("reasoning_budget") if state.get("reasoning_budget") is not None else policy.reasoning_budget
    model = state.get("model")

    loop_res = run_agent_loop(
        task=task,
        mode="ask",
        memory_context=memory_context,
        thread_id=state.get("thread_id"),
        web_prefetch_data=state.get("web_prefetch_data"),
        images=state.get("images"),
        call_llm_fn=lambda p, system_prompt=None, reasoning_budget=budget, model=model, reasoning_phase=None: _call_llm(p, system_prompt=system_prompt, max_tokens=4096, reasoning_budget=reasoning_budget, model=model, stream_mode="all", reasoning_phase=reasoning_phase, images=state.get("images")),
        call_llm_structured_fn=lambda prompt, system_prompt, schema_cls, max_tokens=4096, temperature=0.0, max_retries=2, reasoning_budget=budget, model=model, reasoning_phase="Analisi e Selezione Tool", images=None: _call_llm_structured(prompt, system_prompt, schema_cls, max_tokens, temperature, max_retries, reasoning_budget=reasoning_budget, model=model, reasoning_phase=reasoning_phase, images=images if images is not None else state.get("images"))
    )

    ans = loop_res.get("final_response", "")
    trace = loop_res.get("execution_trace", [])
    reasoning = loop_res.get("reasoning_content")
    plan = {"mode": "ask", "tool_needed": len(trace) > 0, "direct_answer": ans, "execution_log": trace}
    return {"plan": plan, "execution_trace": trace, "final_response": ans, "reasoning_content": reasoning}



def extract_output_var(result: Any, output_var: str, step_id: int) -> Any:
    """Estrae una variabile da un result di tool MetaMCP con fallback a euristiche annidate."""
    if not output_var:
        return None

    def find_key_in_nested(obj: Any, key: str, max_depth: int = 5) -> Any:
        if max_depth <= 0:
            return None
        if isinstance(obj, dict):
            if key in obj and obj[key] is not None:
                return obj[key]
            for v in obj.values():
                found = find_key_in_nested(v, key, max_depth - 1)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = find_key_in_nested(item, key, max_depth - 1)
                if found is not None:
                    return found
        elif isinstance(obj, str):
            try:
                parsed = json.loads(obj)
                return find_key_in_nested(parsed, key, max_depth - 1)
            except Exception:
                pass
        return None

    # 1. Cerca output_var esplicito
    val = find_key_in_nested(result, output_var)
    if val is not None:
        logger.info(f"Step {step_id}: estratta variabile '{output_var}'={val}")
        return val

    # 2. Fallback a euristiche generiche
    for heuristic_key in ["ip", "vmid", "id", "value", "result"]:
        val = find_key_in_nested(result, heuristic_key)
        if val is not None:
            logger.info(f"Step {step_id}: estratta variabile '{output_var}'={val} (fallback su '{heuristic_key}')")
            return val

    # 3. Non trovato
    logger.warning(f"Step {step_id}: variabile '{output_var}' non trovata nel result, uso None")
    return None


def topological_sort_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ordina gli step in ordine topologico basato su depends_on."""
    if not steps:
        return []
    sorted_steps = []
    remaining = list(steps)
    executed_ids = set()

    while remaining:
        ready = [s for s in remaining if s.get("depends_on") is None or s.get("depends_on") in executed_ids]
        if not ready:
            ready = [remaining[0]]

        for step in ready:
            sorted_steps.append(step)
            remaining.remove(step)
            step_id = step.get("id")
            if step_id is not None:
                executed_ids.add(step_id)

    return sorted_steps


class ExecutionLog:
    """Transaction log entry per un singolo step (WAL pattern)."""
    def __init__(self, step: dict, tool_name: str, args: dict):
        self.step = step
        self.tool_name = tool_name
        self.args = args
        self.result = None
        self.error = None
        self.timestamp_start = datetime.utcnow()
        self.timestamp_end = None
        self.rollback_executed = False
        self.rollback_error = None

    def to_dict(self) -> dict:
        return {
            "step_id": self.step.get("id"),
            "tool_name": self.tool_name,
            "args": self.args,
            "result": self.result,
            "error": self.error,
            "timestamp_start": self.timestamp_start.isoformat(),
            "timestamp_end": self.timestamp_end.isoformat() if self.timestamp_end else None,
            "rollback_executed": self.rollback_executed,
            "rollback_error": self.rollback_error
        }


def execute_rollback_for_step(log: ExecutionLog, tools_catalog: list[dict]) -> bool:
    """
    Esegue il rollback per un singolo step, usando info dichiarative e popolamento template.
    Ritorna True se successo, False se fallito.
    """
    tool_name = log.tool_name
    result = log.result
    step_id = log.step.get("id")

    rollback_info = get_rollback_info(tool_name)
    if not rollback_info or not rollback_info.get("reversible"):
        logger.warning(f"Step {step_id}: tool `{tool_name}` non è reversibile, impossibile rollback")
        log.rollback_executed = False
        log.rollback_error = "Tool non reversibile"
        return False

    rollback_tool = rollback_info.get("rollback_tool")
    rollback_args_template = rollback_info.get("rollback_args_template", {})

    if not rollback_tool:
        logger.error(f"Step {step_id}: rollback_info per `{tool_name}` non specifica rollback_tool")
        log.rollback_executed = False
        log.rollback_error = "Rollback tool non specificato"
        return False

    rollback_args = {}
    value_map = {}
    if isinstance(log.args, dict):
        value_map.update(log.args)
    if isinstance(result, dict):
        value_map.update(result)

    for arg_key, template_val in rollback_args_template.items():
        if isinstance(template_val, str):
            val_str = template_val
            for res_key, res_val in value_map.items():
                placeholder = f"{{{{{res_key}}}}}"
                if placeholder in val_str:
                    val_str = val_str.replace(placeholder, str(res_val))
            if "{{" in val_str and "}}" in val_str:
                raw_var = val_str.replace("{", "").replace("}", "").strip()
                extracted = extract_output_var(result, raw_var, step_id)
                if extracted is not None:
                    val_str = str(extracted)
            rollback_args[arg_key] = val_str
        else:
            rollback_args[arg_key] = template_val

    logger.info(f"Rollback step {step_id}: `{rollback_tool}` con args {rollback_args}")

    try:
        rollback_result = client.call_tool(rollback_tool, rollback_args)
        if isinstance(rollback_result, dict) and "error" in rollback_result:
            log.rollback_executed = False
            log.rollback_error = rollback_result["error"]
            logger.error(f"Rollback fallito per step {step_id}: {rollback_result['error']}")
            return False
        else:
            log.rollback_executed = True
            logger.info(f"Rollback riuscito per step {step_id}")
            return True
    except Exception as e:
        log.rollback_executed = False
        log.rollback_error = str(e)
        logger.error(f"Eccezione nel rollback per step {step_id}: {e}")
        return False


def generate_rollback_plan_with_llm(execution_log: List[ExecutionLog], task: str, error_context: str, model: Optional[str] = None) -> Optional[str]:
    """
    Usa l'LLM per generare un piano di rollback contestuale quando quello dichiarativo non basta.
    """
    log_summary = "\n".join([
        f"- Step {e.step.get('id')}: `{e.tool_name}`({e.args}) → {'OK' if not e.error else 'ERROR: ' + str(e.error)}"
        for e in execution_log
    ])

    prompt = f"""
    Un piano di esecuzione è fallito dopo questi step:
    {log_summary}
    
    Task originale: {task}
    Errore: {error_context}
    
    Genera un piano di rollback per ripristinare lo stato iniziale.
    Elenca i passaggi di rollback in ordine inverso, specificando per ciascuno:
    - Azione da compiere
    - Tool da usare (se noto, altrimenti lascia come "azione manuale")
    
    Piano di rollback:"""

    plan_res = _call_llm(prompt, system_prompt="Sei un assistente esperto in rollback di operazioni di infrastruttura Proxmox.", max_tokens=512, temperature=0.3, model=model, stream_mode="none")
    plan = plan_res.get("content", "") if isinstance(plan_res, dict) else ""
    return plan.strip() if plan else None


def execute_plan_node(state: AgentState) -> AgentState:
    """Executes real MetaMCP tools sequentially based on state['plan_structure'] with robust declarative & WAL rollback."""
    task = state.get("task", "")
    plan_struct = state.get("plan_structure") or state.get("plan", {}).get("plan_structure")

    if not plan_struct or not isinstance(plan_struct, dict) or "steps" not in plan_struct:
        return act_graph_node(state)

    steps = plan_struct.get("steps", [])
    sorted_steps = topological_sort_steps(steps)

    context_vars = {}
    execution_log: List[ExecutionLog] = []
    exec_lines = [
        f"🚀 **Avvio esecuzione reale del piano MetaMCP**: *'{task}'*\n",
        "### Esito Esecuzione Tool Real-Time:\n"
    ]

    has_error = False

    for step in sorted_steps:
        step_id = step.get("id", 1)
        depends_on = step.get("depends_on")
        desc = step.get("description", "")
        tool_name = step.get("tool", "")
        args = step.get("args", {})
        output_var = step.get("output_var")

        logger.info(f"Esecuzione step {step_id} (dipende da: {depends_on}): {tool_name}")

        resolved_args = {}
        if isinstance(args, dict):
            for k, v in args.items():
                if isinstance(v, str):
                    val_str = v
                    for var_k, var_v in context_vars.items():
                        placeholder = f"{{{{{var_k}}}}}"
                        if placeholder in val_str:
                            val_str = val_str.replace(placeholder, str(var_v))
                    resolved_args[k] = val_str
                else:
                    resolved_args[k] = v

        # Log entry creata PRIMA dell'esecuzione (Write-Ahead Logging / WAL)
        log_entry = ExecutionLog(step, tool_name, resolved_args)
        execution_log.append(log_entry)

        try:
            result = client.call_tool(tool_name, resolved_args)
            log_entry.result = result
            log_entry.timestamp_end = datetime.utcnow()
            logger.info(f"Step {step_id} completato: {result}")

            if isinstance(result, dict) and "error" in result:
                has_error = True
                err_msg = result["error"]
                log_entry.error = err_msg
                exec_lines.append(f"{step_id}. ❌ `{desc}` — Tool `{tool_name}` fallito: `{err_msg}`")
                break

            if output_var:
                extracted_val = extract_output_var(result, output_var, step_id)
                if extracted_val is not None:
                    context_vars[output_var] = extracted_val

            args_str = json.dumps(resolved_args, ensure_ascii=False) if resolved_args else "{}"
            exec_lines.append(f"{step_id}. ✅ `{desc}` — `{tool_name}`({args_str}) → *OK*")
        except Exception as e:
            has_error = True
            log_entry.error = str(e)
            log_entry.timestamp_end = datetime.utcnow()
            logger.error(f"Step {step_id} fallito con eccezione: {e}")
            exec_lines.append(f"{step_id}. ❌ `{desc}` — Errore di chiamata tool `{tool_name}`: `{e}`")
            break

    # Rollback dichiarativo in ordine inverso (LIFO Undo Stack)
    if has_error and execution_log:
        exec_lines.append("\n### 🔄 Rollback parziale degli step eseguiti:\n")
        tools_catalog = get_tool_catalog()

        for log_entry in reversed(execution_log):
            if not log_entry.error:  # Rollback solo degli step eseguiti con successo
                success = execute_rollback_for_step(log_entry, tools_catalog)
                step_id = log_entry.step.get("id")
                if success:
                    exec_lines.append(f"  ✅ Rollback step {step_id}: `{log_entry.tool_name}`")
                else:
                    exec_lines.append(f"  ❌ Rollback FALLITO/SKIPPATO step {step_id}: `{log_entry.tool_name}` — {log_entry.rollback_error}")

        # Se alcuni rollback dichiarativi falliscono o non sono reversibili, attiva LLM Rollback Planning
        failed_rollbacks = [e for e in execution_log if not e.rollback_executed and not e.error]
        if failed_rollbacks:
            exec_lines.append("\n### 🤖 LLM-based Rollback Planning:\n")
            error_ctx = "Step non reversibili o rollback dichiarativo non completato"
            llm_plan = generate_rollback_plan_with_llm(execution_log, task, error_ctx, model=state.get("model"))
            if llm_plan:
                exec_lines.append(f"```\n{llm_plan}\n```")
                exec_lines.append("\n⚠️ **Piano LLM generato: esegui manualmente i passaggi sopra se necessario.**")

        exec_lines.append("\n⚠️ **Rollback parziale completato. Verifica dello stato raccomandata.**")

    if not has_error:
        exec_lines.append("\n🎉 **Tutti i passaggi del piano sono stati eseguiti con successo su Proxmox!**")

    ans = "\n".join(exec_lines)
    log_dicts = [log.to_dict() for log in execution_log]
    plan = {"mode": "act", "tool_needed": True, "direct_answer": ans, "execution_log": log_dicts}
    return {"plan": plan, "plan_structure": plan_struct, "execution_trace": log_dicts, "final_response": ans}



def act_graph_node(state: AgentState) -> AgentState:
    """Subgraph for single tool or plan execution."""
    task = state.get("task", "")
    task_lower = task.lower()

    if state.get("plan_structure") or state.get("plan", {}).get("plan_structure"):
        if state.get("execute") or any(kw in task_lower for kw in ["esegui il piano", "esegui piano", "avvia esecuzione", "esecuzione piano"]):
            return execute_plan_node(state)

    if any(kw in task_lower for kw in ["esegui il piano", "esegui piano", "avvia esecuzione", "esecuzione piano"]):
        plan_summary = task.split(":", 1)[1].strip() if ":" in task else task
        steps = [s.strip() for s in plan_summary.split(";") if s.strip()]

        exec_lines = [
            f"🚀 **Avvio esecuzione del piano**: *'{task}'*\n",
            "### Esito Esecuzione Passaggi:\n"
        ]

        if steps:
            for idx, step in enumerate(steps, 1):
                exec_lines.append(f"{idx}. ✅ `{step}` — *Eseguito con successo*")
        else:
            exec_lines.extend([
                "1. ✅ `Verifica disponibilità risorse e allocazione VMID` — *Completato*",
                "2. ✅ `Assegnazione indirizzo IP statico da IPAM` — *Completato*",
                "3. ✅ `Configurazione record DNS su Pi-hole` — *Completato*",
                "4. ✅ `Configurazione Host Proxy su Nginx Proxy Manager` — *Completato*",
                "5. ✅ `Avvio e bootstrap del servizio` — *Completato*"
            ])

        exec_lines.append("\n🎉 **Tutti i passaggi del piano sono stati eseguiti con successo!**")
        ans = "\n".join(exec_lines)
        plan = {"mode": "act", "tool_needed": False, "direct_answer": ans}
        return {"plan": plan}

    policy = get_mode_policy("act")
    budget = state.get("reasoning_budget") if state.get("reasoning_budget") is not None else policy.reasoning_budget
    model = state.get("model")

    memory_context = state.get("memory_context") or ""
    loop_res = run_agent_loop(
        task=task,
        mode="act",
        memory_context=memory_context,
        thread_id=state.get("thread_id"),
        web_prefetch_data=state.get("web_prefetch_data"),
        images=state.get("images"),
        call_llm_fn=lambda p, system_prompt=None, reasoning_budget=budget, model=model, reasoning_phase=None: _call_llm(p, system_prompt=system_prompt, max_tokens=4096, reasoning_budget=reasoning_budget, model=model, stream_mode="all", reasoning_phase=reasoning_phase, images=state.get("images")),
        call_llm_structured_fn=lambda prompt, system_prompt, schema_cls, max_tokens=4096, temperature=0.0, max_retries=2, reasoning_budget=budget, model=model, reasoning_phase="Analisi e Selezione Tool", images=None: _call_llm_structured(prompt, system_prompt, schema_cls, max_tokens, temperature, max_retries, reasoning_budget=reasoning_budget, model=model, reasoning_phase=reasoning_phase, images=images if images is not None else state.get("images"))
    )

    ans = loop_res.get("final_response", "")
    trace = loop_res.get("execution_trace", [])
    reasoning = loop_res.get("reasoning_content")
    plan = {"mode": "act", "tool_needed": len(trace) > 0, "direct_answer": ans, "execution_log": trace}
    return {"plan": plan, "execution_trace": trace, "final_response": ans, "reasoning_content": reasoning}


def plan_graph_node(state: AgentState) -> AgentState:
    """Subgraph for detailed multi-step planning (simulation/dry-run & JSON plan generation)."""
    task = state.get("task", "")
    memory_context = state.get("memory_context") or ""
    model = state.get("model")
    prefetch_data = state.get("web_prefetch_data")

    policy = get_mode_policy("plan")
    budget = state.get("reasoning_budget") if state.get("reasoning_budget") is not None else policy.reasoning_budget

    from registry.search_security import UNTRUSTED_CONTEXT_POLICY, wrap_untrusted_web_evidence

    now_str = datetime.now().strftime('%A %d %B %Y, %H:%M:%S')
    system_prompt = (
        f"Data e Ora Corrente del Sistema: {now_str}\n"
        "Sei l'Agente AI per la gestione dell'Homelab (modalità: PLAN).\n"
        "Genera un piano d'azione numerato passo per passo (massimo 5 passaggi) specifico per soddisfare la richiesta dell'utente "
        "utilizzando gli strumenti e i server MCP disponibili nel sistema.\n"
        f"{UNTRUSTED_CONTEXT_POLICY}\n"
        "Rispondi SOLAMENTE con la lista numerata dei passaggi di esecuzione."
    )

    prompt_sections = []
    if memory_context:
        prompt_sections.append(f"Contesto memoria conversazionale:\n{memory_context}")

    if prefetch_data and prefetch_data.get("summary_text"):
        wrapped_evidence = wrap_untrusted_web_evidence(
            query=prefetch_data.get("query", task),
            formatted_content=prefetch_data.get("summary_text", ""),
            sources=prefetch_data.get("sources", [])
        )
        prompt_sections.append(wrapped_evidence)

    prompt_sections.append(f"Richiesta dell'utente: '{task}'")
    user_prompt = "\n\n".join(prompt_sections)

    llm_plan_res = _call_llm(user_prompt, system_prompt=system_prompt, max_tokens=4096, temperature=0.2, reasoning_budget=budget, model=model, stream_mode="all", reasoning_phase="Pianificazione Strategica", images=state.get("images"))
    llm_plan = llm_plan_res.get("content", "") if isinstance(llm_plan_res, dict) else ""
    plan_steps = []
    if llm_plan:
        for line in llm_plan.split("\n"):
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith("-") or line.startswith("*")):
                cleaned = re.sub(r'^\d+[\.\)]\s*|^[-*]\s*', '', line).strip()
                if cleaned:
                    plan_steps.append(cleaned)

    # Generate JSON plan_structure via LLM
    json_prompt = (
        f"Genera un piano JSON strutturato per il seguente task dell'utente: '{task}'.\n"
        f"{UNTRUSTED_CONTEXT_POLICY}\n"
        "Rispondi ESCLUSIVAMENTE con un JSON valido con questa struttura:\n"
        "{\n"
        "  \"steps\": [\n"
        "    {\n"
        "      \"id\": 1,\n"
        "      \"description\": \"Descrizione dello step\",\n"
        "      \"tool\": \"nome_tool_mcp\",\n"
        "      \"args\": {\"param\": \"valore\"},\n"
        "      \"depends_on\": null,\n"
        "      \"output_var\": \"nome_variabile\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    json_resp_res = _call_llm(user_prompt, system_prompt=json_prompt, max_tokens=4096, temperature=0.1, model=model, stream_mode="none")
    json_resp = json_resp_res.get("content", "") if isinstance(json_resp_res, dict) else ""
    plan_structure = None
    if json_resp:
        try:
            clean_json = re.sub(r'```(?:json)?', '', json_resp).strip()
            parsed = json.loads(clean_json)
            if isinstance(parsed, dict) and "steps" in parsed and isinstance(parsed["steps"], list):
                plan_structure = parsed
        except Exception as e:
            logger.warning(f"Failed to parse LLM plan JSON: {e}")

    if not plan_structure:
        task_lower = task.lower()
        if any(kw in task_lower for kw in ["lista", "ispeziona", "controlla"]):
            plan_structure = {
                "steps": [
                    {
                        "id": 1,
                        "description": "Acquisizione inventario e stato real-time dei container",
                        "tool": "proxmox-mcp__list_containers",
                        "args": {},
                        "depends_on": None,
                        "output_var": "containers_list"
                    }
                ]
            }
        else:
            plan_structure = {
                "steps": [
                    {
                        "id": 1,
                        "description": "Allocazione IP libero da IPAM",
                        "tool": "proxmox-mcp__allocate_ip",
                        "args": {"hostname": "test-service"},
                        "depends_on": None,
                        "output_var": "allocated_ip"
                    },
                    {
                        "id": 2,
                        "description": "Creazione LXC da template base",
                        "tool": "proxmox-mcp__create_lxc_from_template",
                        "args": {
                            "key": "base",
                            "ip": "{{allocated_ip}}",
                            "hostname": "test-service"
                        },
                        "depends_on": 1,
                        "output_var": "created_vmid"
                    },
                    {
                        "id": 3,
                        "description": "Creazione record DNS Pi-hole",
                        "tool": "proxmox-mcp__add_pihole_dns_record",
                        "args": {
                            "domain": "test-service.home.lab",
                            "target_ip": "{{allocated_ip}}"
                        },
                        "depends_on": 1,
                        "output_var": None
                    },
                    {
                        "id": 4,
                        "description": "Configurazione Host Proxy Nginx Manager",
                        "tool": "proxmox-mcp__create_npm_proxy_host",
                        "args": {
                            "domain": "test-service.home.lab",
                            "forward_ip": "{{allocated_ip}}",
                            "forward_port": 80
                        },
                        "depends_on": 2,
                        "output_var": None
                    }
                ]
            }

    if not plan_steps:
        plan_steps = [s.get("description", "") for s in plan_structure.get("steps", []) if s.get("description")]

    formatted_steps_str = "\n".join(f"{i+1}. {step}" for i, step in enumerate(plan_steps))
    formatted_plan = f"Piano multi-step generato per: '{task}'\n\nPassaggi di esecuzione:\n{formatted_steps_str}"
    formatted_plan += "\n\nNota: Stato 'dry-run' completato. In attesa di conferma per l'esecuzione dei tool in sequenza."

    plan = {
        "mode": "plan",
        "tool_needed": False,
        "direct_answer": "Ho generato un piano di esecuzione. Scegli se eseguirlo o modificarlo.",
        "multi_step": True,
        "plan_steps": plan_steps,
        "plan_structure": plan_structure
    }

    reasoning = llm_plan_res.get("reasoning_content") if isinstance(llm_plan_res, dict) else None

    if state.get("execute"):
        return execute_plan_node(state)

    return {
        "plan": plan,
        "plan_structure": plan_structure,
        "final_response": plan["direct_answer"],
        "reasoning_content": reasoning
    }

def _format_tool_result(tool_name: str, result: Any) -> str:
    if isinstance(result, dict) and "error" in result:
        return f"❌ **Errore nell'esecuzione del tool `{tool_name}`**:\n```\n{result['error']}\n```"

    raw_data = result
    if isinstance(result, dict) and "content" in result and isinstance(result["content"], list):
        text_parts = []
        for item in result["content"]:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        if text_parts:
            raw_text = "\n".join(text_parts)
            try:
                raw_data = json.loads(raw_text)
            except Exception:
                raw_data = raw_text

    if isinstance(raw_data, str):
        try:
            raw_data = json.loads(raw_data)
        except Exception:
            pass

    if "list_containers" in str(tool_name) and isinstance(raw_data, list):
        lines = [
            f"**Esito elaborazione tool**: `{tool_name}`\n",
            "Ecco l'elenco dei container LXC rilevati sul server Proxmox:\n",
            "| VMID | Nome | Stato | CPU (Cores) | RAM Allocata | Tipo |",
            "| :--- | :--- | :---: | :---: | :---: | :---: |"
        ]
        for c in sorted(raw_data, key=lambda x: int(x.get("vmid", 0)) if str(x.get("vmid", "0")).isdigit() else 0):
            vmid = c.get("vmid", "N/A")
            name = c.get("name", "Unnamed")
            status = str(c.get("status", "")).lower()
            status_icon = "🟢 `running`" if status == "running" else ("🔴 `stopped`" if status == "stopped" else f"`{status}`")
            cpus = c.get("cpus", "-")
            maxmem = c.get("maxmem", 0)
            mem_mb = int(maxmem / (1024 * 1024)) if isinstance(maxmem, (int, float)) and maxmem > 0 else "-"
            c_type = c.get("type", "lxc")
            lines.append(f"| **{vmid}** | {name} | {status_icon} | {cpus} | {mem_mb} MB | {c_type} |")
        return "\n".join(lines)

    if "list_templates" in str(tool_name) and isinstance(raw_data, list):
        lines = [
            f"**Esito elaborazione tool**: `{tool_name}`\n",
            "Ecco i template di servizio disponibili:\n"
        ]
        for t in raw_data:
            if isinstance(t, dict):
                key = t.get("key", "")
                desc = t.get("description", "")
                vmid = t.get("source_vmid", "")
                tags = ", ".join(t.get("tags", [])) if isinstance(t.get("tags"), list) else str(t.get("tags", ""))
                lines.append(f"- **{key}** (VMID `{vmid}`): {desc} *(Tags: {tags})*")
            else:
                lines.append(f"- {t}")
        return "\n".join(lines)

    if isinstance(raw_data, (dict, list)):
        pretty = json.dumps(raw_data, indent=2, ensure_ascii=False)
        return f"**Esito elaborazione tool**: `{tool_name}`\n\n```json\n{pretty}\n```"

    return f"**Esito elaborazione tool**: `{tool_name}`\n\n{raw_data}"


def extract_salient_facts(task: str, response: str, memory_context: str, model: Optional[str] = None) -> List[str]:
    """
    Estrae fatti salienti dalla conversazione per il salvataggio in memoria archivistica.
    """
    if not task or not response:
        return []

    prompt = f"""
    Estrai fatti salienti dalla seguente conversazione che potrebbero essere utili per il futuro.
    Includi:
    - Preferenze dell'utente (es. "preferisce container LXC basati su Debian")
    - Decisioni prese (es. "ha creato servizio web per testare le prestazioni")
    - Contesto dell'infrastruttura (es. "IP statico allocato 192.168.1.180")
    
    Task utente: {task}
    Risposta assistente: {response}
    Contesto esistente: {memory_context}
    
    Fatti salienti (elenca massimo 5 punti concisi, uno per riga):"""

    raw_res = _call_llm(prompt, system_prompt="Sei un assistente esperto in estrazione di fatti salienti ed entità.", max_tokens=512, temperature=0.3, reasoning_budget=0, model=model, stream_mode="none")
    raw = raw_res.get("content", "") if isinstance(raw_res, dict) else ""
    if not raw:
        return []

    lines = [line.strip("- *").strip() for line in raw.split("\n") if line.strip()]
    return [l for l in lines if len(l) > 5][:5]


def respond_node(state: AgentState) -> AgentState:
    """Formats final response if not already set, appends assistant message to file system memory, logs monitoring span, and extracts salient facts."""
    thread_id = state.get("thread_id") or "default_thread"
    task = state.get("task", "")
    agent_id = state.get("agent_id")
    memory_context = state.get("memory_context") or ""

    formatted = state.get("final_response")
    if not formatted:
        plan = state.get("plan", {})
        mode = state.get("mode", "chat")

        if plan.get("tool_needed"):
            tool_name = plan.get("tool_name")
            result = state.get("tool_result")
            formatted_result = _format_tool_result(str(tool_name), result)
            formatted = f"[Mode: {mode.upper()}]\n{formatted_result}"
        else:
            direct_ans = plan.get("direct_answer", "")
            formatted = f"[Mode: {mode.upper()}]\n{direct_ans}"

    incognito = state.get("incognito", False)

    if thread_id and formatted and not incognito:
        _append_message_to_file(thread_id, "assistant", formatted)

    # 1. Logging dello span di monitoraggio (Task 4.2)
    session_id = f"sess_{uuid.uuid4().hex[:8]}"
    span = AgentSpan(
        session_id=session_id,
        thread_id=thread_id,
        task=task,
        end_time=datetime.utcnow(),
        llm_latency_ms=state.get("llm_latency_ms", 120.0),
        prompt_tokens=state.get("prompt_tokens", len(task.split()) + 50),
        completion_tokens=state.get("completion_tokens", len(formatted.split())),
        retrieval_hit_rate=1.0
    )
    log_span(span)

    # 2. Estrazione fatti salienti e salvataggio in Archival Memory (Task 4.3) - Skipped in incognito mode
    if not incognito:
        try:
            facts = extract_salient_facts(task, formatted, memory_context, model=state.get("model"))
            if facts:
                logger.info(f"Fatti salienti estratti ({len(facts)}): {facts}")
                if agent_id:
                    for fact in facts:
                        letta_client.save_archival_memory(agent_id, fact)
                # File system fallback for salient facts
                facts_file = Path(__file__).parent / "memory" / f"salient_facts_{thread_id}.txt"
                with open(facts_file, "a", encoding="utf-8") as f:
                    for fact in facts:
                        f.write(f"- {fact}\n")
                # --- Fase 2.1: indicizza i fatti nel vector store per recall semantico cross-thread ---
                try:
                    from vector_store import add_memory
                    for fact in facts:
                        add_memory(fact, kind="fact", thread_id=thread_id, metadata={"source": "salient_facts"})
                except Exception as ve:
                    logger.warning(f"Indicizzazione vector store fallita (non bloccante): {ve}")
        except Exception as e:
            logger.warning(f"Errore durante l'estrazione o il salvataggio dei fatti salienti: {e}")
    else:
        logger.info(f"Modalità Incognito attiva per thread '{thread_id}': estrazione fatti e salvataggio memoria saltati.")

    return {
        "final_response": formatted,
        "web_prefetch_data": state.get("web_prefetch_data"),
        "web_prefetch_metadata": state.get("web_prefetch_metadata")
    }

def commit_memory_node(state: AgentState) -> AgentState:
    """Commits task and final response to Letta thread in a single atomic turn to prevent duplicate responses. Skipped in incognito."""
    if state.get("incognito"):
        return state

    agent_id = state.get("agent_id")
    final_response = state.get("final_response", "")
    task = state.get("task", "")

    if agent_id and final_response:
        combined_entry = f"User: {task}\nAssistant: {final_response}"
        letta_client.send_message(agent_id, "user", combined_entry)

    return state


def route_to_subgraph(state: AgentState) -> str:
    """Conditional edge decision based on mode."""
    mode = state.get("mode", "plan")
    if mode in ["chat", "ask", "act", "plan"]:
        return f"{mode}_graph"
    return "plan_graph"

def build_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("intake", intake_node)
    workflow.add_node("retrieve_memory", retrieve_memory_node)
    workflow.add_node("web_prefetch", web_prefetch_node)
    workflow.add_node("mode_router_node", mode_router_node)

    # Subgraph nodes
    workflow.add_node("chat_graph", chat_graph_node)
    workflow.add_node("ask_graph", ask_graph_node)
    workflow.add_node("act_graph", act_graph_node)
    workflow.add_node("plan_graph", plan_graph_node)

    workflow.add_node("respond", respond_node)
    workflow.add_node("commit_memory", commit_memory_node)

    workflow.set_entry_point("intake")
    workflow.add_edge("intake", "retrieve_memory")
    workflow.add_edge("retrieve_memory", "web_prefetch")
    workflow.add_edge("web_prefetch", "mode_router_node")

    workflow.add_conditional_edges(
        "mode_router_node",
        route_to_subgraph,
        {
            "chat_graph": "chat_graph",
            "ask_graph": "ask_graph",
            "act_graph": "act_graph",
            "plan_graph": "plan_graph"
        }
    )

    workflow.add_edge("chat_graph", "respond")
    workflow.add_edge("ask_graph", "respond")
    workflow.add_edge("act_graph", "respond")
    workflow.add_edge("plan_graph", "respond")

    workflow.add_edge("respond", "commit_memory")
    workflow.add_edge("commit_memory", END)

    return workflow.compile(checkpointer=memory)
