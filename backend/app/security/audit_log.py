"""Audit log persistente di ogni tool call (Fase 0.4)."""
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger("audit_log")


def _get_conn():
    return sqlite3.connect(settings.checkpoint_db_path)


def init_audit_db():
    conn = _get_conn()
    try:
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_thread ON audit_log(thread_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_auto ON audit_log(automation_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_log(run_id)")
        conn.commit()
    finally:
        conn.close()


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


def count_calls(key: str, since: str) -> Tuple[int, int]:
    """(chiamate, errori) dei tool di un turno: `key` è il thread della chat o la run dell'automazione."""
    conn = _get_conn()
    try:
        calls, errors = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(is_error), 0) FROM audit_log WHERE (thread_id = ? OR run_id = ?) AND timestamp >= ?",
            (key, key, since),
        ).fetchone()
        return int(calls), int(errors)
    finally:
        conn.close()


def tool_stats(since: str) -> List[Dict[str, Any]]:
    """Per tool dalla data `since`: chiamate, errori e durate (media e 95° percentile), più lenti per primi."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT tool_name, is_error, duration_ms FROM audit_log WHERE timestamp >= ? AND result_summary NOT LIKE '{\"approval_pending\"%'",
            (since,),
        ).fetchall()
    finally:
        conn.close()
    by_tool: Dict[str, Dict[str, Any]] = {}
    for tool, is_error, duration in rows:
        entry = by_tool.setdefault(tool, {"tool": tool, "calls": 0, "errors": 0, "durations": []})
        entry["calls"] += 1
        entry["errors"] += int(is_error or 0)
        if duration:
            entry["durations"].append(duration)
    stats = []
    for entry in by_tool.values():
        durations = sorted(entry.pop("durations"))
        entry["avg_ms"] = round(sum(durations) / len(durations)) if durations else None
        entry["p95_ms"] = durations[min(len(durations) - 1, int(len(durations) * 0.95))] if durations else None
        stats.append(entry)
    return sorted(stats, key=lambda s: s["avg_ms"] or 0, reverse=True)
