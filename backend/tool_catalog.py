import logging
import time
from typing import Any, Dict, List, Optional

import requests

import config
from mcp_client import MetaMCPClient

logger = logging.getLogger("tool_catalog")

_catalog_cache: Dict[str, Any] = {"data": None, "timestamp": 0}
CACHE_TTL_SECONDS = 120  # 2 minuti per rilevare tempestivamente nuovi tool

ROLLBACK_DECLARATIONS = {
    "proxmox-mcp__allocate_ip": {
        "rollback_tool": "proxmox-mcp__release_ip",
        "rollback_args_template": {"ip": "{{ip}}"},
        "reversible": True
    },
    "allocate_ip": {
        "rollback_tool": "proxmox-mcp__release_ip",
        "rollback_args_template": {"ip": "{{ip}}"},
        "reversible": True
    },
    "proxmox-mcp__create_lxc_from_template": {
        "rollback_tool": "proxmox-mcp__stop_container",
        "rollback_args_template": {"vmid": "{{vmid}}"},
        "reversible": True
    },
    "create_lxc_from_template": {
        "rollback_tool": "proxmox-mcp__stop_container",
        "rollback_args_template": {"vmid": "{{vmid}}"},
        "reversible": True
    },
    "proxmox-mcp__add_pihole_dns_record": {
        "rollback_tool": "proxmox-mcp__delete_pihole_dns_record",
        "rollback_args_template": {"domain": "{{domain}}", "target_ip": "{{target_ip}}"},
        "reversible": True
    },
    "add_pihole_dns_record": {
        "rollback_tool": "proxmox-mcp__delete_pihole_dns_record",
        "rollback_args_template": {"domain": "{{domain}}", "target_ip": "{{target_ip}}"},
        "reversible": True
    },
    "proxmox-mcp__create_npm_proxy_host": {
        "rollback_tool": "proxmox-mcp__delete_npm_proxy_host",
        "rollback_args_template": {"domain": "{{domain}}"},
        "reversible": True
    },
    "create_npm_proxy_host": {
        "rollback_tool": "proxmox-mcp__delete_npm_proxy_host",
        "rollback_args_template": {"domain": "{{domain}}"},
        "reversible": True
    },
    "proxmox-mcp__list_containers": {"reversible": False},
    "list_containers": {"reversible": False},
    "proxmox-mcp__exec_lxc_command": {"reversible": False},
    "exec_lxc_command": {"reversible": False},
}


def get_rollback_info(tool_name: str) -> dict:
    """Recupera info di rollback per un tool, se dichiarato."""
    if not tool_name:
        return {"reversible": False}
    if tool_name in ROLLBACK_DECLARATIONS:
        return ROLLBACK_DECLARATIONS[tool_name]
    clean_name = tool_name.replace("proxmox-mcp__", "")
    if clean_name in ROLLBACK_DECLARATIONS:
        return ROLLBACK_DECLARATIONS[clean_name]
    return {"reversible": False}


