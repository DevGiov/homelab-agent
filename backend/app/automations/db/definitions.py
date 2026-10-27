"""Definizioni delle automazioni (`automation_definitions`)."""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.automations.db.connection import get_db_connection

logger = logging.getLogger("automations.db")


def save_definition(definition_dict: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    conn = get_db_connection(db_path)
    now = datetime.now(timezone.utc).isoformat()
    auto_id = definition_dict["id"]
    spec_json = json.dumps(definition_dict, ensure_ascii=False)
    retention_days = definition_dict.get("retention_days")
    settings_json = json.dumps(definition_dict.get("settings", {}), ensure_ascii=False)
    try:
        conn.execute("""
            INSERT INTO automation_definitions (
                id, name, description, version, enabled, spec_json, settings_json, retention_days,
                created_by, source_type, source_reference, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                version = excluded.version,
                enabled = excluded.enabled,
                spec_json = excluded.spec_json,
                settings_json = excluded.settings_json,
                retention_days = excluded.retention_days,
                updated_at = excluded.updated_at
        """, (
            auto_id,
            definition_dict.get("name", "Untitled"),
            definition_dict.get("description", ""),
            int(definition_dict.get("version", 1)),
            1 if definition_dict.get("enabled", True) else 0,
            spec_json,
            settings_json,
            retention_days,
            definition_dict.get("created_by", "user"),
            definition_dict.get("source_type", "ui"),
            definition_dict.get("source_reference"),
            now,
            now
        ))
        conn.commit()
    finally:
        conn.close()
    return definition_dict


def get_definition(auto_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, description, created_by, source_type, spec_json, enabled, version, settings_json, retention_days
            FROM automation_definitions WHERE id = ?
        """, (auto_id,))
        row = cursor.fetchone()
        if not row:
            return None
        try:
            data = json.loads(row["spec_json"])
        except Exception:
            data = {}
        data["id"] = data.get("id") or row["id"]
        data["name"] = data.get("name") or row["name"] or "Untitled"
        data["description"] = data.get("description") or row["description"] or ""
        data["created_by"] = data.get("created_by") or row["created_by"] or "user"
        data["source_type"] = data.get("source_type") or row["source_type"] or "ui"
        data["enabled"] = bool(row["enabled"])
        data["version"] = int(row["version"] or 1)
        if row["retention_days"] is not None:
            data["retention_days"] = int(row["retention_days"])
        if row["settings_json"]:
            try:
                data["settings"] = json.loads(row["settings_json"])
            except Exception:
                data["settings"] = {}
        return data
    finally:
        conn.close()


def list_definitions(enabled_only: bool = False, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        query = """
            SELECT
                ad.id, ad.name, ad.description, ad.created_by, ad.source_type, ad.source_reference,
                ad.spec_json, ad.enabled, ad.version, ad.settings_json, ad.retention_days,
                (SELECT status FROM automation_runs WHERE automation_id = ad.id ORDER BY started_at DESC LIMIT 1) as last_run_status,
                (SELECT started_at FROM automation_runs WHERE automation_id = ad.id ORDER BY started_at DESC LIMIT 1) as last_run_at,
                (SELECT a.artifact_id FROM artifacts a JOIN automation_runs r ON a.run_id = r.run_id WHERE r.automation_id = ad.id ORDER BY a.created_at DESC LIMIT 1) as last_artifact_id,
                (SELECT a.name FROM artifacts a JOIN automation_runs r ON a.run_id = r.run_id WHERE r.automation_id = ad.id ORDER BY a.created_at DESC LIMIT 1) as last_artifact_name,
                (SELECT a.created_at FROM artifacts a JOIN automation_runs r ON a.run_id = r.run_id WHERE r.automation_id = ad.id ORDER BY a.created_at DESC LIMIT 1) as last_artifact_at
            FROM automation_definitions ad
            WHERE ad.id != 'system_manual'
        """
        if enabled_only:
            query += " AND ad.enabled = 1"
        query += " ORDER BY ad.name ASC"

        cursor.execute(query)
        rows = cursor.fetchall()
        result = []
        for r in rows:
            try:
                data = json.loads(r["spec_json"])
            except Exception:
                data = {}
            data["id"] = data.get("id") or r["id"]
            data["name"] = data.get("name") or r["name"] or "Untitled"
            data["description"] = data.get("description") or r["description"] or ""
            data["created_by"] = data.get("created_by") or r["created_by"] or "user"
            data["source_type"] = data.get("source_type") or r["source_type"] or "ui"
            data["enabled"] = bool(r["enabled"])
            data["version"] = int(r["version"] or 1)
            if r["retention_days"] is not None:
                data["retention_days"] = int(r["retention_days"])
            if r["settings_json"]:
                try:
                    data["settings"] = json.loads(r["settings_json"])
                except Exception:
                    data["settings"] = {}
            data["last_run_status"] = r["last_run_status"]
            data["last_run_at"] = r["last_run_at"]
            data["last_artifact_id"] = r["last_artifact_id"]
            data["last_artifact_name"] = r["last_artifact_name"]
            data["last_artifact_at"] = r["last_artifact_at"]
            result.append(data)
        return result
    finally:
        conn.close()


def set_definition_enabled(auto_id: str, enabled: bool, db_path: Optional[str] = None) -> bool:
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE automation_definitions SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (1 if enabled else 0, auto_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_definition(auto_id: str, db_path: Optional[str] = None) -> bool:
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM automation_definitions WHERE id = ?", (auto_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
