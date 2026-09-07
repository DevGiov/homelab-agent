"""Guardrail di sicurezza per tool ad alto rischio e Human-in-the-Loop approval workflow.

Classifica i tool in base al rischio, blocca comandi malevoli/distruttivi,
si integra con il Permission Engine e gestisce le richieste di approvazione interattive.
"""

import logging
import re
import shlex
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import permissions

logger = logging.getLogger("guardrails")

# --- Pattern di Comandi Shell Vietati & ad Alto Rischio ---

CRITICAL_BLOCKED_PATTERNS = [
    # Rm ricorsivo su root o cartelle di sistema critiche
    (r"\brm\b(?=.*(?:\s|^)(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b)(?=.*(?:\s|^)(?:/+\*?|~|/(?:etc|var|usr|boot|root|bin|sbin)(?:[\s/*]|$|\S*))(?:\s|$))", "Wipe ricorsivo su cartelle critiche di sistema"),
    # Formattazione e cancellazione filesystem
    (r"\bmkfs(\.\w+)?\b", "Formattazione filesystem"),
    (r"\bwipefs\b", "Cancellazione firme filesystem"),
    # Scrittura grezza su dispositivi a blocchi
    (r"\bdd\s+.*\bof=/dev/(?:sd[a-z]|nvme\d|vd[a-z]|mapper|loop)", "Scrittura grezza (dd) su disco fisico o partizione"),
    (r">\s*/dev/(?:sd[a-z]|nvme\d|vd[a-z]|mapper)", "Redirezione distruttiva verso disco a blocchi"),
    # Fork bomb e DoS di processi
    (r":\(\)\s*\{.*\};\s*:", "Bash fork bomb"),
    (r"perl\s+-e\s+['\"].*fork.*['\"]", "Perl fork bomb"),
    (r"python[23]?\s+-c\s+['\"].*os\.fork.*['\"]", "Python fork bomb"),
    # Manomissione diretta credenziali/shadow
    (r">\s*/etc/(?:passwd|shadow|sudoers|gshadow)", "Sovrascrittura diretta credenziali o file sudoers"),
    # Neutralizzazione firewall / sicurezza host
    (r"\biptables\s+-F\b", "Flush totale regole firewall iptables"),
    (r"\bnft\s+flush\s+ruleset\b", "Flush totale regole nftables"),
    (r"\bufw\s+disable\b", "Disattivazione firewall UFW"),
    # Esecuzione remota diretta con pipe a shell
    (r"\b(?:curl|wget|fetch)\b[^\n|;&]+?\|\s*(?:ba|z)?sh\b", "Download ed esecuzione arbitraria remota pipe to shell"),
    # Comandi offuscati base64 pipe a shell
    (r"\bbase64\s+-(?:d|-decode)\b[^\n|;&]+?\|\s*(?:ba|z)?sh\b", "Esecuzione offuscata base64 pipe to shell"),
]

SUSPICIOUS_HIGH_RISK_PATTERNS = [
    (r"\brm\b(?=.*(?:\s|^)(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b)", "Cancellazione ricorsiva di file o directory"),
    (r"\b(shutdown|reboot|poweroff|halt|init\s+[06])\b", "Spegnimento o riavvio del sistema"),
    (r"\bsystemctl\s+(?:stop|restart|reload|disable|mask)\b", "Interruzione o modifica servizio di sistema"),
    (r"\bapt(?:-get)?\s+(?:remove|purge|autoremove)\b", "Rimozione o disinstallazione pacchetti software"),
    (r"\bpct\s+(?:destroy|stop)\b", "Arresto o distruzione container Proxmox"),
    (r"\bqm\s+(?:destroy|stop)\b", "Arresto o distruzione macchina virtuale Proxmox"),
    (r"\bip\s+link\s+set\b.*down", "Disattivazione interfaccia di rete"),
    (r"\bchmod\s+-R?\s*(?:777|000)\b", "Modifica ricorsiva estrema permessi"),
    (r"\bchown\s+-R\b", "Modifica ricorsiva proprietario file"),
    (r"\bpkill\s+-9\b|\bkillall\s+-9\b", "Terminazione forzata di massa processi"),
]

