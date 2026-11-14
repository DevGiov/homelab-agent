"""Impostazioni di sicurezza dei dati.

- Host ammessi: dove `http_get` e `inspect_image` possono andare senza chiedere conferma (app.security.network).
- Classificazione dei server MCP: etichetta dei risultati e livello ammesso per gli argomenti (app.security.flows).
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import verify_api_key
from app.security import flows, network

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


class McpFlowIn(BaseModel):
    result_label: str = Field(..., description="Etichetta dei risultati: public, internal, private")
    clearance: str = Field(..., description="Etichetta più alta che gli argomenti possono avere: public, internal, private")
    result_untrusted: bool = Field(default=False, description="I risultati contengono testo scritto da altri")


@router.get("/v1/security/mcp-flows", dependencies=[Depends(verify_api_key)])
async def list_mcp_flows() -> Dict[str, Any]:
    """Classificazione per server (prefisso dei tool, es. `files` per `files__read`) o per singolo tool. Un server non
    classificato vale come il più stretto: risultati private, argomenti solo public."""
    table = flows.mcp_flow_settings()
    return {"scopes": [{"scope": scope, "result_label": s.result.key, "result_untrusted": s.untrusted,
                        "clearance": s.clearance.key} for scope, s in sorted(table.items())],
            "default": {"result_label": "private", "result_untrusted": False, "clearance": "public"}}


@router.put("/v1/security/mcp-flows/{scope}", dependencies=[Depends(verify_api_key)])
async def save_mcp_flow(scope: str, body: McpFlowIn) -> Dict[str, Any]:
    try:
        s = flows.save_mcp_flow_setting(scope, body.result_label, body.clearance, body.result_untrusted)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return {"scope": scope, "result_label": s.result.key, "result_untrusted": s.untrusted, "clearance": s.clearance.key}


@router.delete("/v1/security/mcp-flows/{scope}", dependencies=[Depends(verify_api_key)])
async def delete_mcp_flow(scope: str) -> Dict[str, Any]:
    if not flows.delete_mcp_flow_setting(scope):
        raise HTTPException(status_code=404, detail=f"Nessuna classificazione per '{scope}'.")
    return {"removed": scope}


@router.get("/v1/security/flows", dependencies=[Depends(verify_api_key)])
async def data_exit_summary(hours: int = 168) -> Dict[str, Any]:
    """Uscite di dati delle ultime `hours` ore (default una settimana), dall'audit: quante conferme chiede il controllo."""
    from datetime import datetime, timedelta, timezone

    from app.security import audit_log

    hours = max(1, min(hours, 24 * 90))
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    return {"hours": hours, **audit_log.flow_summary(since)}
