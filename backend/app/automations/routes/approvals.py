"""Approvazioni pendenti delle run e delle richieste nate in chat."""
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.automations.db import approvals as approvals_db
from app.automations.db import runs as runs_db
from app.automations.models import (
    ResolveApprovalRequest,
)
from app.automations.routes.common import get_runner
from app.core.config import settings

logger = logging.getLogger("automations.routes")

router = APIRouter(prefix="/v1/automations")


@router.get("/approvals")
async def list_approvals(run_id: Optional[str] = Query(default=None)):
    """Elenca le approvazioni in sospeso per le automazioni."""
    return approvals_db.list_pending_approvals(run_id=run_id, db_path=settings.automations_db_path)


@router.post("/runs/{run_id}/approvals/{approval_id}/resolve")
async def resolve_approval(
    run_id: str,
    approval_id: str,
    body: ResolveApprovalRequest,
    background_tasks: BackgroundTasks,
    sync: bool = Query(default=False),
):
    """Risolve un'approvazione pendente e riprende l'esecuzione della run."""
    runner = get_runner()
    try:
        # Verifica se si tratta di una vera run di automazione o di una richiesta originata da chat/guardrails
        run_dict = runs_db.get_run(run_id, db_path=settings.automations_db_path)
        if not run_dict:
            # Risoluzione per approvazioni di sessione Chat (guardrails)
            from app.registry.manager import get_registry_manager
            from app.security import approvals

            # 1. Aggiorna DB automazioni
            approvals_db.resolve_automation_approval(
                approval_id, body.action, resolved_by=body.resolved_by, db_path=settings.automations_db_path
            )

            # 2. Risolvi in guardrails memory/permissions
            approvals.resolve_approval(
                request_id=approval_id, action=body.action, resolved_by=body.resolved_by
            )

            # 3. Se approvata ed è presente nel tool manager per esecuzione immediata
            if body.action.lower() in ("approve", "approved", "true"):
                try:
                    get_registry_manager().execute_approved_tool(approval_id)
                except Exception as ex:
                    logger.warning(f"Esecuzione tool chat approvato '{approval_id}' non riuscita o già gestita: {ex}")

            norm_status = "approved" if body.action.lower() in ("approve", "approved", "true") else "denied"
            return {
                "status": norm_status,
                "run_id": run_id,
                "approval_id": approval_id,
                "type": "chat_approval",
                "message": f"Approvazione chat '{approval_id}' ({norm_status}) elaborata con successo."
            }

        if sync:
            resumed_run = runner.resume_run(
                run_id=run_id,
                approval_id=approval_id,
                action=body.action,
                resolved_by=body.resolved_by,
            )
            return {"status": resumed_run.status.value, "run": resumed_run}
        else:
            resolved = approvals_db.resolve_automation_approval(approval_id, body.action, resolved_by=body.resolved_by, db_path=settings.automations_db_path)
            if not resolved:
                raise HTTPException(status_code=404, detail="Approvazione non trovata o già risolta.")
            if body.action.lower() in ("approve", "approved", "true"):
                background_tasks.add_task(runner.execute_run, run_id)
            return {"status": resolved["status"], "run_id": run_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/approvals/{approval_id}")
async def delete_approval(approval_id: str):
    """Elimina definitivamente un'approvazione dal database."""
    deleted = approvals_db.delete_automation_approval(approval_id, db_path=settings.automations_db_path)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Richiesta di approvazione '{approval_id}' non trovata.")
    return {"status": "deleted", "approval_id": approval_id}


@router.post("/approvals/clear-expired")
async def clear_expired_approvals():
    """Aggiorna lo stato di tutte le approvazioni scadute a 'expired'."""
    cleared = approvals_db.clear_expired_automation_approvals(db_path=settings.automations_db_path)
    return {"cleared_count": cleared}