# Tool considerati read-only / sicuri (nessuna conferma richiesta)
SAFE_TOOLS = {
    "list_containers", "get_container_status", "get_lxc_service_logs",
    "list_pihole_dns_records", "list_npm_proxy_hosts", "list_lxc_snapshots",
    "list_ip_reservations", "list_templates", "get_storage_status",
    "get_task_status", "get_task_log", "web_search",
    "recall_memory", "knowledge_search", "inspect_image",
}

# Tool ad alto rischio / distruttivi che richiedono SEMPRE approvazione a meno che non pre-approvati
HIGH_RISK_TOOLS = {
    "exec_host_command", "stop_container", "rollback_lxc_snapshot",
    "delete_pihole_dns_record", "delete_npm_proxy_host", "release_ip",
    "run_agy_bootstrap", "create_service",
}

TOOL_CATEGORIES = {
    "list_containers": "proxmox.read", "get_container_status": "proxmox.read",
    "list_templates": "proxmox.read", "list_lxc_snapshots": "proxmox.read",
    "create_lxc_from_template": "proxmox.write", "start_container": "proxmox.write",
    "stop_container": "proxmox.destructive", "rollback_lxc_snapshot": "proxmox.destructive",
    "resize_lxc_disk": "proxmox.write", "update_lxc_resources": "proxmox.write",
    "allocate_ip": "ipam.write", "release_ip": "ipam.destructive",
    "add_pihole_dns_record": "dns.write", "delete_pihole_dns_record": "dns.destructive",
    "create_npm_proxy_host": "proxy.write", "delete_npm_proxy_host": "proxy.destructive",
    "exec_lxc_command": "host.exec", "exec_host_command": "host.exec.dangerous",
    "run_agy_bootstrap": "provisioning", "create_service": "provisioning",
    "python_interpreter": "code.sandboxed", "web_search": "web.read",
    "recall_memory": "memory.read", "knowledge_search": "kb.read", "inspect_image": "vision.read",
}


def analyze_command_safety(command: str) -> Tuple[str, Optional[str]]:
    """
    Analizza un comando shell verificando ogni sub-comando (pipe, &&, ||, ;).
    Ritorna:
      - ('blocked', motivo) se rileva un pattern critico/malevolo vietato categoricamente
      - ('suspicious', motivo) se rileva un comando ad alto rischio che richiede approvazione
      - ('safe', None) se il comando è standard / diagnostico
    """
    if not command or not isinstance(command, str):
        return "safe", None

    cmd_str = command.strip()

    # 1. Verifica pattern critici bloccati
    for pat, desc in CRITICAL_BLOCKED_PATTERNS:
        if re.search(pat, cmd_str, re.IGNORECASE):
            return "blocked", f"Comando bloccato/vietato categoricamente dal guardrail: {desc}"

    # 2. Suddivisione ed analisi subcomandi per pattern ad alto rischio
    sub_cmds = re.split(r"[;&|]+", cmd_str)
    for sub in sub_cmds:
        sub = sub.strip()
        if not sub:
            continue
        for pat, desc in SUSPICIOUS_HIGH_RISK_PATTERNS:
            if re.search(pat, sub, re.IGNORECASE):
                return "suspicious", f"Comando ad alto rischio: {desc}"

    return "safe", None


def check_shell_command(command: str) -> Tuple[bool, Optional[str]]:
    """Retrocompatibilità: verifica se il comando è consentito o bloccato categoricamente."""
    level, reason = analyze_command_safety(command)
    if level in ("blocked", "suspicious"):
        return False, f"Comando bloccato dal guardrail: {reason}"
    return True, None


def classify_tool(tool_name: str, args: Optional[Dict[str, Any]] = None) -> str:
    """
    Classifica il rischio di un tool: 'safe', 'risky' o 'write'.
    Per 'exec_lxc_command', la classificazione dipende dinamicamente dal comando fornito.
    """
    if tool_name in SAFE_TOOLS:
        return "safe"

    if tool_name == "exec_host_command":
        return "risky"

    if tool_name == "exec_lxc_command":
        if args and isinstance(args, dict):
            raw_cmd = args.get("command") or args.get("cmd") or ""
            level, _ = analyze_command_safety(str(raw_cmd))
            if level in ("blocked", "suspicious"):
                return "risky"
            return "safe"
        return "risky"

    if tool_name in HIGH_RISK_TOOLS:
        return "risky"

    lowered = (tool_name or "").lower()
    for pat in (r"delete", r"remove", r"rollback", r"stop", r"destroy"):
        if re.search(pat, lowered):
            return "risky"

    return "write"