def get_tool_catalog(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    Recupera il catalogo tool 100% DINAMICO da MetaMCP (Streamable HTTP / SSE / OpenAPI).
    Mantiene una cache TTL di 2 minuti ed effettua auto-refresh.
    Ogni entry: {"name": str, "description": str, "parameters": dict, "rollback_info": dict}
    """
    now = time.time()
    if not force_refresh and _catalog_cache["data"] and (now - _catalog_cache["timestamp"] < CACHE_TTL_SECONDS):
        return _catalog_cache["data"]

    tools: List[Dict[str, Any]] = []

    # 1. Recupero dinamico via MetaMCPClient (Streamable HTTP / SSE protocol)
    try:
        mcp = MetaMCPClient(config.METAMCP_URL, api_key=config.METAMCP_API_KEY)
        raw_tools = mcp.list_tools()
        if raw_tools and isinstance(raw_tools, list):
            for t in raw_tools:
                if isinstance(t, dict):
                    name = t.get("name", "")
                    desc = t.get("description", "")
                    params = t.get("inputSchema") or t.get("parameters") or {"type": "object", "properties": {}}
                    if name:
                        tools.append({
                            "name": name,
                            "description": desc,
                            "parameters": params
                        })
            if tools:
                logger.info(f"Scoperti dinamicamente {len(tools)} tool da MetaMCP via protocollo MCP")
    except Exception as e:
        logger.warning(f"Discovery dinamica MCP tools fallita: {e}")

    # 2. Fallback OpenAPI se list_tools non ha restituito tool
    if not tools:
        base_http = getattr(config, "METAMCP_URL_HTTP", "http://192.168.1.175:12008").rstrip('/')
        url = f"{base_http}/api/openapi.json"
        headers = {"Authorization": f"Bearer {config.METAMCP_API_KEY}"} if config.METAMCP_API_KEY else {}
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                openapi = res.json()
                tools = _parse_openapi_to_tools(openapi)
                if tools:
                    logger.info(f"Scoperti dinamicamente {len(tools)} tool da MetaMCP via OpenAPI")
        except Exception as e:
            logger.debug(f"Impossibile recuperare OpenAPI da MetaMCP ({e})")

    if tools:
        for t in tools:
            t["rollback_info"] = get_rollback_info(t.get("name", ""))
        from guardrails import enrich_catalog_with_metadata
        tools = enrich_catalog_with_metadata(tools)
        _catalog_cache["data"] = tools
        _catalog_cache["timestamp"] = now
        return tools

    # Resilienza: se MetaMCP è temporaneamente non raggiungibile, usa l'ultimo catalogo valido in cache
    cached = _catalog_cache["data"] or []
    for t in cached:
        t["rollback_info"] = get_rollback_info(t.get("name", ""))
    return cached


def _parse_openapi_to_tools(openapi: dict) -> List[Dict[str, Any]]:
    """Estrae {name, description, parameters} da uno schema OpenAPI."""
    tools = []
    paths = openapi.get("paths", {})
    for path, methods in paths.items():
        if isinstance(methods, dict):
            for method, spec in methods.items():
                if isinstance(spec, dict):
                    name = spec.get("operationId") or path.strip("/").replace("/", "_")
                    description = spec.get("summary") or spec.get("description") or ""
                    params_schema = spec.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
                    tools.append({
                        "name": name,
                        "description": description,
                        "parameters": params_schema
                    })
    return tools


def format_catalog_for_prompt(tools: List[Dict[str, Any]]) -> str:
    """Formatta il catalogo dinamico in modo compatto per il prompt LLM con tag [VIEW] ed [EXECUTE]."""
    from guardrails import is_view_tool
    lines = []
    for t in tools:
        name = t.get("name", "")
        params_dict = t.get("parameters", {})
        props = params_dict.get("properties", {}) if isinstance(params_dict, dict) else {}
        params_summary = ", ".join(props.keys()) if isinstance(props, dict) else ""
        badge = "[VIEW]" if is_view_tool(name) else "[EXECUTE]"
        lines.append(f"- `{name}` {badge}: {t.get('description', '')} (args: {params_summary or 'nessuno'})")
    return "\n".join(lines)


def format_dynamic_catalog_response(tools: List[Dict[str, Any]]) -> str:
    """Raggruppa e formatta dinamicamente i tool scoperti per la visualizzazione all'utente."""
    if not tools:
        return "Al momento nessun tool o server MCP è registrato o raggiungibile."

    categories: Dict[str, List[str]] = {
        "📦 Proxmox LXC Container Management": [],
        "🌐 IPAM & Rete": [],
        "🛡️ DNS (Pi-hole)": [],
        "🔀 Reverse Proxy (Nginx Proxy Manager)": [],
        "⚙️ Automazione & Service Bootstrap": [],
        "💻 Host & Command Execution": [],
        "🔍 Ricerca Web & Dati": [],
        "🧠 Memoria Semantica & Conversazionale": [],
        "🛠️ Altri Tool MCP": []
    }

    for t in tools:
        name = t.get("name", "")
        desc = t.get("description", "")
        nl = name.lower()
        tag = f"`{name}` - {desc}" if desc else f"`{name}`"

        if any(x in nl for x in ["container", "lxc", "snapshot", "template", "vmid", "resize"]):
            categories["📦 Proxmox LXC Container Management"].append(tag)
        elif any(x in nl for x in ["ip", "ipam", "reservation", "allocate"]):
            categories["🌐 IPAM & Rete"].append(tag)
        elif any(x in nl for x in ["pihole", "dns", "domain"]):
            categories["🛡️ DNS (Pi-hole)"].append(tag)
        elif any(x in nl for x in ["npm", "proxy", "host", "ssl", "cert"]):
            categories["🔀 Reverse Proxy (Nginx Proxy Manager)"].append(tag)
        elif any(x in nl for x in ["bootstrap", "service", "agy"]):
            categories["⚙️ Automazione & Service Bootstrap"].append(tag)
        elif any(x in nl for x in ["exec", "command", "storage", "log", "task", "status", "python"]):
            categories["💻 Host & Command Execution"].append(tag)
        elif any(x in nl for x in ["search", "web", "google", "ddg"]):
            categories["🔍 Ricerca Web & Dati"].append(tag)
        elif any(x in nl for x in ["memory", "fact", "recall", "knowledge"]):
            categories["🧠 Memoria Semantica & Conversazionale"].append(tag)
        else:
            categories["🛠️ Altri Tool MCP"].append(tag)

    total_count = len(tools)
    lines = [f"Ho accesso a **{total_count} tool** registrati nell'ecosistema MCP e di sistema:\n"]

    for cat_name, items in categories.items():
        if items:
            lines.append(f"### {cat_name}")
            for it in items:
                lines.append(f"- {it}")
            lines.append("")

    return "\n".join(lines).strip()
