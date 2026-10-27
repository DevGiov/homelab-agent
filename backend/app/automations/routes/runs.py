"""Storico delle run e controllo di quelle in corso (pausa, ripresa, annullamento)."""
import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from app.automations.db import runs as runs_db
from app.automations.models import (
    AutomationRun,
    AutomationRunSummary,
    RunStatus,
)
from app.automations.routes.common import get_runner
from app.core.config import settings

logger = logging.getLogger("automations.routes")

router = APIRouter(prefix="/v1/automations")


@router.get("/runs", response_model=List[AutomationRunSummary])
async def list_runs(
    automation_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Elenca le run storiche."""
    runs = runs_db.list_runs(automation_id=automation_id, status=status, limit=limit, db_path=settings.automations_db_path)
    summaries = []
    for r in runs:
        summaries.append(
            AutomationRunSummary(
                run_id=r["run_id"],
                automation_id=r["automation_id"],
                version_applied=r["version_applied"],
                trigger_type=r["trigger_type"],
                status=r["status"],
                current_step_id=r.get("current_step_id"),
                is_dry_run=bool(r.get("is_dry_run")),
                is_preserved=bool(r.get("is_preserved", False)),
                is_favorite=bool(r.get("is_favorite", False)),
                artifacts_count=int(r.get("artifacts_count", 0)),
                started_at=r["started_at"],
                completed_at=r.get("completed_at"),
                total_tokens=r.get("total_tokens", 0),
                total_duration_ms=r.get("total_duration_ms", 0),
                error_message=r.get("error_message"),
            )
        )
    return summaries


class BulkDeleteRunsRequest(BaseModel):
    run_ids: Optional[List[str]] = None
    automation_id: Optional[str] = None
    failed_only: bool = False
    older_than_days: Optional[int] = None


@router.delete("/runs")
async def bulk_delete_runs(
    run_ids: Optional[List[str]] = Query(default=None),
    automation_id: Optional[str] = Query(default=None),
    failed_only: bool = Query(default=False),
    older_than_days: Optional[int] = Query(default=None),
):
    """Elimina massivamente le run storiche non preservate."""
    deleted_count = runs_db.bulk_delete_runs(
        run_ids=run_ids,
        automation_id=automation_id,
        failed_only=failed_only,
        older_than_days=older_than_days,
        db_path=settings.automations_db_path,
    )
    return {"deleted_count": deleted_count}


@router.post("/runs/delete-batch")
async def bulk_delete_runs_batch(req: BulkDeleteRunsRequest):
    """Elimina massivamente un set di run specificate per ID o per filtro."""
    deleted_count = runs_db.bulk_delete_runs(
        run_ids=req.run_ids,
        automation_id=req.automation_id,
        failed_only=req.failed_only,
        older_than_days=req.older_than_days,
        db_path=settings.automations_db_path,
    )
    return {"deleted_count": deleted_count}


@router.get("/runs/{run_id}", response_model=AutomationRun)
async def get_run_details(run_id: str):
    """Dettaglio di una singola run, step completati e artefatti."""
    r = runs_db.get_run(run_id, db_path=settings.automations_db_path)
    if not r:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' non trovata.")
    return AutomationRun(**r)


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str):
    """Elimina definitivamente una singola run e i relativi file di log/artefatto se non preservata."""
    deleted = runs_db.delete_run(run_id, db_path=settings.automations_db_path)
    if not deleted:
        raise HTTPException(
            status_code=400,
            detail=f"Impossibile eliminare la run '{run_id}': run non trovata o protetta da lucchetto (Preserved).",
        )
    return {"deleted": True, "run_id": run_id}


@router.patch("/runs/{run_id}/favorite")
async def toggle_run_favorite(run_id: str):
    """Imposta o rimuove il contrassegno preferito (Star) per la run."""
    new_val = runs_db.toggle_run_favorite(run_id, db_path=settings.automations_db_path)
    if new_val is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' non trovata.")
    return {"run_id": run_id, "is_favorite": new_val}


@router.patch("/runs/{run_id}/preserve")
async def toggle_run_preserve(run_id: str):
    """Imposta o rimuove la protezione da pulizia automatica (Lock/Preserve) per la run."""
    new_val = runs_db.toggle_run_preserve(run_id, db_path=settings.automations_db_path)
    if new_val is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' non trovata.")
    return {"run_id": run_id, "is_preserved": new_val}


@router.post("/runs/{run_id}/pause")
async def pause_run(run_id: str):
    """Mette in pausa cooperativa una run attualmente in esecuzione."""
    runner = get_runner()
    try:
        return runner.pause_run(run_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    background_tasks: BackgroundTasks,
    sync: bool = Query(default=False),
):
    """Riprende l'esecuzione di una run precedentemente messa in pausa."""
    runner = get_runner()
    try:
        if sync:
            return runner.resume_paused_run(run_id)
        else:
            run_dict = runs_db.get_run(run_id, db_path=settings.automations_db_path)
            if not run_dict:
                raise HTTPException(status_code=404, detail=f"Run '{run_id}' non trovata.")
            if run_dict["status"] != RunStatus.PAUSED.value:
                raise HTTPException(
                    status_code=400,
                    detail=f"La run '{run_id}' non è in pausa (stato attuale: {run_dict['status']}).",
                )
            runs_db.update_run_status(run_id, RunStatus.RUNNING.value, db_path=settings.automations_db_path)
            background_tasks.add_task(runner.execute_run, run_id)
            return {"resumed": True, "run_id": run_id, "status": RunStatus.RUNNING.value}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Annulla forzatamente una run."""
    r = runs_db.get_run(run_id, db_path=settings.automations_db_path)
    if not r:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' non trovata.")
    runs_db.update_run_status(run_id, RunStatus.CANCELLED.value, error_message="Annullata dall'utente.", db_path=settings.automations_db_path)
    return {"cancelled": True, "run_id": run_id}