def get_tool_metadata(tool_name: str) -> Dict[str, Any]:
    """Restituisce i metadata completi di un tool: rischio, categoria, read-only, reversibilità."""
    from tool_catalog import get_rollback_info
    risk = classify_tool(tool_name)
    category = TOOL_CATEGORIES.get(tool_name) or TOOL_CATEGORIES.get(
        (tool_name or "").replace("proxmox-mcp__", ""), "other"
    )
    return {
        "risk": risk,
        "category": category,
        "read_only": risk == "safe",
        "requires_approval": risk == "risky",
        "reversible": get_rollback_info(tool_name).get("reversible", False),
    }


def enrich_catalog_with_metadata(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggiunge i metadata di rischio a ogni entry del catalogo tool."""
    for t in tools:
        t["metadata"] = get_tool_metadata(t.get("name", ""))
    return tools


# --- Approval Workflow Interattivo & Memoria Richieste ---

class ApprovalRequest:
    __slots__ = (
        "request_id", "tool_name", "arguments", "thread_id", "mode",
        "created_at", "status", "resolved_by", "command_preview",
        "risk_reason", "command_prefix"
    )

    def __init__(
        self,
        request_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        thread_id: Optional[str],
        mode: Optional[str],
        command_preview: Optional[str] = None,
        risk_reason: Optional[str] = None,
        command_prefix: Optional[str] = None
    ):
        self.request_id = request_id
        self.tool_name = tool_name
        self.arguments = arguments
        self.thread_id = thread_id
        self.mode = mode
        self.created_at = time.time()
        self.status = "pending"  # pending | approved | denied | expired
        self.resolved_by: Optional[str] = None
        self.command_preview = command_preview
        self.risk_reason = risk_reason
        self.command_prefix = command_prefix


_APPROVALS: Dict[str, ApprovalRequest] = {}
_approval_lock = threading.Lock()
APPROVAL_TTL_SECONDS = 300  # 5 minuti di validità


def _next_request_id() -> str:
    import uuid
    return f"apr_{uuid.uuid4().hex[:12]}"


def create_approval_request(
    tool_name: str,
    arguments: Dict[str, Any],
    thread_id: Optional[str] = None,
    mode: Optional[str] = None,
    risk_reason: Optional[str] = None
) -> ApprovalRequest:
    """Crea e registra una nuova richiesta di approvazione interattiva."""
    cmd_preview = arguments.get("command") or arguments.get("cmd") or None
    cmd_prefix = permissions.extract_command_prefix(arguments)

    req = ApprovalRequest(
        _next_request_id(),
        tool_name,
        arguments,
        thread_id,
        mode,
        command_preview=str(cmd_preview) if cmd_preview else None,
        risk_reason=risk_reason,
        command_prefix=cmd_prefix
    )

    with _approval_lock:
        now = time.time()
        expired = [k for k, v in _APPROVALS.items()
                   if v.status == "pending" and now - v.created_at > APPROVAL_TTL_SECONDS]
        for k in expired:
            _APPROVALS[k].status = "expired"
        _APPROVALS[req.request_id] = req

    logger.info(f"Approval request creata: {req.request_id} per tool '{tool_name}' ({risk_reason})")
    return req


def resolve_approval(
    request_id: str,
    action: Optional[str] = None,
    resolved_by: str = "user",
    approved: Optional[bool] = None
) -> Optional[ApprovalRequest]:
    """
    Approva o nega una richiesta pendente applicando lo scope desiderato:
    - 'deny' / False: rifiuta l'azione
    - 'approve' / True: approva solo per questa singola volta (one-time)
    - 'approve_thread': approva per tutta la chat corrente (session-scope)
    - 'approve_always': approva in modo persistente nel database (global-scope)
    """
    if action is None:
        if approved is False:
            action = "deny"
        else:
            action = "approve"

    with _approval_lock:
        req = _APPROVALS.get(request_id)
        if not req or req.status != "pending":
            return None
        if time.time() - req.created_at > APPROVAL_TTL_SECONDS:
            req.status = "expired"
            return req

        normalized_action = str(action).lower().strip()
        if normalized_action in ("deny", "false", "refuse"):
            req.status = "denied"
            req.resolved_by = resolved_by
            logger.info(f"Approval {request_id}: NEGATA da {resolved_by}")
            return req

        # Azioni di approvazione
        req.status = "approved"
        req.resolved_by = resolved_by

        if normalized_action == "approve_thread" and req.thread_id:
            permissions.grant_permission(req.tool_name, "thread", thread_id=req.thread_id, command_prefix=req.command_prefix, created_by=resolved_by)
            logger.info(f"Approval {request_id}: APPROVATA per l'intero thread '{req.thread_id}'")
        elif normalized_action in ("approve_always", "always"):
            permissions.grant_permission(req.tool_name, "always", thread_id=req.thread_id, command_prefix=req.command_prefix, created_by=resolved_by)
            logger.info(f"Approval {request_id}: APPROVATA SEMPRE (persistente)")
        else:
            logger.info(f"Approval {request_id}: APPROVATA (singola esecuzione)")

        return req


def get_pending_approvals(thread_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Elenca le richieste pendenti includendo dettagli sul comando e sul motivo di sicurezza."""
    with _approval_lock:
        now = time.time()
        result = []
        for req in _APPROVALS.values():
            if req.status != "pending":
                continue
            if now - req.created_at > APPROVAL_TTL_SECONDS:
                req.status = "expired"
                continue
            if thread_id and req.thread_id != thread_id:
                continue
            result.append({
                "request_id": req.request_id,
                "tool_name": req.tool_name,
                "arguments": req.arguments,
                "thread_id": req.thread_id,
                "mode": req.mode,
                "command_preview": req.command_preview,
                "risk_reason": req.risk_reason,
                "command_prefix": req.command_prefix,
                "age_seconds": int(now - req.created_at),
            })
        return result


def enforce_guardrails(
    tool_name: str,
    args: Dict[str, Any],
    *,
    thread_id: Optional[str] = None,
    mode: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Applica i guardrail prima dell'esecuzione di un tool.

    Verifiche:
    1. Pattern critici/malevoli nei comandi shell -> BLOCCA CATEGORICAMENTE (nessun bypass).
    2. Verifica pre-approvazione tramite Permission Engine (session/always) -> SE PRE-APPROVATO, AUTORIZZA SUBITO.
    3. Tool rischiosi o comandi shell sospetti -> CREA RICHIESTA DI APPROVAZIONE INTERATTIVA (UI HITL).
    """
    raw_cmd = args.get("command") or args.get("cmd") or ""

    # 1. Analisi di sicurezza automatica sul comando shell
    if raw_cmd and isinstance(raw_cmd, str):
        level, reason = analyze_command_safety(str(raw_cmd))
        if level == "blocked":
            logger.warning(f"Guardrail CRITICAL BLOCKED: tool '{tool_name}' con comando '{raw_cmd}' -> {reason}")
            return {
                "blocked": True,
                "reason": reason,
                "command": raw_cmd,
                "tool_name": tool_name
            }

    # 2. Controllo pre-approvazione (Sessione o Globale)
    if permissions.is_tool_preapproved(tool_name, args, thread_id=thread_id):
        logger.info(f"Guardrail: tool '{tool_name}' pre-approvato via Permission Engine per thread='{thread_id}'")
        return None

    # 3. Classificazione rischio
    risk = classify_tool(tool_name, args)

    if risk == "risky":
        # Motivo contestuale
        if tool_name in ("exec_lxc_command", "exec_host_command"):
            reason = f"Esecuzione comando shell su infrastruttura: {str(raw_cmd)[:120]}"
        elif "delete" in tool_name or "rollback" in tool_name or "destroy" in tool_name or "stop" in tool_name:
            reason = f"Operazione infrastrutturale potenzialmente distruttiva ({tool_name})"
        else:
            reason = f"Modifica dello stato dell'infrastruttura tramite {tool_name}"

        req = create_approval_request(tool_name, args, thread_id=thread_id, mode=mode, risk_reason=reason)
        return {
            "approval_required": True,
            "request_id": req.request_id,
            "tool_name": tool_name,
            "arguments": args,
            "command_preview": req.command_preview,
            "command_prefix": req.command_prefix,
            "risk_reason": reason,
            "message": (
                f"Il tool '{tool_name}' richiede conferma esplicita per ragioni di sicurezza ({reason}). "
                f"ID richiesta: '{req.request_id}'."
            ),
        }

    return None
