"""Richieste di approvazione persistenti (`automation_approvals`)."""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.automations.db.connection import get_db_connection

logger = logging.getLogger("automations.db")


def create_automation_approval(req_data: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    conn = get_db_connection(db_path)
    try:
        conn.execute("""
            INSERT INTO automation_approvals (
                request_id, run_id, step_run_id, tool_name, arguments_json,
                command_preview, command_prefix, risk_reason, status,
                created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(request_id) DO UPDATE SET
                status = excluded.status,
                command_preview = excluded.command_preview,
                risk_reason = excluded.risk_reason
        """, (
            req_data["request_id"],
            req_data["run_id"],
            req_data.get("step_run_id"),
            req_data["tool_name"],
            json.dumps(req_data.get("arguments", {}), ensure_ascii=False),
            req_data.get("command_preview"),
            req_data.get("command_prefix"),
            req_data.get("risk_reason"),
            req_data.get("status", "pending"),
            req_data.get("created_at", datetime.now(timezone.utc).isoformat()),
            req_data.get("expires_at", datetime.now(timezone.utc).isoformat())
        ))
        conn.commit()
    finally:
        conn.close()
    return req_data


def get_automation_approval(request_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM automation_approvals WHERE request_id = ?", (request_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["arguments"] = json.loads(d.pop("arguments_json", "{}"))
        return d
    finally:
        conn.close()


def clear_expired_automation_approvals(db_path: Optional[str] = None) -> int:
    """Aggiorna lo stato delle approvazioni scadute a 'expired'."""
    conn = get_db_connection(db_path)
    now = datetime.now(timezone.utc).isoformat()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE automation_approvals
            SET status = 'expired'
            WHERE status = 'pending' AND expires_at IS NOT NULL AND expires_at < ?
        """, (now,))
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def list_pending_approvals(run_id: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    # Aggiorna automaticamente le richieste scadute prima della lettura
    clear_expired_automation_approvals(db_path=db_path)

    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        if run_id:
            cursor.execute("SELECT * FROM automation_approvals WHERE run_id = ? AND status = 'pending' ORDER BY created_at ASC", (run_id,))
        else:
            cursor.execute("SELECT * FROM automation_approvals WHERE status = 'pending' ORDER BY created_at ASC")
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["arguments"] = json.loads(d.pop("arguments_json", "{}"))
            result.append(d)
        return result
    finally:
        conn.close()


def delete_automation_approval(request_id: str, db_path: Optional[str] = None) -> bool:
    """Elimina definitivamente un'approvazione dal database."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM automation_approvals WHERE request_id = ?", (request_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def resolve_automation_approval(request_id: str, action: str, resolved_by: str = "user", db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    now = datetime.now(timezone.utc).isoformat()
    norm_action = "approved" if action.lower() in ("approve", "approved", "true") else "denied"
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE automation_approvals
            SET status = ?, resolution_action = ?, resolved_by = ?, resolved_at = ?
            WHERE request_id = ? AND status = 'pending'
        """, (norm_action, norm_action, resolved_by, now, request_id))
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return get_automation_approval(request_id, db_path=db_path)
    finally:
        conn.close()
