"""Definizioni delle automazioni: CRUD, trigger, webhook, circuit breaker e lancio manuale."""
import logging
import secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Query

from app.automations.db import artifacts as artifacts_db
from app.automations.db import definitions as definitions_db
from app.automations.models import (
    AutomationDefinition,
    AutomationRun,
    AutomationSummary,
    TriggerRunRequest,
    TriggerType,
)
from app.automations.routes.common import get_runner, sync_scheduler
from app.core.config import settings

logger = logging.getLogger("automations.routes")

router = APIRouter(prefix="/v1/automations")


@router.get("", response_model=List[AutomationSummary])
async def list_automations(enabled_only: bool = Query(default=False)):
    """Elenca le automazioni registrate."""
    defs = definitions_db.list_definitions(enabled_only=enabled_only, db_path=settings.automations_db_path)
    summaries = []
    for d in defs:
        wh_url = None
        for trg in d.get("triggers", []):
            if isinstance(trg, dict) and trg.get("type") == "webhook" and trg.get("webhook_path"):
                wh_url = trg["webhook_path"]
                break

        summaries.append(
            AutomationSummary(
                id=d.get("id", "unknown"),
                name=d.get("name", "Untitled"),
                description=d.get("description", ""),
                version=int(d.get("version", 1)),
                enabled=bool(d.get("enabled", True)),
                triggers_count=len(d.get("triggers", [])) if isinstance(d.get("triggers"), list) else 0,
                steps_count=len(d.get("workflow", {}).get("steps", [])) if isinstance(d.get("workflow"), dict) and isinstance(d.get("workflow", {}).get("steps"), list) else 0,
                created_by=d.get("created_by", "user"),
                source_type=d.get("source_type", "ui"),
                retention_days=d.get("retention_days"),
                last_run_status=d.get("last_run_status"),
                last_run_at=d.get("last_run_at"),
                last_artifact_id=d.get("last_artifact_id"),
                last_artifact_name=d.get("last_artifact_name"),
                last_artifact_at=d.get("last_artifact_at"),
                triggers=d.get("triggers", []) if isinstance(d.get("triggers"), list) else [],
                webhook_url=wh_url,
            )
        )
    return summaries


@router.post("", response_model=AutomationDefinition, status_code=201)
async def create_or_update_automation(automation: AutomationDefinition):
    """Crea o aggiorna una definizione di automazione."""
    saved = definitions_db.save_definition(automation.model_dump(), db_path=settings.automations_db_path)
    logger.info(f"Automazione '{automation.id}' registrata.")
    sync_scheduler()
    return AutomationDefinition(**saved)


@router.get("/{auto_id}", response_model=AutomationDefinition)
async def get_automation(auto_id: str):
    """Dettaglio completo di un'automazione."""
    d = definitions_db.get_definition(auto_id, db_path=settings.automations_db_path)
    if not d:
        raise HTTPException(status_code=404, detail=f"Automazione '{auto_id}' non trovata.")
    return AutomationDefinition(**d)


@router.put("/{auto_id}", response_model=AutomationDefinition)
async def update_automation(auto_id: str, automation: AutomationDefinition):
    """Aggiorna la definizione di un'automazione."""
    if auto_id != automation.id:
        raise HTTPException(status_code=400, detail="ID del path non coincide con ID del corpo.")
    saved = definitions_db.save_definition(automation.model_dump(), db_path=settings.automations_db_path)
    sync_scheduler()
    return AutomationDefinition(**saved)


@router.delete("/{auto_id}")
async def delete_automation(auto_id: str):
    """Elimina un'automazione e le relative schedulazioni."""
    deleted = definitions_db.delete_definition(auto_id, db_path=settings.automations_db_path)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Automazione '{auto_id}' non trovata.")
    sync_scheduler()
    return {"deleted": True, "id": auto_id}


@router.get("/{auto_id}/latest-artifact")
async def get_latest_artifact_for_automation(auto_id: str):
    """Restituisce il metadato dell'ultimo artefatto generato per l'automazione indicata."""
    art = artifacts_db.get_latest_artifact_for_automation(auto_id, db_path=settings.automations_db_path)
    if not art:
        raise HTTPException(status_code=404, detail=f"Nessun artefatto trovato per l'automazione '{auto_id}'.")
    return art


@router.get("/{auto_id}/introspect-parameters")
async def introspect_parameters(auto_id: str):
    """Introspezione automatica dei parametri e segreti richiesti dal workflow dell'automazione."""
    d = definitions_db.get_definition(auto_id, db_path=settings.automations_db_path)
    if not d:
        raise HTTPException(status_code=404, detail=f"Automazione '{auto_id}' non trovata.")
    from app.automations.introspection import introspect_automation_parameters
    return introspect_automation_parameters(d)


@router.get("/{auto_id}/circuit-breaker")
async def get_circuit_breaker_status(auto_id: str):
    """Restituisce lo stato diagnostico del circuit breaker per l'automazione."""
    from app.automations.circuit_breaker import get_circuit_breaker
    cb = get_circuit_breaker(db_path=settings.automations_db_path)
    return cb.get_status(auto_id)


