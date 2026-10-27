"""Schema del database delle automazioni."""
import logging
from typing import Optional

from app.automations.db.connection import get_db_connection, get_db_path

logger = logging.getLogger("automations.db")


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
