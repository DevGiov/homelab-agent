"""Stato persistente dei circuit breaker (`circuit_breaker_states`)."""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.automations.db.connection import get_db_connection

logger = logging.getLogger("automations.db")


def get_circuit_breaker_state(automation_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM circuit_breaker_states WHERE automation_id = ?", (automation_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_circuit_breaker_state(state_data: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    conn = get_db_connection(db_path)
    try:
        conn.execute("""
            INSERT INTO circuit_breaker_states (
                automation_id, state, consecutive_failures, last_failure_reason,
                tripped_at, cooldown_seconds, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(automation_id) DO UPDATE SET
                state = excluded.state,
                consecutive_failures = excluded.consecutive_failures,
                last_failure_reason = excluded.last_failure_reason,
                tripped_at = excluded.tripped_at,
                cooldown_seconds = excluded.cooldown_seconds,
                updated_at = excluded.updated_at
        """, (
            state_data["automation_id"],
            state_data.get("state", "CLOSED"),
            state_data.get("consecutive_failures", 0),
            state_data.get("last_failure_reason"),
            state_data.get("tripped_at"),
            state_data.get("cooldown_seconds", 1800),
            state_data.get("updated_at", datetime.now(timezone.utc).isoformat())
        ))
        conn.commit()
    finally:
        conn.close()
    return state_data
