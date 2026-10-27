"""Trigger esterni via webhook: il token nel path è la credenziale, senza API key."""
import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.automations.db import definitions as definitions_db
from app.automations.models import (
    TriggerType,
)
from app.automations.routes.common import get_runner
from app.core.config import settings

logger = logging.getLogger("automations.routes")

router = APIRouter(prefix="/v1/automations", tags=["Automations Webhooks"])


@router.post("/{auto_id}/webhook/{token}")
async def handle_automation_webhook(
    auto_id: str,
    token: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Trigger token-based per eventi esterni (Home Assistant, GitHub, Grafana, curl).
    Il token presente nel path funge da credenziale di autenticazione univoca.
    """
    d = definitions_db.get_definition(auto_id, db_path=settings.automations_db_path)
    if not d:
        raise HTTPException(status_code=404, detail=f"Automazione '{auto_id}' non trovata.")

    if not d.get("enabled", True):
        raise HTTPException(status_code=403, detail=f"L'automazione '{auto_id}' è attualmente disabilitata.")

    valid_tokens = set()
    for trg in d.get("triggers", []):
        if isinstance(trg, dict) and trg.get("type") == "webhook" and trg.get("webhook_token"):
            valid_tokens.add(trg["webhook_token"])
    if settings.api_secret_key:
        valid_tokens.add(settings.api_secret_key.strip())

    if token not in valid_tokens:
        raise HTTPException(status_code=401, detail="Token webhook non valido o non autorizzato.")

    payload_data: Dict[str, Any] = {}
    try:
        body_bytes = await request.body()
        if body_bytes:
            payload_data = json.loads(body_bytes.decode("utf-8"))
    except Exception as e:
        logger.debug(f"Parsing body JSON non riuscito: {e}")
        payload_data = {}

    run_parameters = {}
    if isinstance(payload_data, dict):
        if "inputs" in payload_data and isinstance(payload_data["inputs"], dict):
            run_parameters.update(payload_data["inputs"])
        elif "parameters" in payload_data and isinstance(payload_data["parameters"], dict):
            run_parameters.update(payload_data["parameters"])

    runner = get_runner()
    trigger_payload = {
        "source": "webhook",
        "token": token,
        "webhook_payload": payload_data,
        "inputs": run_parameters,
        **run_parameters,
        "client_host": request.client.host if request.client else None,
    }

    run = runner.start_run(
        automation_id=auto_id,
        trigger_type=TriggerType.WEBHOOK,
        trigger_payload=trigger_payload,
        dry_run=False,
    )

    background_tasks.add_task(runner.execute_run, run.run_id)
    logger.info(f"Automazione '{auto_id}' avviata via Webhook HTTP (run_id='{run.run_id}').")
    return {
        "ok": True,
        "run_id": run.run_id,
        "status": run.status.value if hasattr(run.status, "value") else str(run.status),
        "message": f"Automazione '{auto_id}' avviata con successo via webhook.",
    }
