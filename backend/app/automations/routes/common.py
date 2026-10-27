"""Dipendenze condivise dai router delle automazioni."""
import logging

from app.automations.runner import AutomationRunner
from app.core.config import settings

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
