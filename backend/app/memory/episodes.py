"""Episodi di esecuzione: cosa è stato chiesto, quali tool sono stati usati, con che esito.

Un episodio si ricava in modo deterministico (senza modello) dalla traccia di un turno act o plan che ha eseguito tool,
e si salva come record `kind='episode'` della memoria vettoriale. Nei turni act e plan successivi i più simili alla
richiesta entrano nella memoria del turno: l'agente vede come è andata le altre volte e quali errori evitare.
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

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


def executed_steps(trace: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [e for e in trace if e.get("tool_name") and not e.get("duplicate_blocked") and not e.get("approval_required")]


def outcome_of(steps: List[Dict[str, Any]]) -> str:
    if not any(e.get("error") for e in steps):
        outcome = "riuscito"
    elif steps[-1].get("error"):
        outcome = "fallito"
    else:
        outcome = "riuscito dopo errori"
    if any(e.get("rollback_executed") for e in steps):
        outcome += ", con rollback"
    return outcome


def describe(task: str, trace: List[Dict[str, Any]]) -> Optional[str]:
    """Testo dell'episodio; None se il turno non ha eseguito tool (o li ha solo ripetuti)."""
    steps = executed_steps(trace)
    if not steps:
        return None
    return f"Richiesta: «{_clip(task, MAX_TASK_CHARS)}» → " + "; ".join(_step(e) for e in steps) + f" → esito: {outcome_of(steps)}"


def remember_episode(task: str, mode: str, trace: List[Dict[str, Any]], thread_id: Optional[str]) -> Optional[int]:
    """Salva l'episodio del turno; turni in attesa di approvazione esclusi (si concludono in un turno successivo)."""
    if any(e.get("approval_required") for e in trace):
        return None
    text = describe(task, trace)
    if not text:
        return None
    steps = executed_steps(trace)
    metadata = {
        "mode": mode,
        "task": _clip(task, MAX_TASK_CHARS),
        "outcome": outcome_of(steps),
        "steps": [
            {
                "tool": e["tool_name"],
                "args": _clip(json.dumps(e.get("args") or {}, ensure_ascii=False), MAX_ARGS_CHARS),
                "error": _clip(e["error"], MAX_ERROR_CHARS) if e.get("error") else None,
                "rolled_back": bool(e.get("rollback_executed")),
            }
            for e in steps
        ],
    }
    return vector_store.add_memory(text, kind="episode", thread_id=thread_id, metadata=metadata)


def _rows(conn, where: str, params: list) -> List[Dict[str, Any]]:
    rows = conn.execute(f"SELECT id, thread_id, content, metadata_json, created_at FROM vec_memory WHERE kind = 'episode'{where}", params).fetchall()
    episodes = []
    for episode_id, thread_id, content, metadata_json, created_at in rows:
        metadata = json.loads(metadata_json) if metadata_json else {}
        episodes.append({
            "id": episode_id,
            "content": content,
            "thread_id": thread_id,
            "mode": metadata.get("mode"),
            "task": metadata.get("task"),
            "outcome": metadata.get("outcome"),
            "steps": metadata.get("steps", []),
            # CURRENT_TIMESTAMP di SQLite è UTC senza fuso: ISO 8601 esplicito per i client
            "created_at": f"{str(created_at).replace(' ', 'T')}+00:00" if created_at else None,
        })
    return episodes


def list_episodes(*, limit: int = 50, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """Episodi dal più recente, con il totale per la paginazione."""
    conn = vector_store._get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM vec_memory WHERE kind = 'episode'").fetchone()[0]
        return _rows(conn, " ORDER BY id DESC LIMIT ? OFFSET ?", [limit, offset]), total
    finally:
        conn.close()


def search_episodes(query: str, *, k: int = 20, min_score: float = RELEVANT_SCORE) -> List[Dict[str, Any]]:
    """Episodi pertinenti alla richiesta, dal più pertinente, con la somiglianza coseno in `score`."""
    hits = hybrid_search.hybrid_search(
        query, kind="episode", k=k, min_score=min_score, keyword_min_score=min(min_score, KEYWORD_RELEVANT_SCORE)
    )
    if not hits:
        return []
    conn = vector_store._get_conn()
    try:
        by_id = {e["id"]: e for e in _rows(conn, f" AND id IN ({','.join('?' * len(hits))})", [i for i, _ in hits])}
    finally:
        conn.close()
    return [{**by_id[i], "score": round(score, 3)} for i, score in hits if i in by_id]


def delete_episode(episode_id: int) -> bool:
    conn = vector_store._get_conn()
    try:
        found = conn.execute("SELECT 1 FROM vec_memory WHERE id = ? AND kind = 'episode'", (episode_id,)).fetchone()
    finally:
        conn.close()
    return bool(found) and vector_store.delete_memory(episode_id)


def clear_episodes() -> int:
    return vector_store.clear_all_memories(kind="episode")


def similar_episodes(task: str, k: int) -> List[Dict[str, Any]]:
    """Gli episodi più simili alla richiesta, per la memoria dei turni act e plan."""
    return search_episodes(task, k=k)
