"""Consolidamento della memoria a lungo termine: dai messaggi delle conversazioni ai fatti, fuori dai turni.

Al posto dell'estrazione a fine turno, un processo periodico (di notte, o su richiesta dalla vista Memoria) legge i
messaggi non ancora consolidati di ogni thread e, a blocchi in ordine cronologico, chiede al modello come cambiano la
memoria rispetto ai fatti già salvati che riguardano gli stessi argomenti (modello ADD/UPDATE/DELETE di Mem0):
- `add`: un fatto nuovo;
- `update`: un fatto esistente cambia (un servizio spostato, un IP nuovo): nasce il fatto nuovo e il vecchio diventa
  superato, con la data del messaggio e il riferimento al sostituto (validità temporale, modello Graphiti);
- `invalidate`: un fatto esistente non vale più e niente lo sostituisce.
Il modello può superare solo i fatti che gli sono stati mostrati. I fatti nuovi prendono la data del messaggio da cui
vengono, così le domande temporali ("cosa ho installato ad agosto") hanno la data giusta.

La deduplicazione confronta i fatti salvati dall'ultima esecuzione con tutti gli altri: i gruppi molto simili passano al
modello, che indica quali ripetono o contraddicono un altro fatto.
"""
import json
import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.agent import llm_calls
from app.agent.fact_extraction import ENTITY_GUIDE, ExtractedEntity, entity_refs
from app.core.config import settings
from app.llm.providers import LLMUnavailableError
from app.memory import facts, thread_store, vector_store

logger = logging.getLogger("consolidation")

CHUNK_MESSAGES = 16
CHUNK_TOKENS = 4000  # stimati, ~4 caratteri per token
MAX_USER_CHARS = 1500
MAX_ASSISTANT_CHARS = 800  # le risposte lunghe (tabelle, spiegazioni) contano per quello che confermano, non per intero
RELATED_PER_MESSAGE = 4
RELATED_MAX = 20
RELATED_SCORE = 0.4
MAX_OPERATIONS = 10
DEDUP_SCORE = 0.85
DEDUP_GROUP_MAX = 6
DEDUP_GROUPS_PER_RUN = 10
SCHEDULER_CHECK_SECONDS = 300


class FactOperation(BaseModel):
    op: Literal["add", "update", "invalidate"]
    message: int = Field(description="Number of the message the operation comes from")
    fact: str = Field(default="", description="add/update: the new self-contained fact, in the language of the conversation")
    entities: List[ExtractedEntity] = Field(default_factory=list)
    replaces: Optional[int] = Field(default=None, description="update/invalidate: id of the existing fact")


class Consolidation(BaseModel):
    operations: List[FactOperation] = Field(max_length=MAX_OPERATIONS)


class Superseded(BaseModel):
    id: int
    by: int = Field(description="The fact that stays")


class Deduplication(BaseModel):
    superseded: List[Superseded]


# --- Stato del processo ---


