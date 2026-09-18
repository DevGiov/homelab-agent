"""Audit log persistente di ogni tool call (Fase 0.4)."""
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import config

logger = logging.getLogger("audit_log")


def _get_conn():
    return sqlite3.connect(config.CHECKPOINT_DB_PATH)


def init_audit_db():
    try:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                thread_id TEXT,
                mode TEXT,
                tool_name TEXT NOT NULL,
                registry TEXT,
                arguments_json TEXT,
                result_summary TEXT,
                is_error INTEGER DEFAULT 0,
                duration_ms INTEGER,
                automation_id TEXT,
                run_id TEXT,
                step_run_id TEXT
            )
        """)
        # Migrazione schema dinamica se la tabella esisteva già senza le colonne automazione
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(audit_log)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        if "automation_id" not in existing_cols:
            conn.execute("ALTER TABLE audit_log ADD COLUMN automation_id TEXT")
        if "run_id" not in existing_cols:
            conn.execute("ALTER TABLE audit_log ADD COLUMN run_id TEXT")
        if "step_run_id" not in existing_cols:
            conn.execute("ALTER TABLE audit_log ADD COLUMN step_run_id TEXT")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_thread ON audit_log(thread_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_auto ON audit_log(automation_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_log(run_id)")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Errore inizializzazione audit_log: {e}")


init_audit_db()


def log_tool_call(
    tool_name: str,
    arguments: Dict[str, Any],
    *,
    thread_id: Optional[str] = None,
    mode: Optional[str] = None,
    registry: Optional[str] = None,
    result: Any = None,
    is_error: bool = False,
    duration_ms: Optional[int] = None,
    automation_id: Optional[str] = None,
    run_id: Optional[str] = None,
    step_run_id: Optional[str] = None,
) -> None:
    """Registra in modo persistente una chiamata a un tool. Mai bloccante."""
    try:
        if isinstance(result, (dict, list)):
            result_str = json.dumps(result, ensure_ascii=False, default=str)[:2000]
        else:
            result_str = str(result)[:2000] if result is not None else None

        conn = _get_conn()
        conn.execute(
            """INSERT INTO audit_log
               (timestamp, thread_id, mode, tool_name, registry, arguments_json, result_summary, is_error, duration_ms, automation_id, run_id, step_run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                thread_id,
                mode,
                tool_name,
                registry,
                json.dumps(arguments, ensure_ascii=False, default=str),
                result_str,
                1 if is_error else 0,
                duration_ms,
                automation_id,
                run_id,
                step_run_id,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Impossibile scrivere audit log: {e}")


def get_recent(
    limit: int = 100,
    thread_id: Optional[str] = None,
    automation_id: Optional[str] = None,
    run_id: Optional[str] = None,
):
    """Restituisce le ultime N voci di audit (per endpoint diagnostico o run inspector)."""
    try:
        conn = _get_conn()
        conn.row_factory = sqlite3.Row
        conditions = []
        params = []
        if thread_id:
            conditions.append("thread_id = ?")
            params.append(thread_id)
        if automation_id:
            conditions.append("automation_id = ?")
            params.append(automation_id)
        if run_id:
            conditions.append("run_id = ?")
            params.append(run_id)

        query = "SELECT * FROM audit_log"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, tuple(params)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Impossibile leggere audit log: {e}")
        return []
