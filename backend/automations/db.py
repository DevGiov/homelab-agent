"""Gestione storage SQLite dedicato per Automations & Loops.

Tabelle:
- automation_definitions
- automation_runs
- step_runs
- automation_approvals
- artifacts

Include configurazione WAL, busy_timeout a 30s e isolamento da checkpoints.db.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger("automations.db")


def get_db_path() -> str:
    path = config.AUTOMATIONS_DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    target_path = db_path or get_db_path()
    conn = sqlite3.connect(target_path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA synchronous = NORMAL;")
    cursor.execute("PRAGMA busy_timeout = 30000;")
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.close()
    return conn


def _ensure_v2_columns(cursor: sqlite3.Cursor):
    """Assicura l'esistenza delle colonne v2 in modo trasparente e performante."""
    def add_col(tbl: str, col: str, typedef: str):
        cursor.execute(f"PRAGMA table_info({tbl});")
        cols = [r[1] for r in cursor.fetchall()]
        if col not in cols:
            try:
                cursor.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {typedef};")
            except Exception:
                pass

    add_col("automation_definitions", "retention_days", "INTEGER DEFAULT NULL")
    add_col("automation_definitions", "settings_json", "TEXT DEFAULT '{}'")
    add_col("automation_runs", "is_preserved", "INTEGER NOT NULL DEFAULT 0")
    add_col("automation_runs", "is_favorite", "INTEGER NOT NULL DEFAULT 0")
    add_col("artifacts", "is_preserved", "INTEGER NOT NULL DEFAULT 0")
    add_col("artifacts", "is_favorite", "INTEGER NOT NULL DEFAULT 0")


