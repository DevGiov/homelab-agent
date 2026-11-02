"""Stato di un lavoro sospeso in attesa di un'approvazione: il loop, il piano o lo step di automazione che l'ha chiesta.

Sta nel database, indicizzato dall'id della richiesta, così la ripresa sopravvive a un riavvio del backend. Si cancella
quando il lavoro riprende; i record mai risolti scadono dopo MAX_AGE_HOURS.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.memory import thread_store

logger = logging.getLogger("turn_checkpoints")

# Supera la scadenza più lunga di una richiesta (24 ore per le run delle automazioni)
MAX_AGE_HOURS = 48


def _conn():
    conn = thread_store._get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS turn_checkpoints (
            request_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    return conn


def save(request_id: str, kind: str, state: Dict[str, Any]) -> bool:
    """False se lo stato non si può salvare: la richiesta resta valida, ma il lavoro non riprenderà."""
    now = datetime.now(timezone.utc)
    try:
        conn = _conn()
        try:
            conn.execute("DELETE FROM turn_checkpoints WHERE created_at < ?", ((now - timedelta(hours=MAX_AGE_HOURS)).isoformat(),))
            conn.execute("INSERT OR REPLACE INTO turn_checkpoints (request_id, kind, state, created_at) VALUES (?, ?, ?, ?)",
                         (request_id, kind, json.dumps(state, ensure_ascii=False, default=str), now.isoformat()))
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as e:
        logger.warning(f"Stato della richiesta '{request_id}' non salvato: {e}")
        return False


def load(request_id: str) -> Optional[Dict[str, Any]]:
    """{"kind", "state"} del lavoro sospeso su questa richiesta, o None."""
    conn = _conn()
    try:
        row = conn.execute("SELECT kind, state FROM turn_checkpoints WHERE request_id = ?", (request_id,)).fetchone()
    finally:
        conn.close()
    return {"kind": row[0], "state": json.loads(row[1])} if row else None


def delete(request_id: str) -> None:
    conn = _conn()
    try:
        conn.execute("DELETE FROM turn_checkpoints WHERE request_id = ?", (request_id,))
        conn.commit()
    finally:
        conn.close()
