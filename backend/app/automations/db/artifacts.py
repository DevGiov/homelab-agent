"""Artefatti prodotti dalle run (`artifacts`)."""
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.automations.db.connection import get_db_connection

logger = logging.getLogger("automations.db")


def save_artifact(artifact_data: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    conn = get_db_connection(db_path)
    run_id = artifact_data.get("run_id") or "manual_or_direct"
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM automation_runs WHERE run_id = ?", (run_id,))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT OR IGNORE INTO automation_definitions (id, name, description, enabled, spec_json)
                VALUES ('system_manual', 'System Manual Actions', 'Automazione virtuale di sistema', 1, '{}')
            """)
            cursor.execute("""
                INSERT OR IGNORE INTO automation_runs (
                    run_id, automation_id, version_applied, trigger_type, status, started_at
                ) VALUES (?, 'system_manual', 1, 'manual', 'completed', ?)
            """, (run_id, datetime.now(timezone.utc).isoformat()))
            conn.commit()

        cursor.execute("""
            INSERT INTO artifacts (
                artifact_id, run_id, step_run_id, name, type, mime_type, storage_uri, checksum_sha256,
                is_preserved, is_favorite, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(artifact_id) DO UPDATE SET
                name = excluded.name,
                type = excluded.type,
                mime_type = excluded.mime_type,
                storage_uri = excluded.storage_uri,
                checksum_sha256 = excluded.checksum_sha256,
                is_preserved = excluded.is_preserved,
                is_favorite = excluded.is_favorite
        """, (
            artifact_data["artifact_id"],
            run_id,
            artifact_data.get("step_run_id"),
            artifact_data.get("title") or artifact_data.get("name", "Report Automazione"),
            artifact_data.get("type", "report"),
            artifact_data.get("mime_type", "text/plain"),
            artifact_data["storage_uri"],
            artifact_data.get("checksum_sha256"),
            1 if artifact_data.get("is_preserved") else 0,
            1 if artifact_data.get("is_favorite") else 0,
            artifact_data.get("created_at", datetime.now(timezone.utc).isoformat())
        ))
        conn.commit()
    finally:
        conn.close()
    return artifact_data


def get_artifact(artifact_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                a.*,
                r.automation_id,
                d.name as automation_name,
                r.status as run_status
            FROM artifacts a
            LEFT JOIN automation_runs r ON a.run_id = r.run_id
            LEFT JOIN automation_definitions d ON r.automation_id = d.id
            WHERE a.artifact_id = ?
        """, (artifact_id,))
        row = cursor.fetchone()
        if not row:
            return None
        art = dict(row)
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
        return art
    finally:
        conn.close()


def list_artifacts(run_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Elenca tutti gli artefatti associati a una run."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at ASC", (run_id,))
        rows = cursor.fetchall()
        results = []
        for r in rows:
            art = dict(r)
            art["is_preserved"] = bool(art.get("is_preserved", 0))
            art["is_favorite"] = bool(art.get("is_favorite", 0))
            results.append(art)
        return results
    finally:
        conn.close()


def list_all_artifacts(automation_id: Optional[str] = None, type: Optional[str] = None,
                       query: Optional[str] = None, search: Optional[str] = None,
                       favorite_only: bool = False, starred_only: bool = False,
                       preserved_only: bool = False, limit: int = 50, offset: int = 0,
                       db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Elenca tutti gli artefatti del sistema con filtri, unendo informazioni sull'automazione associata."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        sql_query = """
            SELECT
                a.artifact_id, a.run_id, a.step_run_id, a.name, a.type, a.mime_type,
                a.storage_uri, a.checksum_sha256, a.is_preserved, a.is_favorite, a.created_at,
                r.automation_id,
                d.name as automation_name,
                r.status as run_status
            FROM artifacts a
            LEFT JOIN automation_runs r ON a.run_id = r.run_id
            LEFT JOIN automation_definitions d ON r.automation_id = d.id
        """
        where = []
        params: List[Any] = []
        if automation_id:
            where.append("r.automation_id = ?")
            params.append(automation_id)
        if type:
            where.append("a.type = ?")
            params.append(type)
        search_term = query or search
        if search_term:
            where.append("(a.name LIKE ? OR d.name LIKE ?)")
            params.extend([f"%{search_term}%", f"%{search_term}%"])
        if favorite_only or starred_only:
            where.append("a.is_favorite = 1")
        if preserved_only:
            where.append("a.is_preserved = 1")

        if where:
            sql_query += " WHERE " + " AND ".join(where)

        sql_query += " ORDER BY a.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(sql_query, tuple(params))
        results = []
        for row in cursor.fetchall():
            art = dict(row)
            art["title"] = art["name"]
            art["is_preserved"] = bool(art.get("is_preserved", 0))
            art["is_favorite"] = bool(art.get("is_favorite", 0))
            results.append(art)
        return results
    finally:
        conn.close()


def get_latest_artifact_for_automation(automation_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Recupera l'ultimo artefatto generato per una specifica automazione."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.artifact_id
            FROM artifacts a
            JOIN automation_runs r ON a.run_id = r.run_id
            WHERE r.automation_id = ?
            ORDER BY a.created_at DESC LIMIT 1
        """, (automation_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return get_artifact(row["artifact_id"], db_path=db_path)
    finally:
        conn.close()


def toggle_artifact_favorite(artifact_id: str, is_favorite: Optional[bool] = None, db_path: Optional[str] = None) -> Optional[bool]:
    """Imposta, rimuove o inverte lo stato preferito (star) da un artefatto."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        if is_favorite is None:
            cursor.execute("SELECT is_favorite FROM artifacts WHERE artifact_id = ?", (artifact_id,))
            row = cursor.fetchone()
            if not row:
                return None
            new_val = 0 if row["is_favorite"] else 1
        else:
            new_val = 1 if is_favorite else 0
        cursor.execute("UPDATE artifacts SET is_favorite = ? WHERE artifact_id = ?", (new_val, artifact_id))
        conn.commit()
        return bool(new_val)
    finally:
        conn.close()


def toggle_artifact_preserve(artifact_id: str, is_preserved: Optional[bool] = None, db_path: Optional[str] = None) -> Optional[bool]:
    """Imposta, rimuove o inverte la protezione da eliminazione su un artefatto."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        if is_preserved is None:
            cursor.execute("SELECT is_preserved FROM artifacts WHERE artifact_id = ?", (artifact_id,))
            row = cursor.fetchone()
            if not row:
                return None
            new_val = 0 if row["is_preserved"] else 1
        else:
            new_val = 1 if is_preserved else 0
        cursor.execute("UPDATE artifacts SET is_preserved = ? WHERE artifact_id = ?", (new_val, artifact_id))
        conn.commit()
        return bool(new_val)
    finally:
        conn.close()


def delete_artifact(artifact_id: str, force: bool = False, db_path: Optional[str] = None) -> bool:
    """Elimina definitivamente un artefatto e il suo file corrispondente su disco se non preservato."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT storage_uri, is_preserved FROM artifacts WHERE artifact_id = ?", (artifact_id,))
        row = cursor.fetchone()
        if not row:
            return False
        if bool(row["is_preserved"]) and not force:
            return False
        storage_uri = row["storage_uri"]
        if storage_uri and os.path.isfile(storage_uri):
            try:
                os.remove(storage_uri)
            except Exception:
                pass
        cursor.execute("DELETE FROM artifacts WHERE artifact_id = ?", (artifact_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
