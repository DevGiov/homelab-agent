"""Episodi di esecuzione: cosa è stato chiesto, quali tool sono stati usati, con che esito.

Un episodio si ricava in modo deterministico (senza modello) dalla traccia di un turno act o plan che ha eseguito tool,
e si salva come record `kind='episode'` della memoria vettoriale. Nei turni act e plan successivi i più simili alla
richiesta entrano nella memoria del turno: l'agente vede come è andata le altre volte e quali errori evitare.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from app.memory import hybrid_search, vector_store

logger = logging.getLogger("episodes")

MAX_TASK_CHARS = 200
MAX_ARGS_CHARS = 80
MAX_ERROR_CHARS = 120
RELEVANT_SCORE = 0.5  # somiglianza minima con la richiesta
KEYWORD_RELEVANT_SCORE = 0.35  # per gli episodi trovati per parole in comune


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _step(entry: Dict[str, Any]) -> str:
    args = entry.get("args") or {}
    call = f"{entry['tool_name']}({_clip(json.dumps(args, ensure_ascii=False), MAX_ARGS_CHARS)})" if args else entry["tool_name"]
    if entry.get("error"):
        return f"{call} ✗ {_clip(entry['error'], MAX_ERROR_CHARS)}"
    if entry.get("rollback_executed"):
        return f"{call} ✓ (annullato dal rollback)"
    return f"{call} ✓"


def describe(task: str, trace: List[Dict[str, Any]]) -> Optional[str]:
    """Testo dell'episodio; None se il turno non ha eseguito tool (o li ha solo ripetuti)."""
    steps = [e for e in trace if e.get("tool_name") and not e.get("duplicate_blocked") and not e.get("approval_required")]
    if not steps:
        return None
    errors = sum(1 for e in steps if e.get("error"))
    if not errors:
        outcome = "riuscito"
    elif steps[-1].get("error"):
        outcome = "fallito"
    else:
        outcome = "riuscito dopo errori"
    if any(e.get("rollback_executed") for e in steps):
        outcome += ", con rollback"
    return f"Richiesta: «{_clip(task, MAX_TASK_CHARS)}» → " + "; ".join(_step(e) for e in steps) + f" → esito: {outcome}"


def remember_episode(task: str, mode: str, trace: List[Dict[str, Any]], thread_id: Optional[str]) -> Optional[int]:
    """Salva l'episodio del turno; turni in attesa di approvazione esclusi (si concludono in un turno successivo)."""
    if any(e.get("approval_required") for e in trace):
        return None
    text = describe(task, trace)
    if not text:
        return None
    tools = sorted({e["tool_name"] for e in trace if e.get("tool_name")})
    return vector_store.add_memory(text, kind="episode", thread_id=thread_id, metadata={"mode": mode, "tools": tools})


def similar_episodes(task: str, k: int) -> List[Dict[str, Any]]:
    """Gli episodi più simili alla richiesta, con la data."""
    hits = hybrid_search.hybrid_search(
        task, kind="episode", k=k, min_score=RELEVANT_SCORE, keyword_min_score=KEYWORD_RELEVANT_SCORE
    )
    if not hits:
        return []
    ids = [i for i, _ in hits]
    conn = vector_store._get_conn()
    try:
        rows = dict(
            (r[0], (r[1], r[2]))
            for r in conn.execute(
                f"SELECT id, content, created_at FROM vec_memory WHERE id IN ({','.join('?' * len(ids))})", ids
            ).fetchall()
        )
    finally:
        conn.close()
    return [
        {"id": i, "content": rows[i][0], "date": str(rows[i][1] or "")[:10], "score": round(score, 3)}
        for i, score in hits if i in rows
    ]
