"""Server MCP registrati e impostazioni per tool: modifiche applicate subito, senza riavvio."""
from dataclasses import asdict
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import verify_api_key
from app.mcp import store
from app.mcp.hub import ServerStatus, get_mcp_hub
from app.mcp.store import MCPServer, ToolSetting
from app.security.policy import is_view_tool

router = APIRouter(prefix="/v1/mcp", tags=["mcp"], dependencies=[Depends(verify_api_key)])


class ServerFields(BaseModel):
    name: str = Field(min_length=1)
    url: str = Field(pattern=r"^https?://")
    enabled: bool = True


class ServerCreate(ServerFields):
    id: str
    token: str = ""


class ServerUpdate(ServerFields):
    # None: token invariato; stringa vuota: token rimosso
    token: Optional[str] = None


class ServerTest(BaseModel):
    url: str = Field(pattern=r"^https?://")
    token: str = ""


class ToolSettingUpdate(BaseModel):
    enabled: bool
    risk: Literal["auto", "view", "confirm", "blocked"]


def _server_view(server: MCPServer, status: Optional[ServerStatus]) -> dict:
    return {
        "id": server.id,
        "name": server.name,
        "url": server.url,
        "enabled": server.enabled,
        "builtin": server.builtin,
        "has_token": bool(server.token),
        "status": asdict(status) if status else None,
    }


def _editable_server(server_id: str) -> MCPServer:
    if server_id == store.BUILTIN_SERVER_ID:
        raise HTTPException(400, "Il server predefinito si configura dal .env (METAMCP_URL, METAMCP_API_KEY).")
    server = store.get_server(server_id)
    if server is None:
        raise HTTPException(404, f"Server MCP '{server_id}' non trovato.")
    return server


def _save_and_reload(server: MCPServer) -> dict:
    try:
        store.save_server(server)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    hub = get_mcp_hub()
    hub.invalidate(server.id)
    hub.refresh(force=True)
    return _server_view(server, hub.status().get(server.id))


@router.get("/servers")
def list_servers():
    hub = get_mcp_hub()
    hub.refresh()
    statuses = hub.status()
    return [_server_view(s, statuses.get(s.id)) for s in hub.servers()]


@router.post("/servers", status_code=201)
def create_server(body: ServerCreate):
    hub = get_mcp_hub()
    if any(s.id == body.id for s in hub.servers()):
        raise HTTPException(409, f"Esiste già un server con id '{body.id}'.")
    # L'id diventa il prefisso dei tool: non deve coincidere con un namespace già nel catalogo
    if any(t["name"].startswith(f"{body.id}__") for t in hub.tools(include_disabled=True)):
        raise HTTPException(409, f"L'id '{body.id}' è già il prefisso di tool esistenti (es. un server dentro MetaMCP).")
    return _save_and_reload(MCPServer(id=body.id, name=body.name, url=body.url, token=body.token, enabled=body.enabled))


@router.put("/servers/{server_id}")
def update_server(server_id: str, body: ServerUpdate):
    current = _editable_server(server_id)
    token = current.token if body.token is None else body.token
    return _save_and_reload(MCPServer(id=server_id, name=body.name, url=body.url, token=token, enabled=body.enabled))


@router.delete("/servers/{server_id}")
def delete_server(server_id: str):
    _editable_server(server_id)
    store.delete_server(server_id)
    get_mcp_hub().invalidate(server_id)
    return {"deleted": server_id}


@router.post("/servers/test")
def test_new_server(body: ServerTest):
    """Prova di connessione prima del salvataggio."""
    return get_mcp_hub().test(MCPServer(id="test", name="test", url=body.url, token=body.token))


@router.post("/servers/{server_id}/test")
def test_server(server_id: str):
    server = store.get_server(server_id)
    if server is None:
        raise HTTPException(404, f"Server MCP '{server_id}' non trovato.")
    return get_mcp_hub().test(server)


@router.get("/tools")
def list_tools(refresh: bool = False):
    """Tutti i tool MCP, anche quelli disattivati, con impostazioni e accesso effettivo (lettura o esecuzione)."""
    tools = get_mcp_hub().tools(include_disabled=True, force=refresh)
    return [
        {
            "name": t["name"],
            "server": t["server"],
            "description": t["description"],
            "enabled": t["enabled"],
            "risk": t["risk"],
            "access": "view" if is_view_tool(t["name"]) else "execute",
        }
        for t in tools
    ]


@router.put("/tools/{tool_name}")
def update_tool(tool_name: str, body: ToolSettingUpdate):
    if not any(t["name"] == tool_name for t in get_mcp_hub().tools(include_disabled=True)):
        raise HTTPException(404, f"Tool MCP '{tool_name}' non trovato.")
    store.save_tool_setting(tool_name, ToolSetting(enabled=body.enabled, risk=body.risk))
    return {"name": tool_name, **asdict(store.tool_setting(tool_name)), "access": "view" if is_view_tool(tool_name) else "execute"}


@router.post("/reload")
def reload_servers():
    """Ricarica subito i cataloghi di tutti i server."""
    hub = get_mcp_hub()
    hub.invalidate()
    hub.refresh(force=True)
    return {sid: asdict(status) for sid, status in hub.status().items()}
