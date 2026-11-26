"""Dipendenze condivise dai router delle automazioni."""
import logging
from typing import Optional

from fastapi import HTTPException

from app.automations.runner import AutomationRunner
from app.core.config import settings
from app.llm import providers

logger = logging.getLogger("automations.routes")


def get_runner() -> AutomationRunner:
    return AutomationRunner(db_path=settings.automations_db_path)


def sync_scheduler():
    """Riallinea i job dello scheduler dopo una modifica a definizioni o trigger."""
    try:
        from app.automations.scheduler import get_scheduler
        sched = get_scheduler()
        if sched.is_running:
            sched.sync_triggers()
    except Exception as e:
        logger.debug(f"Scheduler trigger sync skipped: {e}")


def check_provider(provider: Optional[str]) -> None:
    """Il provider di un salvataggio deve esistere: 422 altrimenti (nessun ripiego silenzioso su un altro)."""
    try:
        providers.require_known_provider(provider)
    except providers.ProviderUnavailableError as e:
        raise HTTPException(status_code=422, detail={"code": "unknown_provider", "message": str(e)}) from e
