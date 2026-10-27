"""Endpoint REST di Automations & Loops, un modulo per dominio.

I router con rotte statiche (template, integrazioni, run, approvazioni, artefatti) sono inclusi prima delle
definizioni, le cui rotte `/{auto_id}` altrimenti le catturerebbero. I webhook esterni hanno un router a parte,
senza API key: il token nel path è la credenziale.
"""
from fastapi import APIRouter, Depends

from app.api.deps import verify_api_key
from app.automations.routes import approvals, artifacts, catalog, definitions, integrations, runs, webhooks

router = APIRouter(tags=["Automations"], dependencies=[Depends(verify_api_key)])
for _domain in (catalog, integrations, runs, approvals, artifacts, definitions):
    router.include_router(_domain.router)

webhook_router = webhooks.router
