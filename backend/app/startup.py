"""Avvio del backend in un unico punto: sicurezza, schemi dei database, registry, scheduler e campionamento della salute.

Nessun modulo crea tabelle o connessioni all'import: lo fanno queste funzioni, chiamate dal
lifespan FastAPI (app.api.main), dalla CLI e dal conftest dei test. Un errore di
inizializzazione blocca l'avvio invece di lasciare un servizio a metà.
"""
import logging
from pathlib import Path

from app.agent import memory_consolidation
from app.agent.graph import get_checkpointer
from app.automations.db.schema import init_automations_db
from app.automations.scheduler import get_scheduler
from app.calendar.db import init_calendar_db
from app.core.config import settings
from app.memory import facts, hybrid_search, procedures, profile, thread_store, vector_store
from app.observability import health
from app.observability.store import init_metrics_db
from app.registry.manager import get_registry_manager
from app.security import audit_log, permissions

logger = logging.getLogger("startup")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO)


def init_storage() -> None:
    """Crea le directory dei dati e gli schemi mancanti di tutti i database (idempotente)."""
    for directory in (settings.data_dir, settings.artifacts_dir, settings.uploads_dir,
                      settings.knowledge_base_dir, Path(settings.checkpoint_db_path).parent):
        Path(directory).mkdir(parents=True, exist_ok=True)
    # checkpoints.db: checkpoint LangGraph, thread, audit, permessi e memoria vettoriale
    get_checkpointer().setup()
    thread_store.init_db()
    profile.init_profile_db()
    procedures.init_procedures_db()
    memory_consolidation.init_consolidation_db()
    audit_log.init_audit_db()
    permissions.init_permissions_db()
    vector_store.init_vector_db()
    facts.init_facts_db()
    hybrid_search.init_search_indexes()
    init_automations_db()
    init_calendar_db()
    init_metrics_db()
    logger.info(f"Dati in {settings.data_dir}: directory e schemi pronti")


def start() -> None:
    """Avvio completo del servizio API."""
    settings.validate_security()
    init_storage()
    get_registry_manager()
    if settings.enable_automation_scheduler:
        get_scheduler().start()
    health.start_sampler()
    memory_consolidation.start_scheduler()


def stop() -> None:
    health.stop_sampler()
    memory_consolidation.stop_scheduler()
    if settings.enable_automation_scheduler:
        get_scheduler().stop()
