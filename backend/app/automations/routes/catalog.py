"""Catalogo dei template predefiniti e job registrati nello scheduler."""
import json
import logging
from pathlib import Path

from fastapi import APIRouter

logger = logging.getLogger("automations.routes")

router = APIRouter(prefix="/v1/automations")


@router.get("/templates")
async def list_templates():
    """Restituisce il catalogo dei template predefiniti."""
    templates_dir = Path(__file__).parent.parent / "templates"
    templates = []
    if templates_dir.exists():
        for file in templates_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    templates.append(json.load(f))
            except Exception as e:
                logger.error(f"Errore lettura template {file}: {e}")
    return templates


@router.get("/scheduler/jobs")
async def list_scheduled_jobs():
    """Elenca i job cron attualmente registrati nello scheduler in esecuzione."""
    try:
        from app.automations.scheduler import get_scheduler
        sched = get_scheduler()
        return {
            "running": sched.is_running,
            "jobs": sched.get_scheduled_jobs() if sched.is_running else []
        }
    except Exception as e:
        return {"running": False, "jobs": [], "error": str(e)}
