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

# Tool considerati read-only / VIEW (nessuna conferma richiesta in modalità Normal)
VIEW_TOOLS = {
    # Proxmox / Container inspection
    "list_containers", "get_container_status", "get_storage_status",
    "list_templates", "list_lxc_snapshots", "get_lxc_service_logs",
    "get_task_status", "get_task_log", "wait_for_container",
    "generate_agy_prompt_tool", "generate_host_agy_prompt", "create_service_dry_run",

    # Rete & DNS / Proxy inspection
    "list_ip_reservations", "list_pihole_dns_records", "list_npm_proxy_hosts",

    # Conoscenza, Memoria & Web
    "web_search", "recall_memory", "knowledge_search", "inspect_image",
}

SAFE_TOOLS = VIEW_TOOLS  # Retrocompatibilità

# Comandi shell diagnostici e di sola lettura (Safe-Read)
SAFE_READ_COMMAND_ROOTS = {
    "ls", "dir", "pwd", "cat", "head", "tail", "more", "less",
    "grep", "egrep", "fgrep", "awk", "wc", "diff", "cmp",
    "df", "du", "free", "uptime", "top", "htop", "vmstat", "iostat",
    "ps", "pstree", "pgrep",
    "uname", "hostname", "id", "whoami", "w", "who", "last",
    "ip", "ifconfig", "netstat", "ss", "route",
    "ping", "traceroute", "tracepath", "dig", "nslookup", "host",
    "journalctl", "dmesg",
    "git status", "git log", "git diff", "git branch", "git show",
    "python -m unittest", "pytest", "python3 -m unittest"
}

SAFE_SUBCOMMAND_PREFIXES = [
    (r"^systemctl\s+(status|is-active|is-enabled|is-failed|cat)\b", "systemctl status"),
    (r"^service\s+\S+\s+status\b", "service status"),
    (r"^pct\s+(list|status|config)\b", "pct status"),
    (r"^qm\s+(list|status|config)\b", "qm status"),
    (r"^docker\s+(ps|logs|inspect|version|info)\b", "docker inspect/logs"),
    (r"^git\s+(status|log|diff|branch|show|rev-parse)\b", "git read"),
    (r"^ip\s+(addr|a|link|route|r)\s*(show)?\b", "ip inspect"),
]