@router.post("/{auto_id}/circuit-breaker/reset")
async def reset_circuit_breaker(auto_id: str):
    """Reimposta manualmente il circuit breaker a CLOSED."""
    from app.automations.circuit_breaker import get_circuit_breaker
    cb = get_circuit_breaker(db_path=settings.automations_db_path)
    cb.reset(auto_id)
    return {"status": "reset", "automation_id": auto_id, "state": "CLOSED"}


@router.patch("/{auto_id}/toggle")
async def toggle_automation_enabled(
    auto_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None),
):
    """Attiva o disattiva un'automazione (switch toggle sulla card). Sincronizza immediatamente APScheduler."""
    d = definitions_db.get_definition(auto_id, db_path=settings.automations_db_path)
    if not d:
        raise HTTPException(status_code=404, detail=f"Automazione '{auto_id}' non trovata.")

    current_enabled = bool(d.get("enabled", True))
    if payload and "enabled" in payload and payload["enabled"] is not None:
        new_enabled = bool(payload["enabled"])
    else:
        new_enabled = not current_enabled

    d["enabled"] = new_enabled
    definitions_db.save_definition(d, db_path=settings.automations_db_path)

    sync_scheduler()

    return {"id": auto_id, "enabled": new_enabled, "name": d.get("name")}


@router.put("/{auto_id}/triggers")
async def update_automation_triggers(
    auto_id: str,
    triggers: List[Dict[str, Any]] = Body(...),
):
    """Aggiorna i trigger (schedulazione temporale o webhook) di un'automazione direttamente dalla UI."""
    d = definitions_db.get_definition(auto_id, db_path=settings.automations_db_path)
    if not d:
        raise HTTPException(status_code=404, detail=f"Automazione '{auto_id}' non trovata.")

    clean_triggers = []
    for idx, t in enumerate(triggers):
        if not isinstance(t, dict):
            continue
        t = dict(t)
        t_type = str(t.get("type", "cron")).lower()
        if t_type not in {"cron", "webhook", "manual", "event"}:
            t_type = "cron"
        t["type"] = t_type
        if not t.get("id"):
            t["id"] = f"trg_{t_type}_{idx+1}"

        if t_type == "cron":
            cron_expr = t.get("cron_expression") or t.get("cron") or t.get("schedule") or "0 12 * * *"
            from apscheduler.triggers.cron import CronTrigger
            try:
                CronTrigger.from_crontab(str(cron_expr).strip())
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Espressione cron '{cron_expr}' non valida: {e}") from e
            t["cron_expression"] = str(cron_expr).strip()
            if not t.get("timezone"):
                t["timezone"] = "Europe/Rome"
        elif t_type == "webhook":
            if not t.get("webhook_token"):
                t["webhook_token"] = secrets.token_urlsafe(24)
            t["webhook_path"] = f"/v1/automations/{auto_id}/webhook/{t['webhook_token']}"

        if "enabled" not in t:
            t["enabled"] = True
        clean_triggers.append(t)

    d["triggers"] = clean_triggers
    saved = definitions_db.save_definition(d, db_path=settings.automations_db_path)

    sync_scheduler()

    return {"id": auto_id, "triggers": saved.get("triggers", [])}


@router.post("/{auto_id}/webhook-regenerate")
async def regenerate_webhook_token(auto_id: str):
    """Genera un nuovo token segreto per il trigger webhook dell'automazione."""
    d = definitions_db.get_definition(auto_id, db_path=settings.automations_db_path)
    if not d:
        raise HTTPException(status_code=404, detail=f"Automazione '{auto_id}' non trovata.")

    new_token = secrets.token_urlsafe(24)
    triggers = list(d.get("triggers", []))
    found = False
    for t in triggers:
        if isinstance(t, dict) and t.get("type") == "webhook":
            t["webhook_token"] = new_token
            t["webhook_path"] = f"/v1/automations/{auto_id}/webhook/{new_token}"
            found = True
            break

    if not found:
        triggers.append({
            "id": f"trg_webhook_{secrets.token_hex(3)}",
            "type": "webhook",
            "webhook_token": new_token,
            "webhook_path": f"/v1/automations/{auto_id}/webhook/{new_token}",
            "enabled": True,
        })

    d["triggers"] = triggers
    saved = definitions_db.save_definition(d, db_path=settings.automations_db_path)
    return {
        "id": auto_id,
        "webhook_token": new_token,
        "webhook_path": f"/v1/automations/{auto_id}/webhook/{new_token}",
        "triggers": saved.get("triggers", []),
    }


@router.post("/{auto_id}/run", response_model=AutomationRun, status_code=202)
async def trigger_run(
    auto_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[TriggerRunRequest] = None,
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
        raise HTTPException(status_code=400, detail=str(e)) from e

    if sync:
        executed_run = runner.execute_run(run.run_id)
        return executed_run
    else:
        background_tasks.add_task(runner.execute_run, run.run_id)
        return run
