"""Punto unico verso i server MCP: un client per server, catalogo aggregato e instradamento delle chiamate.

Il catalogo è in cache per `CACHE_TTL_SECONDS` e si ricarica subito (`invalidate`) quando cambiano server
o impostazioni dei tool, senza riavviare il backend. Se un server non risponde, restano i suoi ultimi tool noti.
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from app.mcp import store
from app.mcp.client import MCPClient
from app.mcp.store import MCPServer

logger = logging.getLogger("mcp_hub")

CACHE_TTL_SECONDS = 120


@dataclass
class ServerStatus:
    ok: bool = False
    tool_count: int = 0
    error: Optional[str] = None
    checked_at: Optional[float] = None


@dataclass
class _Discovery:
    """Tool di un server come li espone il server stesso: [{name, description, inputSchema}]."""
    tools: List[Dict[str, Any]] = field(default_factory=list)
    status: ServerStatus = field(default_factory=ServerStatus)


class MCPHub:
    def __init__(self):
        self._lock = threading.Lock()  # stato condiviso: client, discovery, route
        self._refresh_lock = threading.Lock()  # una sola ricarica alla volta; la rete gira fuori da `_lock`
        self._clients: Dict[str, Tuple[Tuple[str, str], MCPClient]] = {}
        self._discoveries: Dict[str, _Discovery] = {}
        self._routes: Dict[str, Tuple[str, str]] = {}  # nome nel catalogo -> (server, nome remoto)
        self._loaded_at = 0.0

    # --- server e client -----------------------------------------------------------

    def servers(self) -> List[MCPServer]:
        """Server predefinito (dal .env) seguito da quelli registrati dalla UI."""
        return [store.builtin_server(), *store.list_servers()]

    def _client(self, server: MCPServer) -> MCPClient:
        key = (server.url, server.token)
        with self._lock:
            cached = self._clients.get(server.id)
            if cached and cached[0] == key:
                return cached[1]
            if cached:
                cached[1].close()
            client = MCPClient(server.url, api_key=server.token)
            self._clients[server.id] = (key, client)
            return client

    def invalidate(self, server_id: Optional[str] = None) -> None:
        """Forza la ricarica del catalogo; con `server_id` chiude anche il client di quel server."""
        with self._lock:
            self._loaded_at = 0.0
            if server_id is not None:
                cached = self._clients.pop(server_id, None)
                self._discoveries.pop(server_id, None)
            else:
                cached = None
        if cached:
            cached[1].close()

    # --- discovery -----------------------------------------------------------------

    def _discover(self, server: MCPServer) -> _Discovery:
        previous = self._discoveries.get(server.id, _Discovery())
        try:
            tools = self._client(server).list_tools()
            return _Discovery(tools, ServerStatus(ok=True, tool_count=len(tools), checked_at=time.time()))
        except Exception as e:
            logger.warning(f"Discovery del server MCP '{server.id}' fallita: {e}")
            return _Discovery(previous.tools, ServerStatus(ok=False, tool_count=len(previous.tools), error=str(e), checked_at=time.time()))

    def _is_fresh(self) -> bool:
        return time.time() - self._loaded_at < CACHE_TTL_SECONDS

    def refresh(self, force: bool = False) -> None:
        """Interroga in parallelo i server attivi se la cache è scaduta (o con `force`)."""
        if not force and self._is_fresh():
            return
        with self._refresh_lock:
            # Un'altra richiesta può aver appena ricaricato mentre questa aspettava
            if not force and self._is_fresh():
                return
            servers = [s for s in self.servers() if s.enabled]
            with ThreadPoolExecutor(max_workers=max(1, len(servers))) as pool:
                results = dict(zip([s.id for s in servers], pool.map(self._discover, servers), strict=True))

            routes: Dict[str, Tuple[str, str]] = {}
            for server in servers:
                for tool in results[server.id].tools:
                    name = server.tool_name(tool["name"])
                    if name in routes:
                        logger.warning(f"Tool '{name}' esposto da più server: resta quello di '{routes[name][0]}'")
                        continue
                    routes[name] = (server.id, tool["name"])
            with self._lock:
                self._discoveries = results
                self._routes = routes
                self._loaded_at = time.time()

    def tools(self, include_disabled: bool = False, force: bool = False) -> List[Dict[str, Any]]:
        """Catalogo: [{name, description, parameters, server, enabled, risk}]; senza `include_disabled` solo i tool attivi."""
        self.refresh(force)
        settings = store.tool_settings()
        with self._lock:
            catalog = []
            for name, (server_id, remote) in self._routes.items():
                tool = next(t for t in self._discoveries[server_id].tools if t["name"] == remote)
                setting = settings.get(name, store.ToolSetting())
                if setting.enabled or include_disabled:
                    catalog.append(
                        {
                            "name": name,
                            "description": tool["description"],
                            "parameters": tool["inputSchema"],
                            "server": server_id,
                            "enabled": setting.enabled,
                            "risk": setting.risk,
                        }
                    )
            return catalog

    def status(self) -> Dict[str, ServerStatus]:
        with self._lock:
            return {sid: d.status for sid, d in self._discoveries.items()}

    def test(self, server: MCPServer) -> Dict[str, Any]:
        """Prova di connessione con un client usa e getta (anche per un server non ancora salvato)."""
        client = MCPClient(server.url, api_key=server.token)
        start = time.monotonic()
        try:
            tools = client.list_tools()
            return {"ok": True, "tool_count": len(tools), "tools": [t["name"] for t in tools],
                    "latency_ms": int((time.monotonic() - start) * 1000)}
        except Exception as e:
            return {"ok": False, "error": str(e), "latency_ms": int((time.monotonic() - start) * 1000)}
        finally:
            client.close()

    # --- esecuzione ------------------------------------------------------------------

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Esegue un tool del catalogo sul suo server. Un tool disattivato non è eseguibile."""
        route = self._routes.get(tool_name)
        if route is None:
            self.refresh(force=True)
            route = self._routes.get(tool_name)
        if route is None:
            return {"error": f"Tool MCP '{tool_name}' non trovato in nessun server attivo."}
        if not store.tool_setting(tool_name).enabled:
            return {"error": f"Il tool MCP '{tool_name}' è disattivato."}
        server_id, remote = route
        server = store.get_server(server_id)
        if server is None or not server.enabled:
            return {"error": f"Il server MCP '{server_id}' non è attivo."}
        return self._client(server).call_tool(remote, arguments)


@lru_cache(maxsize=1)
def get_mcp_hub() -> MCPHub:
    return MCPHub()
