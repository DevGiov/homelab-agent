from typing import Any, Dict, List

from app.mcp.hub import get_mcp_hub

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
    """Tool MCP attivi di tutti i server, con info di rollback e metadata di rischio.

    Ogni entry: {"name", "description", "parameters", "server", "enabled", "risk", "rollback_info", "metadata"}.
    """
    from app.security.policy import enrich_catalog_with_metadata

    tools = get_mcp_hub().tools(force=force_refresh)
    for t in tools:
        t["rollback_info"] = get_rollback_info(t["name"])
    return enrich_catalog_with_metadata(tools)


def format_catalog_for_prompt(tools: List[Dict[str, Any]]) -> str:
    """Formatta il catalogo dinamico in modo compatto per il prompt LLM con tag [VIEW] ed [EXECUTE]."""
    from app.security.policy import is_view_tool
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


def format_available_tools_catalog() -> str:
    """Catalogo dei tool raggiungibili (server MCP, web, code, memory) formattato per l'utente."""
    from app.registry.manager import get_registry_manager
    all_tools = get_registry_manager().get_tools_for_mode(["mcp", "web", "code", "memory"])
    return format_dynamic_catalog_response(all_tools)
