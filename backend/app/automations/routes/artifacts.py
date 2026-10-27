"""Artefatti prodotti dalle run: ricerca, download, preferiti e protezione."""
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.automations.db import artifacts as artifacts_db
from app.core.config import settings

logger = logging.getLogger("automations.routes")

router = APIRouter(prefix="/v1/automations")


@router.get("/artifacts")
async def list_artifacts(
    automation_id: Optional[str] = Query(default=None),
    query: Optional[str] = Query(default=None),
    favorite_only: bool = Query(default=False),
    preserved_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Elenca tutti gli artefatti prodotti dalle automazioni con supporto a ricerca e filtri."""
    return artifacts_db.list_all_artifacts(
        automation_id=automation_id,
        query=query,
        favorite_only=favorite_only,
        preserved_only=preserved_only,
        limit=limit,
        db_path=settings.automations_db_path,
    )


@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str):
    """Metadati dell'artefatto."""
    art = artifacts_db.get_artifact(artifact_id, db_path=settings.automations_db_path)
    if not art:
        raise HTTPException(status_code=404, detail="Artefatto non trovato.")
    return art


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(artifact_id: str):
    """Download del file artefatto."""
    art = artifacts_db.get_artifact(artifact_id, db_path=settings.automations_db_path)
    if not art:
        raise HTTPException(status_code=404, detail="Artefatto non trovato.")
    uri = art["storage_uri"]
    if not os.path.exists(uri):
        raise HTTPException(status_code=404, detail="File non presente sullo storage.")
    return FileResponse(uri, media_type=art.get("mime_type", "application/octet-stream"), filename=art["name"])


@router.patch("/artifacts/{artifact_id}/favorite")
async def toggle_artifact_favorite(artifact_id: str):
    """Imposta o rimuove il contrassegno preferito (Star) per l'artefatto."""
    new_val = artifacts_db.toggle_artifact_favorite(artifact_id, db_path=settings.automations_db_path)
    if new_val is None:
        raise HTTPException(status_code=404, detail=f"Artefatto '{artifact_id}' non trovato.")
    return {"artifact_id": artifact_id, "is_favorite": new_val}


@router.patch("/artifacts/{artifact_id}/preserve")
async def toggle_artifact_preserve(artifact_id: str):
    """Imposta o rimuove la protezione da cancellazione (Lock/Preserve) per l'artefatto."""
    new_val = artifacts_db.toggle_artifact_preserve(artifact_id, db_path=settings.automations_db_path)
    if new_val is None:
        raise HTTPException(status_code=404, detail=f"Artefatto '{artifact_id}' non trovato.")
    return {"artifact_id": artifact_id, "is_preserved": new_val}


@router.delete("/artifacts/{artifact_id}")
async def delete_artifact(artifact_id: str):
    """Elimina definitivamente un artefatto e il relativo file su disco."""
    deleted = artifacts_db.delete_artifact(artifact_id, db_path=settings.automations_db_path)
    if not deleted:
        raise HTTPException(
            status_code=400,
            detail=f"Impossibile eliminare l'artefatto '{artifact_id}': non trovato o protetto da lucchetto (Preserved).",
        )
    return {"deleted": True, "artifact_id": artifact_id}
