"""Host ammessi: dove `http_get` e `inspect_image` possono andare senza chiedere conferma (app.security.network)."""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import verify_api_key
from app.security import network

router = APIRouter()


class AllowedHostIn(BaseModel):
    host: str = Field(..., description="Nome (example.com), dominio con sottodomini (*.example.com) o indirizzo IP")
    note: str = Field(default="", max_length=200)


@router.get("/v1/security/allowed-hosts", dependencies=[Depends(verify_api_key)])
async def list_allowed_hosts() -> Dict[str, Any]:
    return {"hosts": network.list_allowed_hosts(), "defaults": [h for h, _ in network.DEFAULT_ALLOWED_HOSTS]}


@router.post("/v1/security/allowed-hosts", dependencies=[Depends(verify_api_key)])
async def add_allowed_host(body: AllowedHostIn) -> Dict[str, Any]:
    try:
        return network.add_allowed_host(body.host, note=body.note, origin="user")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.delete("/v1/security/allowed-hosts/{host}", dependencies=[Depends(verify_api_key)])
async def remove_allowed_host(host: str) -> Dict[str, Any]:
    if not network.remove_allowed_host(host):
        raise HTTPException(status_code=404, detail=f"Host '{host}' non presente nella lista.")
    return {"removed": host}


@router.post("/v1/security/allowed-hosts/defaults", dependencies=[Depends(verify_api_key)])
async def restore_default_hosts() -> Dict[str, Any]:
    added = network.restore_default_hosts()
    return {"added": added, "hosts": network.list_allowed_hosts()}
