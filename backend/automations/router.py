"""Endpoint REST FastAPI per Automations & Loops.

Gestisce CRUD delle definizioni, lancio manuale/dry-run,
ispezione delle run, approvazioni persistenti e catalogo template.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Security
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader

import config
from automations import db as auto_db
from automations.models import (
    AutomationDefinition,
    AutomationRun,
    AutomationRunSummary,
    AutomationSummary,
    ResolveApprovalRequest,
    RunStatus,
    TriggerRunRequest,
    TriggerType,
)
from automations.runner import AutomationRunner

logger = logging.getLogger("automations.router")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(x_api_key: Optional[str] = Security(api_key_header)):
    expected_key = config.API_SECRET_KEY.strip()
    if expected_key:
        if not x_api_key or x_api_key != expected_key:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")
    return x_api_key


router = APIRouter(prefix="/v1/automations", tags=["Automations"], dependencies=[Depends(verify_api_key)])


def get_runner() -> AutomationRunner:
    return AutomationRunner(db_path=config.AUTOMATIONS_DB_PATH)


# --- 1. Templates predefiniti (Rotta statica prioritaria) ---

@router.get("/templates")
async def list_templates():
    """Restituisce il catalogo dei template predefiniti."""
    templates_dir = Path(__file__).parent / "templates"
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
        from automations.scheduler import get_scheduler
        sched = get_scheduler()
        return {
            "running": sched.is_running,
            "jobs": sched.get_scheduled_jobs() if sched.is_running else []
        }
    except Exception as e:
        return {"running": False, "jobs": [], "error": str(e)}


# --- 1.1 Integrazioni e Credenziali Servizi (Rotte statiche prioritarie) ---

@router.get("/integrations")
async def list_service_integrations(service_type: Optional[str] = Query(default=None)):
    """Elenca le integrazioni configurate (con credenziali mascherate)."""
    from integrations.manager import get_integration_manager
    mgr = get_integration_manager(db_path=config.AUTOMATIONS_DB_PATH)
    return mgr.list_integrations(service_type=service_type, decrypt=False)


@router.get("/integrations/{integration_id}")
async def get_service_integration(integration_id: str):
    """Dettaglio di un'integrazione configurata."""
    from integrations.manager import get_integration_manager
    mgr = get_integration_manager(db_path=config.AUTOMATIONS_DB_PATH)
    item = mgr.get_integration(integration_id, decrypt=False)
    if not item:
        raise HTTPException(status_code=404, detail=f"Integrazione '{integration_id}' non trovata.")
    return item


@router.post("/integrations", status_code=200)
async def save_service_integration(data: Dict[str, Any]):
    """Salva o aggiorna un'integrazione (con cifratura dei campi sensibili)."""
    from integrations.manager import get_integration_manager
    mgr = get_integration_manager(db_path=config.AUTOMATIONS_DB_PATH)
    try:
        saved = mgr.save_integration(data)
        return saved
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/integrations/{integration_id}/test")
async def test_service_integration(integration_id: str):
    """Esegue un test di connettività in tempo reale per l'integrazione."""
    from integrations.manager import get_integration_manager
    mgr = get_integration_manager(db_path=config.AUTOMATIONS_DB_PATH)
    res = mgr.test_connection(integration_id)
    return res