def init_consolidation_db() -> None:
    conn = thread_store._get_conn()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS memory_jobs (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.commit()
    finally:
        conn.close()


def _job(key: str) -> Optional[str]:
    conn = thread_store._get_conn()
    try:
        row = conn.execute("SELECT value FROM memory_jobs WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _set_job(key: str, value: str) -> None:
    conn = thread_store._get_conn()
    try:
        conn.execute("INSERT OR REPLACE INTO memory_jobs (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    finally:
        conn.close()


# --- Consolidamento dei messaggi ---


def _numbered(messages: List[Dict[str, Any]]) -> str:
    lines = []
    for i, m in enumerate(messages, start=1):
        limit = MAX_USER_CHARS if m["role"] == "user" else MAX_ASSISTANT_CHARS
        text = m["content"] if len(m["content"]) <= limit else m["content"][:limit] + "…"
        lines.append(f"[{i}] {str(m.get('created_at') or '')[:10]} {'User' if m['role'] == 'user' else 'Assistant'}: {text}")
    return "\n".join(lines)


def propose_operations(messages: List[Dict[str, Any]], related: List[Dict[str, Any]], model: Optional[str] = None) -> Optional[List[FactOperation]]:
    """Come i messaggi cambiano la memoria rispetto ai fatti `related`; None se il modello non dà una risposta valida."""
    existing = "\n".join(f"#{f['id']} [{(f['created_at'] or '')[:10]}] {f['content']}" for f in related) or "(none)"
    prompt = f"""Conversation messages (numbered, with date):
{_numbered(messages)}

Facts already in memory that may be related (id, date, text):
{existing}

Update the long-term memory with what these messages establish about the user and their world:
- "add": a new durable fact: user preferences, decisions, the state of the user's infrastructure and projects,
  people and their roles, commitments and dates.
- "update": the messages change an existing fact (a service moved, an IP changed, a tool replaced): write the new
  fact, self-contained, and set "replaces" to the id of the old fact.
- "invalidate": an existing fact is no longer true and nothing replaces it (a service removed): set "replaces".
Every operation has "message": the number of the message it comes from.
Each fact must be understandable on its own, without the conversation.
Do NOT store: the conversation itself ("the user asked..."), general knowledge the assistant explained, transient
errors, how-to instructions or procedures (they belong to a separate procedural memory), or facts already in memory
unchanged. Assistant messages count only when they report something about the user's world (e.g. a tool result),
not for suggestions. Return an empty list when nothing changes. At most {MAX_OPERATIONS} operations.
{ENTITY_GUIDE}"""
    result = llm_calls.call_llm_structured(
        prompt,
        "You maintain the long-term memory of a homelab assistant: you add, update and invalidate durable facts.",
        Consolidation,
        max_tokens=2048,
        max_retries=1,
        reasoning_budget=0,
        model=model,
        reasoning_phase=None,
    )
    return result.operations if result else None


def _related_facts(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fatti validi simili ai messaggi dell'utente del blocco, senza ripetizioni."""
    found: Dict[int, Dict[str, Any]] = {}
    for m in messages:
        if m["role"] != "user":
            continue
        for fact in facts.search_facts(m["content"][:500], k=RELATED_PER_MESSAGE, min_score=RELATED_SCORE):
            found.setdefault(fact["id"], fact)
    return list(found.values())[:RELATED_MAX]


def _apply(operations: List[FactOperation], messages: List[Dict[str, Any]], related: List[Dict[str, Any]], thread_id: str) -> Dict[str, int]:
    counts = {"added": 0, "updated": 0, "invalidated": 0}
    known = {f["id"] for f in related}
    for op in operations:
        date = messages[min(max(op.message, 1), len(messages)) - 1].get("created_at")
        if op.op in ("update", "invalidate") and op.replaces not in known:
            logger.info(f"Operazione '{op.op}' scartata: il fatto #{op.replaces} non era tra quelli mostrati")
            if op.op == "invalidate":
                continue
            op.op, op.replaces = "add", None
        if op.op == "invalidate":
            counts["invalidated"] += facts.supersede_fact(op.replaces, at=date)
            continue
        if len(op.fact.strip()) <= 5:
            continue
        fact_id, created = facts.add_fact(op.fact, thread_id=thread_id, entities=entity_refs(op.entities), source="conversation",
                                          entities_checked=True, created_at=date)
        if fact_id is None:
            continue
        if op.op == "update" and fact_id != op.replaces:
            counts["updated"] += facts.supersede_fact(op.replaces, by=fact_id, at=date)
        else:
            counts["added"] += created
    return counts


def _chunks(messages: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    chunks: List[List[Dict[str, Any]]] = [[]]
    tokens = 0
    for m in messages:
        size = min(len(m["content"]), MAX_USER_CHARS) // 4
        if chunks[-1] and (len(chunks[-1]) >= CHUNK_MESSAGES or tokens + size > CHUNK_TOKENS):
            chunks.append([])
            tokens = 0
        chunks[-1].append(m)
        tokens += size
    return [c for c in chunks if c]


def pending() -> Dict[str, int]:
    """Messaggi e thread non ancora consolidati."""
    messages = threads = 0
    for thread_id in thread_store.threads_by_first_message():
        count = len(thread_store.get_history(thread_id)) - thread_store.get_consolidated(thread_id)
        if count > 0:
            messages += count
            threads += 1
    return {"messages": messages, "threads": threads}


def consolidate_messages(model: Optional[str] = None) -> Dict[str, int]:
    """Consolida i messaggi nuovi di tutti i thread, a blocchi per thread in ordine cronologico globale: un fatto
    detto dopo, anche in un altro thread, supera quello detto prima."""
    blocks = []
    for thread_id in thread_store.threads_by_first_message():
        history = thread_store.get_history(thread_id)
        covered = min(thread_store.get_consolidated(thread_id), len(history))
        position = covered
        for chunk in _chunks(history[covered:]):
            position += len(chunk)
            blocks.append((str(chunk[0].get("created_at") or ""), thread_id, chunk, position))
    blocks.sort(key=lambda b: b[0])

    totals = {"messages": 0, "added": 0, "updated": 0, "invalidated": 0}
    stalled = set()
    for _, thread_id, chunk, position in blocks:
        if thread_id in stalled:  # un blocco fallito: i successivi dello stesso thread aspettano il prossimo giro
            continue
        related = _related_facts(chunk)
        operations = propose_operations(chunk, related, model=model)
        if operations is None:
            logger.warning(f"Consolidamento del thread '{thread_id}' fermo: risposta del modello non valida")
            stalled.add(thread_id)
            continue
        for key, value in _apply(operations, chunk, related, thread_id).items():
            totals[key] += value
        totals["messages"] += len(chunk)
        thread_store.save_consolidated(thread_id, position)
    return totals


# --- Deduplicazione ---


def deduplicate(model: Optional[str] = None) -> int:
    """Confronta i fatti salvati dall'ultima esecuzione con tutti gli altri; restituisce quanti ne supera."""
    last_id = int(_job("dedup_last_id") or 0)
    new_facts, _ = facts.list_facts(limit=10_000)
    new_facts = [f for f in new_facts if f["id"] > last_id]
    if not new_facts:
        return 0
    groups: List[Dict[int, Dict[str, Any]]] = []
    grouped: set = set()
    for fact in sorted(new_facts, key=lambda f: f["id"]):
        if fact["id"] in grouped:
            continue
        similar = [h for h in vector_store.search_memory(fact["content"], k=DEDUP_GROUP_MAX, kind="fact")
                   if h["id"] != fact["id"] and h["score"] >= DEDUP_SCORE and h["id"] not in grouped]
        if similar:
            ids = [fact["id"], *(h["id"] for h in similar)][:DEDUP_GROUP_MAX]
            groups.append({i: facts.get_fact(i) for i in ids})
            grouped.update(ids)

    superseded = 0
    for group in groups[:DEDUP_GROUPS_PER_RUN]:
        listing = "\n".join(f"#{i} [{(f['created_at'] or '')[:10]}] {f['content']}" for i, f in group.items() if f)
        result = llm_calls.call_llm_structured(
            f"""These long-term memory facts are similar:
{listing}

For each fact that repeats the same information as another, or is contradicted by a more recent one, return it
with "by" = the fact that should stay (prefer the more recent and more complete). Facts that say different things
(e.g. two different services on the same container) all stay: return an empty list for them.""",
            "You deduplicate the long-term memory of a homelab assistant.",
            Deduplication,
            max_tokens=512,
            max_retries=1,
            reasoning_budget=0,
            model=model,
            reasoning_phase=None,
        )
        for item in result.superseded if result else []:
            if item.id in group and item.by in group and item.id != item.by:
                superseded += facts.supersede_fact(item.id, by=item.by)
    if len(groups) <= DEDUP_GROUPS_PER_RUN:  # i gruppi rimasti fuori si riprendono al prossimo giro
        _set_job("dedup_last_id", str(max(f["id"] for f in new_facts)))
    return superseded


# --- Esecuzione ---


_lock = threading.Lock()
_running_since: Optional[str] = None


def status() -> Dict[str, Any]:
    last = _job("last_result")
    return {
        "running": _running_since is not None,
        "running_since": _running_since,
        "last_run": _job("last_run"),
        "last_result": json.loads(last) if last else None,
        "pending": pending(),
        "schedule_hour": settings.memory_consolidation_hour,
    }


def run(model: Optional[str] = None, trigger: str = "manual") -> Optional[Dict[str, Any]]:
    """Consolidamento e deduplicazione; None se un'esecuzione è già in corso."""
    global _running_since
    if not _lock.acquire(blocking=False):
        return None
    started = time.monotonic()
    _running_since = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        result: Dict[str, Any] = {"trigger": trigger}
        try:
            result.update(consolidate_messages(model))
            result["deduplicated"] = deduplicate(model)
        except LLMUnavailableError as e:
            result["error"] = f"Modello non disponibile: {e}"
        result["seconds"] = round(time.monotonic() - started, 1)
        _set_job("last_run", datetime.now().astimezone().isoformat(timespec="seconds"))
        _set_job("last_result", json.dumps(result))
        logger.info(f"Consolidamento della memoria ({trigger}): {result}")
        return result
    finally:
        _running_since = None
        _lock.release()


def run_in_background(model: Optional[str] = None) -> bool:
    if _lock.locked():
        return False
    threading.Thread(target=run, kwargs={"model": model}, name="memory-consolidation", daemon=True).start()
    return True


class ConsolidationScheduler:
    """Thread daemon: una volta al giorno, nell'ora `MEMORY_CONSOLIDATION_HOUR` (fuso del container)."""

    def __init__(self, hour: int):
        self.hour = hour
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="consolidation-scheduler", daemon=True).start()
        logger.info(f"Consolidamento della memoria ogni giorno alle {self.hour}:00")

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(SCHEDULER_CHECK_SECONDS):
            now = datetime.now()
            if now.hour != self.hour or (_job("last_run") or "")[:10] == now.date().isoformat():
                continue
            try:
                run(trigger="schedule")
            except Exception as e:
                logger.warning(f"Consolidamento programmato non riuscito: {e}")


_scheduler: Optional[ConsolidationScheduler] = None


def start_scheduler() -> None:
    global _scheduler
    if settings.memory_consolidation_hour >= 0 and _scheduler is None:
        _scheduler = ConsolidationScheduler(settings.memory_consolidation_hour)
        _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.stop()
        _scheduler = None
