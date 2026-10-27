"""Richieste di approvazione Human-in-the-Loop: creazione, risoluzione con scope, elenco delle pendenti.

Le richieste vivono in memoria (con scadenza) e sono specchiate su automations.db, così una richiesta
sopravvive al riavvio del backend. Le approvazioni "per questa chat" / "sempre" diventano permessi
del Permission Engine. Qui stanno anche le approvazioni emerse a runtime (`ApprovalRequired`), quando
il bisogno di conferma si scopre durante l'esecuzione del tool.
"""

import contextvars
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.automations.db import approvals as approvals_db
from app.security import permissions

logger = logging.getLogger("approvals")

APPROVAL_TTL_SECONDS = 300  # 5 minuti di validità


@dataclass
class ApprovalRequest:
    request_id: str
    tool_name: str
    arguments: Dict[str, Any]
    thread_id: Optional[str]
    mode: Optional[str]
    command_preview: Optional[str] = None
    risk_reason: Optional[str] = None
    command_prefix: Optional[str] = None
    task: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending | approved | denied | expired
    resolved_by: Optional[str] = None


_APPROVALS: Dict[str, ApprovalRequest] = {}
_approval_lock = threading.Lock()


def create_approval_request(
    tool_name: str,
    arguments: Dict[str, Any],
    thread_id: Optional[str] = None,
    mode: Optional[str] = None,
    risk_reason: Optional[str] = None,
    task: Optional[str] = None,
    command_preview: Optional[str] = None,
    command_prefix: Optional[str] = None,
) -> ApprovalRequest:
    """Crea e registra una nuova richiesta di approvazione interattiva."""
    cmd_preview = command_preview or arguments.get("command") or arguments.get("cmd") or None

    req = ApprovalRequest(
        request_id=f"apr_{uuid.uuid4().hex[:12]}",
        tool_name=tool_name,
        arguments=arguments,
        thread_id=thread_id,
        mode=mode,
        command_preview=str(cmd_preview) if cmd_preview else None,
        risk_reason=risk_reason,
        command_prefix=command_prefix or permissions.extract_command_prefix(arguments),
        task=task,
    )

    with _approval_lock:
        now = time.time()
        expired = [k for k, v in _APPROVALS.items()
                   if v.status == "pending" and now - v.created_at > APPROVAL_TTL_SECONDS]
        for k in expired:
            _APPROVALS[k].status = "expired"
        _APPROVALS[req.request_id] = req

    # Sincronizzazione persistente su automations.db
    try:
        approvals_db.create_automation_approval({
            "request_id": req.request_id,
            "run_id": thread_id or "chat_session",
            "tool_name": tool_name,
            "arguments": arguments,
            "command_preview": req.command_preview,
            "command_prefix": req.command_prefix,
            "risk_reason": risk_reason,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": datetime.fromtimestamp(now + APPROVAL_TTL_SECONDS, tz=timezone.utc).isoformat()
        })
    except Exception as e:
        logger.debug(f"Salvataggio approval su DB automazioni non eseguito: {e}")

    logger.info(f"Approval request creata: {req.request_id} per tool '{tool_name}' ({risk_reason})")
    return req


def get_approval_request(request_id: str) -> Optional[ApprovalRequest]:
    with _approval_lock:
        return _APPROVALS.get(request_id)


def approval_response(req: ApprovalRequest, message: str, *, security_mode: Optional[str] = None,
                      command_prefix: Optional[str] = None) -> Dict[str, Any]:
    """Risultato del tool che chiede conferma: l'agent loop chiude il turno e la UI mostra la richiesta."""
    response = {
        "approval_required": True,
        "request_id": req.request_id,
        "tool_name": req.tool_name,
        "arguments": req.arguments,
        "command_preview": req.command_preview,
        "command_prefix": command_prefix or req.command_prefix,
        "risk_reason": req.risk_reason,
        "message": f"{message} ID richiesta: '{req.request_id}'.",
    }
    if security_mode:
        response["security_mode"] = security_mode
    return response


# --- Approvazioni emerse a runtime (il bisogno di conferma si scopre durante l'esecuzione) ---

# Esecuzione del codice Python fuori dalla sandbox Firecracker, nel container backend
LOCAL_CODE_FALLBACK = "local-fallback"

_approved_capability: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("approved_capability", default=None)