def init_automations_db(db_path: Optional[str] = None):
    """Inizializza lo schema completo del database automazioni (v2 canonico)."""
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()

        # 1. Definizioni delle automazioni
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS automation_definitions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                enabled INTEGER NOT NULL DEFAULT 1,
                spec_json TEXT NOT NULL,
                settings_json TEXT DEFAULT '{}',
                retention_days INTEGER DEFAULT NULL,
                created_by TEXT NOT NULL DEFAULT 'user',
                source_type TEXT NOT NULL DEFAULT 'ui',
                source_reference TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Storico delle esecuzioni (Runs)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS automation_runs (
                run_id TEXT PRIMARY KEY,
                automation_id TEXT NOT NULL,
                version_applied INTEGER NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_payload_json TEXT DEFAULT '{}',
                status TEXT NOT NULL,
                current_step_id TEXT,
                is_dry_run INTEGER NOT NULL DEFAULT 0,
                is_preserved INTEGER NOT NULL DEFAULT 0,
                is_favorite INTEGER NOT NULL DEFAULT 0,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                total_tokens INTEGER DEFAULT 0,
                total_duration_ms INTEGER DEFAULT 0,
                idempotency_key TEXT UNIQUE,
                associated_thread_id TEXT,
                error_message TEXT,
                FOREIGN KEY(automation_id) REFERENCES automation_definitions(id) ON DELETE CASCADE
            )
        """)

        # 3. Singoli passaggi di esecuzione (Step Runs)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS step_runs (
                step_run_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 1,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                input_payload_json TEXT DEFAULT '{}',
                output_payload_json TEXT,
                error_message TEXT,
                tool_calls_json TEXT DEFAULT '[]',
                tokens_consumed INTEGER DEFAULT 0,
                approval_request_id TEXT,
                FOREIGN KEY(run_id) REFERENCES automation_runs(run_id) ON DELETE CASCADE
            )
        """)

        # 4. Richieste di approvazione persistenti
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS automation_approvals (
                request_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                step_run_id TEXT,
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                command_preview TEXT,
                command_prefix TEXT,
                risk_reason TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                resolved_at DATETIME,
                resolved_by TEXT,
                resolution_action TEXT
            )
        """)

        # 5. Registro degli artefatti prodotti
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                step_run_id TEXT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                mime_type TEXT NOT NULL DEFAULT 'text/plain',
                storage_uri TEXT NOT NULL,
                checksum_sha256 TEXT,
                is_preserved INTEGER NOT NULL DEFAULT 0,
                is_favorite INTEGER NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(run_id) REFERENCES automation_runs(run_id) ON DELETE CASCADE
            )
        """)

        # 6. Circuit Breaker States per automazione
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS circuit_breaker_states (
                automation_id TEXT PRIMARY KEY,
                state TEXT NOT NULL DEFAULT 'CLOSED',
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                last_failure_reason TEXT,
                tripped_at TEXT,
                cooldown_seconds INTEGER NOT NULL DEFAULT 1800,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(automation_id) REFERENCES automation_definitions(id) ON DELETE CASCADE
            )
        """)

        # 7. Integrazioni e Credenziali Servizi (Service Integrations)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS service_integrations (
                id TEXT PRIMARY KEY,
                service_type TEXT NOT NULL,
                name TEXT NOT NULL,
                is_default INTEGER NOT NULL DEFAULT 1,
                config_json TEXT NOT NULL DEFAULT '{}',
                encrypted_secrets_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'untested',
                last_tested_at DATETIME,
                last_error TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Allinea colonne su eventuali database esistenti PRIMA di creare gli indici
        _ensure_v2_columns(cursor)

        # Creazione indici (sicuri ora che le colonne esistono)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_auto_enabled ON automation_definitions(enabled)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_auto_id ON automation_runs(automation_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON automation_runs(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_started ON automation_runs(started_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_fav ON automation_runs(is_favorite)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_pres ON automation_runs(is_preserved)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_step_run_parent ON step_runs(run_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_auto_appr_status ON automation_approvals(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_auto_appr_run ON automation_approvals(run_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_created ON artifacts(created_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_fav ON artifacts(is_favorite)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_int_type ON service_integrations(service_type)")

        conn.commit()
        conn.close()
        logger.info(f"Database automazioni inizializzato con successo: {db_path or get_db_path()}")
    except Exception as e:
        logger.error(f"Errore inizializzazione schema automations.db: {e}", exc_info=True)
        raise


# --- CRUD Helpers: Automation Definitions ---

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
        cursor.execute("SELECT spec_json, enabled, version, settings_json, retention_days FROM automation_definitions WHERE id = ?", (auto_id,))
        row = cursor.fetchone()
        if not row:
            return None
        data = json.loads(row["spec_json"])
        data["enabled"] = bool(row["enabled"])
        data["version"] = int(row["version"])
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
                ad.spec_json, ad.enabled, ad.version, ad.settings_json, ad.retention_days,
                (SELECT status FROM automation_runs WHERE automation_id = ad.id ORDER BY started_at DESC LIMIT 1) as last_run_status,
                (SELECT started_at FROM automation_runs WHERE automation_id = ad.id ORDER BY started_at DESC LIMIT 1) as last_run_at,
                (SELECT a.artifact_id FROM artifacts a JOIN automation_runs r ON a.run_id = r.run_id WHERE r.automation_id = ad.id ORDER BY a.created_at DESC LIMIT 1) as last_artifact_id,
                (SELECT a.name FROM artifacts a JOIN automation_runs r ON a.run_id = r.run_id WHERE r.automation_id = ad.id ORDER BY a.created_at DESC LIMIT 1) as last_artifact_name,
                (SELECT a.created_at FROM artifacts a JOIN automation_runs r ON a.run_id = r.run_id WHERE r.automation_id = ad.id ORDER BY a.created_at DESC LIMIT 1) as last_artifact_at
            FROM automation_definitions ad
        """
        if enabled_only:
            query += " WHERE ad.enabled = 1"
        query += " ORDER BY ad.name ASC"

        cursor.execute(query)
        rows = cursor.fetchall()
        result = []
        for r in rows:
            data = json.loads(r["spec_json"])
            data["enabled"] = bool(r["enabled"])
            data["version"] = int(r["version"])
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


# --- CRUD Helpers: Runs & Step Runs ---

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


def bulk_delete_runs(status: Optional[str] = None, before_date: Optional[str] = None,
                     automation_id: Optional[str] = None, failed_only: bool = False,
                     preserve_protected: bool = True, db_path: Optional[str] = None) -> int:
    """Elimina in blocco esecuzioni storiche (es. pulizia fallite o scadute per retention)."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        where = []
        params: List[Any] = []

        if failed_only:
            where.append("status IN ('failed', 'cancelled', 'exhausted')")
        elif status:
            where.append("status = ?")
            params.append(status)

        if before_date:
            where.append("started_at < ?")
            params.append(before_date)

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


# --- CRUD Helpers: Step Runs ---

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


# --- CRUD Helpers: Approvals ---

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


# --- CRUD Helpers: Artifacts ---

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


# --- CRUD Helpers: Circuit Breaker (Milestone M4) ---

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


# Alias comodi per compatibilità semantica
get_automation = get_definition
list_automations = list_definitions
save_automation = save_definition
delete_automation = delete_definition


# --- CRUD Helpers: Service Integrations ---

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