@router.delete("/integrations/{integration_id}")
async def delete_service_integration(integration_id: str):
    """Elimina un'integrazione."""
    from integrations.manager import get_integration_manager
    mgr = get_integration_manager(db_path=config.AUTOMATIONS_DB_PATH)
    deleted = mgr.delete_integration(integration_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Integrazione '{integration_id}' non trovata.")
    return {"deleted": True, "id": integration_id}


# --- 2. Gestione Runs & Storico (Rotte statiche prioritarie rispetto a /{auto_id}) ---

@router.get("/runs", response_model=List[AutomationRunSummary])
async def list_runs(
    automation_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Elenca le run storiche."""
    runs = auto_db.list_runs(automation_id=automation_id, status=status, limit=limit, db_path=config.AUTOMATIONS_DB_PATH)
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


@router.delete("/runs")
async def bulk_delete_runs(
    automation_id: Optional[str] = Query(default=None),
    failed_only: bool = Query(default=False),
    older_than_days: Optional[int] = Query(default=None),
):
    """Elimina massivamente le run storiche non preservate."""
    deleted_count = auto_db.bulk_delete_runs(
        automation_id=automation_id,
        failed_only=failed_only,
        older_than_days=older_than_days,
        db_path=config.AUTOMATIONS_DB_PATH,
    )
    return {"deleted_count": deleted_count}


@router.get("/runs/{run_id}", response_model=AutomationRun)
async def get_run_details(run_id: str):
    """Dettaglio di una singola run, step completati e artefatti."""
    r = auto_db.get_run(run_id, db_path=config.AUTOMATIONS_DB_PATH)
    if not r:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' non trovata.")
    return AutomationRun(**r)


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str):
    """Elimina definitivamente una singola run e i relativi file di log/artefatto se non preservata."""
    deleted = auto_db.delete_run(run_id, db_path=config.AUTOMATIONS_DB_PATH)
    if not deleted:
        raise HTTPException(
            status_code=400,
            detail=f"Impossibile eliminare la run '{run_id}': run non trovata o protetta da lucchetto (Preserved).",
        )
    return {"deleted": True, "run_id": run_id}


@router.patch("/runs/{run_id}/favorite")
async def toggle_run_favorite(run_id: str):
    """Imposta o rimuove il contrassegno preferito (Star) per la run."""
    new_val = auto_db.toggle_run_favorite(run_id, db_path=config.AUTOMATIONS_DB_PATH)
    if new_val is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' non trovata.")
    return {"run_id": run_id, "is_favorite": new_val}


@router.patch("/runs/{run_id}/preserve")
async def toggle_run_preserve(run_id: str):
    """Imposta o rimuove la protezione da pulizia automatica (Lock/Preserve) per la run."""
    new_val = auto_db.toggle_run_preserve(run_id, db_path=config.AUTOMATIONS_DB_PATH)
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
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    sync: bool = Query(default=False),
):
    """Riprende l'esecuzione di una run precedentemente messa in pausa."""
    runner = get_runner()
    try:
        if sync:
            return runner.resume_paused_run(run_id)
        else:
            run_dict = auto_db.get_run(run_id, db_path=config.AUTOMATIONS_DB_PATH)
            if not run_dict:
                raise HTTPException(status_code=404, detail=f"Run '{run_id}' non trovata.")
            if run_dict["status"] != RunStatus.PAUSED.value:
                raise HTTPException(
                    status_code=400,
                    detail=f"La run '{run_id}' non è in pausa (stato attuale: {run_dict['status']}).",
                )
            auto_db.update_run_status(run_id, RunStatus.RUNNING.value, db_path=config.AUTOMATIONS_DB_PATH)
            background_tasks.add_task(runner.execute_run, run_id)
            return {"resumed": True, "run_id": run_id, "status": RunStatus.RUNNING.value}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Annulla forzatamente una run."""
    r = auto_db.get_run(run_id, db_path=config.AUTOMATIONS_DB_PATH)
    if not r:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' non trovata.")
    auto_db.update_run_status(run_id, RunStatus.CANCELLED.value, error_message="Annullata dall'utente.", db_path=config.AUTOMATIONS_DB_PATH)
    return {"cancelled": True, "run_id": run_id}


# --- 3. Approvazioni (Rotte statiche prioritarie) ---

@router.get("/approvals")
async def list_approvals(run_id: Optional[str] = Query(default=None)):
    """Elenca le approvazioni in sospeso per le automazioni."""
    return auto_db.list_pending_approvals(run_id=run_id, db_path=config.AUTOMATIONS_DB_PATH)


@router.post("/runs/{run_id}/approvals/{approval_id}/resolve")
async def resolve_approval(
    run_id: str,
    approval_id: str,
    body: ResolveApprovalRequest,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    sync: bool = Query(default=False),
):
    """Risolve un'approvazione pendente e riprende l'esecuzione della run."""
    runner = get_runner()
    try:
        # Verifica se si tratta di una vera run di automazione o di una richiesta originata da chat/guardrails
        run_dict = auto_db.get_run(run_id, db_path=config.AUTOMATIONS_DB_PATH)
        if not run_dict:
            # Risoluzione per approvazioni di sessione Chat (guardrails)
            import guardrails
            from registry.manager import get_registry_manager

            # 1. Aggiorna DB automazioni
            auto_db.resolve_automation_approval(
                approval_id, body.action, resolved_by=body.resolved_by, db_path=config.AUTOMATIONS_DB_PATH
            )

            # 2. Risolvi in guardrails memory/permissions
            guard_req = guardrails.resolve_approval(
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
            resolved = auto_db.resolve_automation_approval(approval_id, body.action, resolved_by=body.resolved_by, db_path=config.AUTOMATIONS_DB_PATH)
            if not resolved:
                raise HTTPException(status_code=404, detail="Approvazione non trovata o già risolta.")
            if body.action.lower() in ("approve", "approved", "true"):
                background_tasks.add_task(runner.execute_run, run_id)
            return {"status": resolved["status"], "run_id": run_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/approvals/{approval_id}")
async def delete_approval(approval_id: str):
    """Elimina definitivamente un'approvazione dal database."""
    deleted = auto_db.delete_automation_approval(approval_id, db_path=config.AUTOMATIONS_DB_PATH)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Richiesta di approvazione '{approval_id}' non trovata.")
    return {"status": "deleted", "approval_id": approval_id}


@router.post("/approvals/clear-expired")
async def clear_expired_approvals():
    """Aggiorna lo stato di tutte le approvazioni scadute a 'expired'."""
    cleared = auto_db.clear_expired_automation_approvals(db_path=config.AUTOMATIONS_DB_PATH)
    return {"cleared_count": cleared}


# --- 4. Artefatti ---

@router.get("/artifacts")
async def list_artifacts(
    automation_id: Optional[str] = Query(default=None),
    query: Optional[str] = Query(default=None),
    favorite_only: bool = Query(default=False),
    preserved_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Elenca tutti gli artefatti prodotti dalle automazioni con supporto a ricerca e filtri."""
    return auto_db.list_all_artifacts(
        automation_id=automation_id,
        query=query,
        favorite_only=favorite_only,
        preserved_only=preserved_only,
        limit=limit,
        db_path=config.AUTOMATIONS_DB_PATH,
    )


@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str):
    """Metadati dell'artefatto."""
    art = auto_db.get_artifact(artifact_id, db_path=config.AUTOMATIONS_DB_PATH)
    if not art:
        raise HTTPException(status_code=404, detail="Artefatto non trovato.")
    return art


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(artifact_id: str):
    """Download del file artefatto."""
    art = auto_db.get_artifact(artifact_id, db_path=config.AUTOMATIONS_DB_PATH)
    if not art:
        raise HTTPException(status_code=404, detail="Artefatto non trovato.")
    uri = art["storage_uri"]
    if not os.path.exists(uri):
        raise HTTPException(status_code=404, detail="File non presente sullo storage.")
    return FileResponse(uri, media_type=art.get("mime_type", "application/octet-stream"), filename=art["name"])


@router.patch("/artifacts/{artifact_id}/favorite")
async def toggle_artifact_favorite(artifact_id: str):
    """Imposta o rimuove il contrassegno preferito (Star) per l'artefatto."""
    new_val = auto_db.toggle_artifact_favorite(artifact_id, db_path=config.AUTOMATIONS_DB_PATH)
    if new_val is None:
        raise HTTPException(status_code=404, detail=f"Artefatto '{artifact_id}' non trovato.")
    return {"artifact_id": artifact_id, "is_favorite": new_val}


@router.patch("/artifacts/{artifact_id}/preserve")
async def toggle_artifact_preserve(artifact_id: str):
    """Imposta o rimuove la protezione da cancellazione (Lock/Preserve) per l'artefatto."""
    new_val = auto_db.toggle_artifact_preserve(artifact_id, db_path=config.AUTOMATIONS_DB_PATH)
    if new_val is None:
        raise HTTPException(status_code=404, detail=f"Artefatto '{artifact_id}' non trovato.")
    return {"artifact_id": artifact_id, "is_preserved": new_val}


@router.delete("/artifacts/{artifact_id}")
async def delete_artifact(artifact_id: str):
    """Elimina definitivamente un artefatto e il relativo file su disco."""
    deleted = auto_db.delete_artifact(artifact_id, db_path=config.AUTOMATIONS_DB_PATH)
    if not deleted:
        raise HTTPException(
            status_code=400,
            detail=f"Impossibile eliminare l'artefatto '{artifact_id}': non trovato o protetto da lucchetto (Preserved).",
        )
    return {"deleted": True, "artifact_id": artifact_id}


# --- 5. CRUD Definizioni Automazioni & Trigger Run ---

@router.get("", response_model=List[AutomationSummary])
async def list_automations(enabled_only: bool = Query(default=False)):
    """Elenca le automazioni registrate."""
    defs = auto_db.list_definitions(enabled_only=enabled_only, db_path=config.AUTOMATIONS_DB_PATH)
    summaries = []
    for d in defs:
        summaries.append(
            AutomationSummary(
                id=d["id"],
                name=d.get("name", "Untitled"),
                description=d.get("description", ""),
                version=int(d.get("version", 1)),
                enabled=bool(d.get("enabled", True)),
                triggers_count=len(d.get("triggers", [])),
                steps_count=len(d.get("workflow", {}).get("steps", [])),
                created_by=d.get("created_by", "user"),
                source_type=d.get("source_type", "ui"),
                retention_days=d.get("retention_days"),
                last_run_status=d.get("last_run_status"),
                last_run_at=d.get("last_run_at"),
                last_artifact_id=d.get("last_artifact_id"),
                last_artifact_name=d.get("last_artifact_name"),
                last_artifact_at=d.get("last_artifact_at"),
            )
        )
    return summaries


@router.post("", response_model=AutomationDefinition, status_code=201)
async def create_or_update_automation(automation: AutomationDefinition):
    """Crea o aggiorna una definizione di automazione."""
    saved = auto_db.save_definition(automation.model_dump(), db_path=config.AUTOMATIONS_DB_PATH)
    logger.info(f"Automazione '{automation.id}' registrata.")
    try:
        from automations.scheduler import get_scheduler
        sched = get_scheduler()
        if sched.is_running:
            sched.sync_triggers()
    except Exception as e:
        logger.debug(f"Scheduler trigger sync skipped: {e}")
    return AutomationDefinition(**saved)


@router.get("/{auto_id}", response_model=AutomationDefinition)
async def get_automation(auto_id: str):
    """Dettaglio completo di un'automazione."""
    d = auto_db.get_definition(auto_id, db_path=config.AUTOMATIONS_DB_PATH)
    if not d:
        raise HTTPException(status_code=404, detail=f"Automazione '{auto_id}' non trovata.")
    return AutomationDefinition(**d)


@router.put("/{auto_id}", response_model=AutomationDefinition)
async def update_automation(auto_id: str, automation: AutomationDefinition):
    """Aggiorna la definizione di un'automazione."""
    if auto_id != automation.id:
        raise HTTPException(status_code=400, detail="ID del path non coincide con ID del corpo.")
    saved = auto_db.save_definition(automation.model_dump(), db_path=config.AUTOMATIONS_DB_PATH)
    try:
        from automations.scheduler import get_scheduler
        sched = get_scheduler()
        if sched.is_running:
            sched.sync_triggers()
    except Exception as e:
        logger.debug(f"Scheduler trigger sync skipped: {e}")
    return AutomationDefinition(**saved)


@router.delete("/{auto_id}")
async def delete_automation(auto_id: str):
    """Elimina un'automazione e le relative schedulazioni."""
    deleted = auto_db.delete_definition(auto_id, db_path=config.AUTOMATIONS_DB_PATH)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Automazione '{auto_id}' non trovata.")
    try:
        from automations.scheduler import get_scheduler
        sched = get_scheduler()
        if sched.is_running:
            sched.sync_triggers()
    except Exception as e:
        logger.debug(f"Scheduler trigger sync skipped: {e}")
    return {"deleted": True, "id": auto_id}


@router.get("/{auto_id}/latest-artifact")
async def get_latest_artifact_for_automation(auto_id: str):
    """Restituisce il metadato dell'ultimo artefatto generato per l'automazione indicata."""
    art = auto_db.get_latest_artifact_for_automation(auto_id, db_path=config.AUTOMATIONS_DB_PATH)
    if not art:
        raise HTTPException(status_code=404, detail=f"Nessun artefatto trovato per l'automazione '{auto_id}'.")
    return art


@router.get("/{auto_id}/introspect-parameters")
async def introspect_parameters(auto_id: str):
    """Introspezione automatica dei parametri e segreti richiesti dal workflow dell'automazione."""
    d = auto_db.get_definition(auto_id, db_path=config.AUTOMATIONS_DB_PATH)
    if not d:
        raise HTTPException(status_code=404, detail=f"Automazione '{auto_id}' non trovata.")
    from automations.introspection import introspect_automation_parameters
    return introspect_automation_parameters(d)


@router.get("/{auto_id}/circuit-breaker")
async def get_circuit_breaker_status(auto_id: str):
    """Restituisce lo stato diagnostico del circuit breaker per l'automazione."""
    from automations.circuit_breaker import get_circuit_breaker
    cb = get_circuit_breaker(db_path=config.AUTOMATIONS_DB_PATH)
    return cb.get_status(auto_id)


@router.post("/{auto_id}/circuit-breaker/reset")
async def reset_circuit_breaker(auto_id: str):
    """Reimposta manualmente il circuit breaker a CLOSED."""
    from automations.circuit_breaker import get_circuit_breaker
    cb = get_circuit_breaker(db_path=config.AUTOMATIONS_DB_PATH)
    cb.reset(auto_id)
    return {"status": "reset", "automation_id": auto_id, "state": "CLOSED"}


@router.post("/{auto_id}/run", response_model=AutomationRun, status_code=202)
async def trigger_run(
    auto_id: str,
    body: Optional[TriggerRunRequest] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    sync: bool = Query(default=False, description="Esegui in modalità sincrona bloccante fino al completamento/approval"),
):
    """Avvia manualmente una run per l'automazione indicata."""
    runner = get_runner()
    req = body or TriggerRunRequest()
    try:
        run = runner.start_run(
            automation_id=auto_id,
            trigger_type=TriggerType.MANUAL,
            trigger_payload=req.trigger_payload,
            dry_run=req.dry_run,
            associated_thread_id=req.associated_thread_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if sync:
        executed_run = runner.execute_run(run.run_id)
        return executed_run
    else:
        background_tasks.add_task(runner.execute_run, run.run_id)
        return run
