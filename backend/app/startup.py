"""Avvio del backend in un unico punto: sicurezza, schemi dei database, registry e scheduler.

Nessun modulo crea tabelle o connessioni all'import: lo fanno queste funzioni, chiamate dal
lifespan FastAPI (app.api.main), dalla CLI e dal conftest dei test. Un errore di
inizializzazione blocca l'avvio invece di lasciare un servizio a metà.
"""
import logging
from pathlib import Path

from app.agent.graph import get_checkpointer
from app.automations.db.schema import init_automations_db
from app.automations.scheduler import get_scheduler
from app.calendar.db import init_calendar_db
from app.core.config import settings
from app.memory import thread_store, vector_store
from app.registry.manager import get_registry_manager
from app.security import audit_log, permissions

logger = logging.getLogger("startup")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO)


def init_databases() -> None:
    """Crea gli schemi mancanti di tutti i database (idempotente)."""
    Path(settings.checkpoint_db_path).parent.mkdir(parents=True, exist_ok=True)
    # checkpoints.db: checkpoint LangGraph, thread, audit, permessi e memoria vettoriale
    get_checkpointer().setup()
    thread_store.init_db()
    audit_log.init_audit_db()
    permissions.init_permissions_db()
    vector_store.init_vector_db()
    init_automations_db()
    init_calendar_db()
    logger.info("Schemi dei database pronti")


def start() -> None:
    """Avvio completo del servizio API."""
    settings.validate_security()
    init_databases()
    get_registry_manager()
    if settings.enable_automation_scheduler:
        get_scheduler().start()


def stop() -> None:
    if settings.enable_automation_scheduler:
        get_scheduler().stop()
