"""Integrazioni con servizi esterni e relative credenziali (cifrate a riposo)."""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings

logger = logging.getLogger("automations.routes")

router = APIRouter(prefix="/v1/automations")


@router.get("/integrations")
async def list_service_integrations(service_type: Optional[str] = Query(default=None)):
    """Elenca le integrazioni configurate (con credenziali mascherate)."""
    from app.integrations.manager import get_integration_manager
    mgr = get_integration_manager(db_path=settings.automations_db_path)
    return mgr.list_integrations(service_type=service_type, decrypt=False)


@router.get("/integrations/{integration_id}")
async def get_service_integration(integration_id: str):
    """Dettaglio di un'integrazione configurata."""
    from app.integrations.manager import get_integration_manager
    mgr = get_integration_manager(db_path=settings.automations_db_path)
    item = mgr.get_integration(integration_id, decrypt=False)
    if not item:
        raise HTTPException(status_code=404, detail=f"Integrazione '{integration_id}' non trovata.")
    return item


@router.post("/integrations", status_code=200)
async def save_service_integration(data: Dict[str, Any]):
    """Salva o aggiorna un'integrazione (con cifratura dei campi sensibili)."""
    from app.integrations.manager import get_integration_manager
    mgr = get_integration_manager(db_path=settings.automations_db_path)
    try:
        saved = mgr.save_integration(data)
        return saved
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/integrations/{integration_id}/test")
async def test_service_integration(integration_id: str):
    """Esegue un test di connettività in tempo reale per l'integrazione."""
    from app.integrations.manager import get_integration_manager
    mgr = get_integration_manager(db_path=settings.automations_db_path)
    res = mgr.test_connection(integration_id)
    return res


@router.delete("/integrations/{integration_id}")
async def delete_service_integration(integration_id: str):
    """Elimina un'integrazione."""
    from app.integrations.manager import get_integration_manager
    mgr = get_integration_manager(db_path=settings.automations_db_path)
    deleted = mgr.delete_integration(integration_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Integrazione '{integration_id}' non trovata.")
    return {"deleted": True, "id": integration_id}