class ApprovalRequired(Exception):
    """Sollevata da un registry quando un'esecuzione richiede una capability non ancora approvata.

    La capability viene registrata come `command_prefix` della richiesta: così le scelte
    "per questa chat" / "sempre" diventano permessi granulari distinti dall'approvazione del tool.
    """

    def __init__(self, capability: str, reason: str, preview: Optional[str] = None):
        super().__init__(reason)
        self.capability = capability
        self.reason = reason
        self.preview = preview


def is_capability_approved(capability: str) -> bool:
    """True solo dentro un'esecuzione esplicitamente autorizzata per questa capability (non impostabile dall'LLM)."""
    return _approved_capability.get() == capability


def run_with_approved_capability(capability: Optional[str], fn, *args, **kwargs):
    token = _approved_capability.set(capability)
    try:
        return fn(*args, **kwargs)
    finally:
        _approved_capability.reset(token)


def request_runtime_approval(
    tool_name: str,
    args: Dict[str, Any],
    exc: ApprovalRequired,
    *,
    thread_id: Optional[str] = None,
    mode: Optional[str] = None,
    task: Optional[str] = None,
) -> Dict[str, Any]:
    req = create_approval_request(
        tool_name, args, thread_id=thread_id, mode=mode, risk_reason=exc.reason, task=task,
        command_preview=exc.preview, command_prefix=exc.capability,
    )
    return approval_response(req, f"{exc.reason}. Serve la tua autorizzazione esplicita.")


# --- Risoluzione ed elenco ---

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
        if not req:
            # Fallback a recupero da DB se riavviato
            try:
                db_appr = approvals_db.get_automation_approval(request_id)
                if db_appr and db_appr.get("status") == "pending":
                    req = ApprovalRequest(
                        request_id=db_appr["request_id"],
                        tool_name=db_appr["tool_name"],
                        arguments=db_appr["arguments"],
                        thread_id=db_appr["run_id"] if db_appr["run_id"] != "chat_session" else None,
                        mode=None,
                        command_preview=db_appr.get("command_preview"),
                        risk_reason=db_appr.get("risk_reason"),
                        command_prefix=db_appr.get("command_prefix")
                    )
                    _APPROVALS[request_id] = req
            except Exception as e:
                logger.debug(f"Recupero fallback approval da DB non riuscito: {e}")

        if not req or req.status != "pending":
            return None
        if time.time() - req.created_at > APPROVAL_TTL_SECONDS:
            req.status = "expired"
            try:
                approvals_db.resolve_automation_approval(request_id, "expired", resolved_by=resolved_by)
            except Exception:
                pass
            return req

        normalized_action = str(action).lower().strip()
        if normalized_action in ("deny", "false", "refuse"):
            req.status = "denied"
            req.resolved_by = resolved_by
            try:
                approvals_db.resolve_automation_approval(request_id, "deny", resolved_by=resolved_by)
            except Exception:
                pass
            logger.info(f"Approval {request_id}: NEGATA da {resolved_by}")
            return req

        # Azioni di approvazione
        req.status = "approved"
        req.resolved_by = resolved_by
        try:
            approvals_db.resolve_automation_approval(request_id, "approve", resolved_by=resolved_by)
        except Exception:
            pass

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
        seen_ids = set()
        for req in _APPROVALS.values():
            if req.status != "pending":
                continue
            if now - req.created_at > APPROVAL_TTL_SECONDS:
                req.status = "expired"
                continue
            if thread_id and req.thread_id != thread_id:
                continue
            seen_ids.add(req.request_id)
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

        # Integrazione record persistenti da DB per richieste sopravvissute al restart
        try:
            db_pending = approvals_db.list_pending_approvals()
            for d in db_pending:
                rid = d.get("request_id")
                if rid and rid not in seen_ids:
                    t_id = d.get("run_id")
                    if thread_id and t_id != thread_id:
                        continue
                    seen_ids.add(rid)
                    result.append({
                        "request_id": rid,
                        "tool_name": d.get("tool_name"),
                        "arguments": d.get("arguments", {}),
                        "thread_id": t_id if t_id != "chat_session" else None,
                        "mode": None,
                        "command_preview": d.get("command_preview"),
                        "risk_reason": d.get("risk_reason"),
                        "command_prefix": d.get("command_prefix"),
                        "age_seconds": 0,
                    })
        except Exception:
            pass

        return result