# Tool ad alto rischio / distruttivi che richiedono SEMPRE approvazione a meno che non pre-approvati
HIGH_RISK_TOOLS = {
    "exec_host_command", "stop_container", "rollback_lxc_snapshot",
    "delete_pihole_dns_record", "delete_npm_proxy_host", "release_ip",
    "run_agy_bootstrap", "create_service", "create_lxc_from_template",
    "exec_lxc_command", "start_container", "resize_lxc_disk", "update_lxc_resources",
    "allocate_ip", "add_pihole_dns_record", "create_npm_proxy_host",
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


def normalize_tool_name(tool_name: str) -> str:
    """Rimuove l'eventuale prefisso del namespace MCP (es. 'proxmox-mcp__list_containers' -> 'list_containers')."""
    if not tool_name:
        return ""
    return re.sub(r'^[a-zA-Z0-9_-]+__', '', tool_name)


def is_view_tool(tool_name: str) -> bool:
    """Verifica se il tool appartiene alla whitelist di sola lettura (VIEW)."""
    return normalize_tool_name(tool_name) in VIEW_TOOLS


def analyze_command_safety(command: str) -> Tuple[str, Optional[str]]:
    """
    Analizza un comando shell verificando ogni sub-comando (pipe, &&, ||, ;).
    Ritorna:
      - ('blocked', motivo) se rileva un pattern critico/malevolo vietato categoricamente (Tier 1)
      - ('suspicious', motivo) se rileva un comando ad alto rischio che richiede approvazione
      - ('safe', None) se il comando è standard / diagnostico
    """
    if not command or not isinstance(command, str):
        return "safe", None

    cmd_str = command.strip()

    # 1. Verifica pattern critici bloccati (Tier 1)
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


def analyze_shell_command_nature(command: str) -> Tuple[str, str, Optional[str]]:
    """
    Classifica il contenuto del comando shell in:
    - ('blocked', prefix, reason) se rileva pattern critici Tier 1
    - ('safe_read', prefix, None) se il comando è puramente diagnostico/lettura
    - ('mutating_write', prefix, reason) se il comando modifica filesystem, pacchetti, processi o servizi
    """
    if not command or not isinstance(command, str):
        return "safe_read", "", None

    cmd_str = command.strip()
    prefix = permissions.extract_command_prefix({"command": cmd_str}) or "sh"

    # 1. Verifica pattern critici Tier 1
    tier1_level, tier1_reason = analyze_command_safety(cmd_str)
    if tier1_level == "blocked":
        return "blocked", prefix, tier1_reason

    # 2. Rileva redirezioni a file (output write): >, >>, | tee
    if re.search(r"(?:>{1,2}\s*\S+|\|\s*tee\b)", cmd_str):
        return "mutating_write", prefix, "Redirezione di output o scrittura diretta su file"

    # 3. Suddivisione in sub-comandi (chained pipe, &&, ||, ;)
    sub_cmds = re.split(r"[;&|]+", cmd_str)
    for sub in sub_cmds:
        sub = sub.strip()
        if not sub:
            continue

        matched_safe = False
        for pat, _ in SAFE_SUBCOMMAND_PREFIXES:
            if re.search(pat, sub, re.IGNORECASE):
                matched_safe = True
                break

        if matched_safe:
            continue

        try:
            sub_tokens = shlex.split(sub)
        except Exception:
            sub_tokens = sub.split()

        if not sub_tokens:
            continue

        s_idx = 0
        while s_idx < len(sub_tokens) and sub_tokens[s_idx].lower() in ("sudo", "env", "nohup", "timeout"):
            s_idx += 1

        if s_idx >= len(sub_tokens):
            continue

        first_word = sub_tokens[s_idx].lower()
        if first_word in SAFE_READ_COMMAND_ROOTS:
            continue

        if len(sub_tokens) > s_idx + 1:
            two_words = f"{first_word} {sub_tokens[s_idx+1].lower()}"
            if two_words in SAFE_READ_COMMAND_ROOTS:
                continue

        return "mutating_write", prefix, f"Comando di scrittura/modifica: {first_word}"

    return "safe_read", prefix, None


def check_shell_command(command: str) -> Tuple[bool, Optional[str]]:
    """Retrocompatibilità: verifica se il comando è consentito o bloccato categoricamente."""
    level, reason = analyze_command_safety(command)
    if level in ("blocked", "suspicious"):
        return False, f"Comando bloccato dal guardrail: {reason}"
    return True, None


def classify_tool(tool_name: str, args: Optional[Dict[str, Any]] = None) -> str:
    """
    Classifica il rischio di un tool:
    - 'safe' per i tool VIEW (sola lettura / safe)
    - 'risky' per i tool EXECUTE (scrittura, esecuzione shell o mutazione)
    """
    clean_name = normalize_tool_name(tool_name)

    if clean_name in VIEW_TOOLS:
        return "safe"

    return "risky"


def get_tool_metadata(tool_name: str) -> Dict[str, Any]:
    """Restituisce i metadata completi di un tool: rischio, categoria, read-only, reversibilità."""
    from tool_catalog import get_rollback_info
    risk = classify_tool(tool_name)
    category = TOOL_CATEGORIES.get(tool_name) or TOOL_CATEGORIES.get(
        (tool_name or "").replace("proxmox-mcp__", ""), "other"
    )
    is_view = is_view_tool(tool_name)
    return {
        "risk": risk,
        "action_type": "view" if is_view else "execute",
        "category": category,
        "read_only": is_view,
        "requires_approval": not is_view,
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
    mode: Optional[str] = None,
    security_mode: str = "normal"
) -> Optional[Dict[str, Any]]:
    """
    Applica i guardrail multilivello prima dell'esecuzione di un tool in base alla modalità di rischio:

    1. TIER 1 (CATEGORICO): Pattern critici/distruttivi vietati (rm -rf /, mkfs, dd, fork bomb).
       Attivo e INVIOLABILE in TUTTE le modalità (anche 'dangerous').
    2. MODALITÀ DANGEROUS: Esecuzione autonoma di tutti i tool non bloccati da Tier 1.
    3. MODALITÀ SAFEST: Qualsiasi tool esterno Homelab/Proxmox (anche read-only) richiede conferma esplicita
       dell'utente (eccetto web_search e memoria interna).
    4. MODALITÀ NORMAL (Default):
       - Tool VIEW (sola lettura): esecuzione immediata automatica.
       - Comandi shell (exec_lxc_command, exec_host_command):
         - Safe-Read (ls, pwd, cat, df, ps, ecc.): autorizzati se il tool è stato sbloccato per la chat.
         - Mutating-Write (rm, systemctl restart, apt, ecc.): richiedono SEMPRE approvazione specifica
           per quel comando/prefisso (a meno che non sia presente nella allow-list della chat o globale).
       - Altri tool EXECUTE (create, stop, allocate_ip, ecc.): richiedono approvazione interattiva.
    """
    raw_cmd = args.get("command") or args.get("cmd") or ""
    clean_name = normalize_tool_name(tool_name)
    sec_mode = (security_mode or "normal").lower().strip()

    # 1. TIER 1 DETERMINISTICO: Verifica pattern critici (INVIOLABILE IN TUTTE LE MODALITÀ)
    if raw_cmd and isinstance(raw_cmd, str):
        level, reason = analyze_command_safety(str(raw_cmd))
        if level == "blocked":
            logger.warning(f"Guardrail TIER 1 BLOCKED [{sec_mode}]: tool '{tool_name}' comando '{raw_cmd}' -> {reason}")
            return {
                "blocked": True,
                "reason": reason,
                "command": raw_cmd,
                "tool_name": tool_name,
                "security_mode": sec_mode
            }

    # 2. MODALITÀ DANGEROUS: Bypass approvazioni per tutti i tool (Tier 1 già verificato)
    if sec_mode in ("dangerous", "bypass-dangerous", "bypass"):
        logger.info(f"Guardrail [DANGEROUS]: tool '{tool_name}' eseguito in modalità autonoma")
        return None

    # 3. MODALITÀ SAFEST: Ogni tool esterno richiede conferma (eccetto web_search e memoria)
    if sec_mode in ("safest", "safe_mode"):
        if clean_name in ("web_search", "recall_memory", "knowledge_search", "inspect_image"):
            return None

        # Se già esplicitamente pre-approvato
        if permissions.is_tool_preapproved(tool_name, args, thread_id=thread_id):
            logger.info(f"Guardrail [SAFEST]: tool '{tool_name}' pre-approvato via Permission Engine")
            return None

        reason = f"Modalità Massima Sicurezza (Safest): conferma esplicita richiesta per '{tool_name}'"
        req = create_approval_request(tool_name, args, thread_id=thread_id, mode=mode, risk_reason=reason)
        return {
            "approval_required": True,
            "request_id": req.request_id,
            "tool_name": tool_name,
            "arguments": args,
            "command_preview": req.command_preview,
            "command_prefix": req.command_prefix,
            "risk_reason": reason,
            "security_mode": "safest",
            "message": (
                f"Modalità Safest attiva: il tool '{tool_name}' richiede la tua autorizzazione esplicita. "
                f"ID richiesta: '{req.request_id}'."
            ),
        }

    # 4. MODALITÀ NORMAL (Bilanciata / Predefinita)
    # A. Tool di sola lettura (VIEW) -> Esecuzione trasparente senza interruzione
    if is_view_tool(tool_name):
        return None

    # B. Comandi Shell (exec_lxc_command, exec_host_command) -> Ispezione granulare del contenuto
    if clean_name in ("exec_lxc_command", "exec_host_command"):
        nature, extracted_prefix, cmd_reason = analyze_shell_command_nature(str(raw_cmd))
        effective_prefix = extracted_prefix or permissions.extract_command_prefix(args) or "sh"

        # B.1: Comando Safe-Read (ls, pwd, cat, df, uptime, ps, journalctl, git status, ecc.)
        if nature == "safe_read":
            # Se il tool generale è autorizzato in questo thread, o se il comando è già nella allow-list
            if permissions.is_tool_level_approved(clean_name, thread_id=thread_id) or permissions.is_command_preapproved(clean_name, effective_prefix, thread_id=thread_id):
                logger.info(f"Guardrail [NORMAL]: comando safe-read '{raw_cmd}' (prefisso='{effective_prefix}') auto-eseguito")
                return None

            reason = f"Esecuzione comando di sola lettura/diagnostica ({effective_prefix}): {str(raw_cmd)[:120]}"
            req = create_approval_request(tool_name, args, thread_id=thread_id, mode=mode, risk_reason=reason)
            return {
                "approval_required": True,
                "request_id": req.request_id,
                "tool_name": tool_name,
                "arguments": args,
                "command_preview": req.command_preview,
                "command_prefix": effective_prefix,
                "risk_reason": reason,
                "security_mode": "normal",
                "message": (
                    f"Il comando di lettura '{effective_prefix}' richiede conferma. "
                    f"ID richiesta: '{req.request_id}'."
                ),
            }

        # B.2: Comando Mutating-Write (rm, mkdir, touch, mv, chmod, systemctl restart, apt, ecc.)
        else:
            # Per comandi di modifica, serve un'autorizzazione specifica per quel comando/prefisso
            if permissions.is_command_preapproved(clean_name, effective_prefix, thread_id=thread_id):
                logger.info(f"Guardrail [NORMAL]: comando modificante '{raw_cmd}' (prefisso='{effective_prefix}') consentito da allow-list")
                return None

            reason = f"Esecuzione comando shell modificante ({effective_prefix}): {str(raw_cmd)[:120]}"
            req = create_approval_request(tool_name, args, thread_id=thread_id, mode=mode, risk_reason=reason)
            return {
                "approval_required": True,
                "request_id": req.request_id,
                "tool_name": tool_name,
                "arguments": args,
                "command_preview": req.command_preview,
                "command_prefix": effective_prefix,
                "risk_reason": reason,
                "security_mode": "normal",
                "message": (
                    f"Il comando shell modificante '{effective_prefix}' richiede autorizzazione esplicita. "
                    f"ID richiesta: '{req.request_id}'."
                ),
            }

    # C. Altri tool di mutazione infrastrutturale (create_lxc, stop_container, allocate_ip, ecc.)
    if permissions.is_tool_preapproved(tool_name, args, thread_id=thread_id):
        logger.info(f"Guardrail [NORMAL]: tool '{tool_name}' pre-approvato via Permission Engine per thread='{thread_id}'")
        return None

    if any(kw in clean_name for kw in ("delete", "rollback", "destroy", "stop")):
        reason = f"Operazione infrastrutturale potenzialmente distruttiva ({clean_name})"
    elif clean_name in ("create_lxc_from_template", "create_service", "run_agy_bootstrap", "import_existing_lxc"):
        reason = f"Provisioning nuova risorsa/container su Proxmox ({clean_name})"
    elif clean_name in ("start_container", "resize_lxc_disk", "update_lxc_resources"):
        reason = f"Modifica risorse o stato container ({clean_name})"
    elif clean_name in ("allocate_ip", "release_ip"):
        reason = f"Modifica assegnazione indirizzi IPAM ({clean_name})"
    elif clean_name in ("add_pihole_dns_record", "delete_pihole_dns_record"):
        reason = f"Modifica record DNS Pi-hole ({clean_name})"
    elif clean_name in ("create_npm_proxy_host", "delete_npm_proxy_host"):
        reason = f"Modifica rotte reverse proxy NPM ({clean_name})"
    else:
        reason = f"Modifica dello stato dell'infrastruttura tramite {clean_name}"

    req = create_approval_request(tool_name, args, thread_id=thread_id, mode=mode, risk_reason=reason)
    return {
        "approval_required": True,
        "request_id": req.request_id,
        "tool_name": tool_name,
        "arguments": args,
        "command_preview": req.command_preview,
        "command_prefix": req.command_prefix,
        "risk_reason": reason,
        "security_mode": "normal",
        "message": (
            f"Il tool '{tool_name}' richiede conferma esplicita per ragioni di sicurezza ({reason}). "
            f"ID richiesta: '{req.request_id}'."
        ),
    }
