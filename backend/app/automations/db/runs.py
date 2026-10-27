"""Run delle automazioni e relativi step (`automation_runs`, `step_runs`), retention e contatori per i limiti."""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.automations.db.connection import get_db_connection

logger = logging.getLogger("automations.db")


def create_run(run_data: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    conn = get_db_connection(db_path)
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute("""
            INSERT INTO automation_runs (
                run_id, automation_id, version_applied, trigger_type, trigger_payload_json,
                status, current_step_id, is_dry_run, is_preserved, is_favorite,
                started_at, idempotency_key, associated_thread_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_data["run_id"],
            run_data["automation_id"],
            run_data.get("version_applied", 1),
            run_data.get("trigger_type", "manual"),
            json.dumps(run_data.get("trigger_payload", {}), ensure_ascii=False),
            run_data.get("status", "pending"),
            run_data.get("current_step_id"),
            1 if run_data.get("is_dry_run") else 0,
            1 if run_data.get("is_preserved") else 0,
            1 if run_data.get("is_favorite") else 0,
            now,
            run_data.get("idempotency_key"),
            run_data.get("associated_thread_id")
        ))
        conn.commit()
    finally:
        conn.close()
    return run_data


def get_run(run_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM automation_runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["trigger_payload"] = json.loads(d.pop("trigger_payload_json", "{}"))
        d["is_dry_run"] = bool(d["is_dry_run"])
        d["is_preserved"] = bool(d.get("is_preserved", 0))
        d["is_favorite"] = bool(d.get("is_favorite", 0))

        # Fetch step runs
        cursor.execute("SELECT * FROM step_runs WHERE run_id = ? ORDER BY started_at ASC", (run_id,))
        steps = []
        for s in cursor.fetchall():
            s_dict = dict(s)
            s_dict["input_payload"] = json.loads(s_dict.pop("input_payload_json", "{}"))
            s_dict["output_payload"] = json.loads(s_dict.pop("output_payload_json")) if s_dict.get("output_payload_json") else None
            s_dict["tool_calls"] = json.loads(s_dict.pop("tool_calls_json", "[]"))
            steps.append(s_dict)
        d["step_runs"] = steps

        # Fetch artifacts
        cursor.execute("SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at ASC", (run_id,))
        artifacts = []
        for a in cursor.fetchall():
            art = dict(a)
            if not art.get("title") and art.get("name"):
                art["title"] = art["name"]
            art["is_preserved"] = bool(art.get("is_preserved", 0))
            art["is_favorite"] = bool(art.get("is_favorite", 0))
            if "content" not in art or not art["content"]:
                storage_uri = art.get("storage_uri", "")
                if storage_uri and os.path.isfile(storage_uri):
                    try:
                        with open(storage_uri, "r", encoding="utf-8", errors="replace") as f:
                            art["content"] = f.read()
                    except Exception:
                        art["content"] = ""
                else:
                    art["content"] = ""
            artifacts.append(art)
        d["artifacts"] = artifacts

        # Fetch pending approval if any
        cursor.execute("SELECT request_id FROM automation_approvals WHERE run_id = ? AND status = 'pending'", (run_id,))
        appr_row = cursor.fetchone()
        d["pending_approval_id"] = appr_row["request_id"] if appr_row else None

        return d
    finally:
        conn.close()


def update_run_status(run_id: str, status: str, current_step_id: Optional[str] = None,
                      error_message: Optional[str] = None, total_tokens: Optional[int] = None,
                      total_duration_ms: Optional[int] = None, db_path: Optional[str] = None) -> bool:
    conn = get_db_connection(db_path)
    now = datetime.now(timezone.utc).isoformat() if status in ("completed", "failed", "cancelled", "exhausted", "blocked") else None
    try:
        cursor = conn.cursor()
        updates = ["status = ?"]
        params: List[Any] = [status]

        if current_step_id is not None:
            updates.append("current_step_id = ?")
            params.append(current_step_id)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        if total_tokens is not None:
            updates.append("total_tokens = ?")
            params.append(total_tokens)
        if total_duration_ms is not None:
            updates.append("total_duration_ms = ?")
            params.append(total_duration_ms)
        if now is not None:
            updates.append("completed_at = ?")
            params.append(now)

        params.append(run_id)
        sql = f"UPDATE automation_runs SET {', '.join(updates)} WHERE run_id = ?"
        cursor.execute(sql, tuple(params))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def list_runs(automation_id: Optional[str] = None, status: Optional[str] = None,
              starred_only: bool = False, preserved_only: bool = False,
              limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        query = """
            SELECT
                r.run_id, r.automation_id, r.version_applied, r.trigger_type, r.status,
                r.current_step_id, r.is_dry_run, r.is_preserved, r.is_favorite,
                r.started_at, r.completed_at, r.total_tokens, r.total_duration_ms, r.error_message,
                (SELECT COUNT(*) FROM artifacts WHERE run_id = r.run_id) as artifacts_count
            FROM automation_runs r
        """
        conditions = []
        params = []
        if automation_id:
            conditions.append("r.automation_id = ?")
            params.append(automation_id)
        if status:
            conditions.append("r.status = ?")
            params.append(status)
        if starred_only:
            conditions.append("r.is_favorite = 1")
        if preserved_only:
            conditions.append("r.is_preserved = 1")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY r.started_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, tuple(params))
        results = []
        for r in cursor.fetchall():
            row_dict = dict(r)
            row_dict["is_dry_run"] = bool(row_dict.get("is_dry_run", 0))
            row_dict["is_preserved"] = bool(row_dict.get("is_preserved", 0))
            row_dict["is_favorite"] = bool(row_dict.get("is_favorite", 0))
            row_dict["artifacts_count"] = int(row_dict.get("artifacts_count", 0))
            results.append(row_dict)
        return results
    finally:
        conn.close()


def toggle_run_favorite(run_id: str, is_favorite: Optional[bool] = None, db_path: Optional[str] = None) -> Optional[bool]:
    """Imposta, rimuove o inverte lo stato preferito (star) da una run."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        if is_favorite is None:
            cursor.execute("SELECT is_favorite FROM automation_runs WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            if not row:
                return None
            new_val = 0 if row["is_favorite"] else 1
        else:
            new_val = 1 if is_favorite else 0
        cursor.execute("UPDATE automation_runs SET is_favorite = ? WHERE run_id = ?", (new_val, run_id))
        conn.commit()
        return bool(new_val)
    finally:
        conn.close()


def toggle_run_preserve(run_id: str, is_preserved: Optional[bool] = None, db_path: Optional[str] = None) -> Optional[bool]:
    """Imposta, rimuove o inverte il blocco di conservazione da auto-cleanup su una run."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        if is_preserved is None:
            cursor.execute("SELECT is_preserved FROM automation_runs WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            if not row:
                return None
            new_val = 0 if row["is_preserved"] else 1
        else:
            new_val = 1 if is_preserved else 0
        cursor.execute("UPDATE automation_runs SET is_preserved = ? WHERE run_id = ?", (new_val, run_id))
        conn.commit()
        return bool(new_val)
    finally:
        conn.close()


def delete_run(run_id: str, force: bool = False, db_path: Optional[str] = None) -> bool:
    """Elimina definitivamente una run e ripulisce gli artefatti e i file fisici su disco."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT is_preserved, is_favorite FROM automation_runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        if not row:
            return False
        if bool(row["is_preserved"]) and not force:
            raise ValueError("Impossibile eliminare una run contrassegnata come 'Preservata' senza force=True.")

        # Elimina file fisici degli artefatti associati
        cursor.execute("SELECT storage_uri FROM artifacts WHERE run_id = ?", (run_id,))
        for art_row in cursor.fetchall():
            s_uri = art_row["storage_uri"]
            if s_uri and os.path.isfile(s_uri):
                try:
                    os.remove(s_uri)
                except Exception:
                    pass

        cursor.execute("DELETE FROM automation_runs WHERE run_id = ?", (run_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def bulk_delete_runs(status: Optional[str] = None, older_than_days: Optional[int] = None,
                     automation_id: Optional[str] = None, failed_only: bool = False,
                     preserve_protected: bool = True, run_ids: Optional[List[str]] = None,
                     db_path: Optional[str] = None) -> int:
    """Elimina in blocco esecuzioni storiche (es. pulizia fallite, retention o selezione manuale)."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        where = []
        params: List[Any] = []

        if run_ids:
            clean_ids = [str(rid).strip() for rid in run_ids if rid]
            if clean_ids:
                in_placeholders = ",".join("?" for _ in clean_ids)
                where.append(f"run_id IN ({in_placeholders})")
                params.extend(clean_ids)
            else:
                return 0

        if failed_only:
            where.append("status IN ('failed', 'cancelled', 'exhausted')")
        elif status:
            where.append("status = ?")
            params.append(status)

        if older_than_days is not None:
            # datetime() normalizza sia ISO 8601 con offset sia CURRENT_TIMESTAMP in UTC
            where.append("datetime(started_at) < datetime('now', ?)")
            params.append(f"-{int(older_than_days)} days")

        if automation_id:
            where.append("automation_id = ?")
            params.append(automation_id)

        if preserve_protected:
            where.append("is_preserved = 0 AND is_favorite = 0")

        where_clause = (" WHERE " + " AND ".join(where)) if where else ""

        cursor.execute(f"SELECT run_id FROM automation_runs{where_clause}", tuple(params))
        target_run_ids = [r["run_id"] for r in cursor.fetchall()]
        if not target_run_ids:
            return 0

        # Rimuovi file fisici
        placeholders = ",".join("?" for _ in target_run_ids)
        cursor.execute(f"SELECT storage_uri FROM artifacts WHERE run_id IN ({placeholders})", tuple(target_run_ids))
        for art_row in cursor.fetchall():
            s_uri = art_row["storage_uri"]
            if s_uri and os.path.isfile(s_uri):
                try:
                    os.remove(s_uri)
                except Exception:
                    pass

        cursor.execute(f"DELETE FROM automation_runs WHERE run_id IN ({placeholders})", tuple(target_run_ids))
        deleted_count = cursor.rowcount
        conn.commit()
        return deleted_count
    finally:
        conn.close()


def get_run_by_idempotency_key(key: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT run_id, status FROM automation_runs WHERE idempotency_key = ?", (key,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_step_run(step_data: Dict[str, Any], db_path: Optional[str] = None):
    conn = get_db_connection(db_path)
    try:
        conn.execute("""
            INSERT INTO step_runs (
                step_run_id, run_id, step_id, status, attempt, started_at, completed_at,
                input_payload_json, output_payload_json, error_message, tool_calls_json,
                tokens_consumed, approval_request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(step_run_id) DO UPDATE SET
                status = excluded.status,
                completed_at = excluded.completed_at,
                output_payload_json = excluded.output_payload_json,
                error_message = excluded.error_message,
                tool_calls_json = excluded.tool_calls_json,
                tokens_consumed = excluded.tokens_consumed,
                approval_request_id = excluded.approval_request_id
        """, (
            step_data["step_run_id"],
            step_data["run_id"],
            step_data["step_id"],
            step_data.get("status", "running"),
            step_data.get("attempt", 1),
            step_data.get("started_at"),
            step_data.get("completed_at"),
            json.dumps(step_data.get("input_payload", {}), ensure_ascii=False, default=str),
            json.dumps(step_data.get("output_payload"), ensure_ascii=False, default=str) if step_data.get("output_payload") is not None else None,
            step_data.get("error_message"),
            json.dumps(step_data.get("tool_calls", []), ensure_ascii=False, default=str),
            step_data.get("tokens_consumed", 0),
            step_data.get("approval_request_id")
        ))
        conn.commit()
    finally:
        conn.close()


def list_step_runs(run_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Recupera tutti gli step eseguiti per una specifica run."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM step_runs WHERE run_id = ? ORDER BY started_at ASC", (run_id,))
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("input_payload_json"):
                try:
                    d["input_payload"] = json.loads(d["input_payload_json"])
                except Exception:
                    pass
            if d.get("output_payload_json"):
                try:
                    d["output_payload"] = json.loads(d["output_payload_json"])
                except Exception:
                    pass
            if d.get("tool_calls_json"):
                try:
                    d["tool_calls"] = json.loads(d["tool_calls_json"])
                except Exception:
                    pass
            result.append(d)
        return result
    finally:
        conn.close()


def count_recent_runs(automation_id: str, window_seconds: int = 3600, db_path: Optional[str] = None) -> int:
    """Conta il numero di run avviate per questa automazione negli ultimi N secondi."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM automation_runs WHERE automation_id = ? AND started_at >= datetime('now', '-' || ? || ' seconds')",
            (automation_id, window_seconds)
        )
        row = cursor.fetchone()
        return int(row["cnt"]) if row else 0
    finally:
        conn.close()


def sum_recent_tokens(automation_id: str, window_seconds: int = 86400, db_path: Optional[str] = None) -> int:
    """Somma i token consumati per questa automazione negli ultimi N secondi."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) as tok FROM automation_runs WHERE automation_id = ? AND started_at >= datetime('now', '-' || ? || ' seconds')",
            (automation_id, window_seconds)
        )
        row = cursor.fetchone()
        return int(row["tok"]) if row else 0
    finally:
        conn.close()
