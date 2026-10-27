"""Integrazioni di servizio (`service_integrations`)."""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.automations.db.connection import get_db_connection

logger = logging.getLogger("automations.db")


def list_integrations(service_type: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Elenca le integrazioni di terze parti registrate."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        if service_type:
            cursor.execute("SELECT * FROM service_integrations WHERE service_type = ? ORDER BY created_at ASC", (service_type,))
        else:
            cursor.execute("SELECT * FROM service_integrations ORDER BY created_at ASC")
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_integration(integration_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Recupera un'integrazione per ID."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM service_integrations WHERE id = ?", (integration_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_integration(data: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """Salva o aggiorna un'integrazione."""
    conn = get_db_connection(db_path)
    now = datetime.now(timezone.utc).isoformat()
    int_id = data["id"]
    try:
        conn.execute("""
            INSERT INTO service_integrations (
                id, service_type, name, config_json, encrypted_secrets_json,
                status, last_tested_at, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                service_type = excluded.service_type,
                name = excluded.name,
                config_json = excluded.config_json,
                encrypted_secrets_json = excluded.encrypted_secrets_json,
                status = excluded.status,
                last_tested_at = COALESCE(excluded.last_tested_at, service_integrations.last_tested_at),
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
        """, (
            int_id,
            data.get("service_type", "generic_secret"),
            data.get("name", int_id),
            data.get("config_json", "{}"),
            data.get("encrypted_secrets_json", "{}"),
            data.get("status", "untested"),
            data.get("last_tested_at"),
            data.get("last_error"),
            data.get("created_at", now),
            now,
        ))
        conn.commit()
    finally:
        conn.close()
    return get_integration(int_id, db_path=db_path)


def update_integration_status(
    integration_id: str,
    status: str,
    last_tested_at: Optional[str] = None,
    last_error: Optional[str] = None,
    db_path: Optional[str] = None
) -> bool:
    """Aggiorna lo stato diagnostico di un'integrazione."""
    conn = get_db_connection(db_path)
    now = datetime.now(timezone.utc).isoformat()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE service_integrations
            SET status = ?, last_tested_at = COALESCE(?, last_tested_at), last_error = ?, updated_at = ?
            WHERE id = ?
        """, (status, last_tested_at, last_error, now, integration_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_integration(integration_id: str, db_path: Optional[str] = None) -> bool:
    """Elimina un'integrazione."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM service_integrations WHERE id = ?", (integration_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
