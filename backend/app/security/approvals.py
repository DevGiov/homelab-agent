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

APPROVAL_TTL_SECONDS = 1800  # 30 minuti: una scheda di chat resta decidibile oltre i pochi secondi del turno
RUN_APPROVAL_TTL_SECONDS = 24 * 3600  # una run può partire di notte: la decisione arriva quando l'utente c'è


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
    # La scadenza è created_at + ttl_seconds, la stessa di expires_at sul database (il ripristino la ricava da lì)
    ttl_seconds: int = APPROVAL_TTL_SECONDS


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
        req.created_at = now
        expired = [k for k, v in _APPROVALS.items() if v.status == "pending" and _is_past_deadline(v, now)]
        for k in expired:
            _APPROVALS[k].status = "expired"
        _APPROVALS[req.request_id] = req
    _mark_expired(expired)

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
            "created_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            "expires_at": datetime.fromtimestamp(_deadline(req), tz=timezone.utc).isoformat()
        })
    except Exception as e:
        logger.debug(f"Salvataggio approval su DB automazioni non eseguito: {e}")

    logger.info(f"Approval request creata: {req.request_id} per tool '{tool_name}' ({risk_reason})")
    return req


def get_approval_request(request_id: str) -> Optional[ApprovalRequest]:
    with _approval_lock:
        return _APPROVALS.get(request_id)


def bind_to_run(request_id: str, run_id: str, step_run_id: str, db_path: Optional[str] = None) -> None:
    """Lega al passo di una run una richiesta nata dal guardrail, con la scadenza delle run."""
    deadline = time.time() + RUN_APPROVAL_TTL_SECONDS
    with _approval_lock:
        req = _APPROVALS.get(request_id)
        if req:
            # In memoria la stessa scadenza della riga: 24 ore da adesso, non dalla creazione
            req.ttl_seconds = int(deadline - req.created_at)
    expires_at = datetime.fromtimestamp(deadline, tz=timezone.utc).isoformat()
    if not approvals_db.bind_approval_to_run(request_id, run_id, step_run_id, expires_at, db_path=db_path):
        logger.warning(f"Richiesta '{request_id}' non trovata: non legata alla run '{run_id}'")


def approved_request_for(request_id: str, tool_name: str, arguments: Dict[str, Any], thread_id: Optional[str], mode: Optional[str]) -> ApprovalRequest:
    """La richiesta già approvata con cui eseguire il tool. Dopo un riavvio può non essere più in memoria: la decisione è
    comunque presa e registrata."""
    return get_approval_request(request_id) or ApprovalRequest(
        request_id=request_id, tool_name=tool_name, arguments=arguments, thread_id=thread_id, mode=mode, status="approved")


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
        "expires_at": _expires_at_iso(req),
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

def _parse_utc(value: Any) -> Optional[float]:
    """Epoch UTC da un timestamp salvato (ISO, oppure la forma senza fuso di SQLite)."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _deadline(req: ApprovalRequest) -> float:
    return req.created_at + req.ttl_seconds


def _is_past_deadline(req: ApprovalRequest, now: float) -> bool:
    return now > _deadline(req)


def _expires_at_iso(req: ApprovalRequest) -> str:
    return _iso_or_none(_deadline(req))


def _mark_expired(request_ids: List[str]) -> None:
    """Allinea il database alle richieste che la pulizia in memoria ha segnato expired."""
    for request_id in request_ids:
        try:
            approvals_db.expire_automation_approval(request_id)
        except Exception as e:
            logger.debug(f"Scadenza approval '{request_id}' non scritta sul database: {e}")


def _restore_approval(request_id: str) -> Optional[ApprovalRequest]:
    """Ricarica pending o expired dal database, copiando created_at e expires_at. Non tocca approve/deny."""
    try:
        row = approvals_db.get_automation_approval(request_id)
    except Exception as e:
        logger.debug(f"Recupero fallback approval da DB non riuscito: {e}")
        return None
    if not row or row.get("status") not in ("pending", "expired"):
        return None
    created = _parse_utc(row.get("created_at"))
    expires = _parse_utc(row.get("expires_at"))
    if created is None:
        created = expires if expires is not None else time.time()
    if expires is None:
        expires = created + APPROVAL_TTL_SECONDS
    run_id = row.get("run_id")
    req = ApprovalRequest(
        request_id=row["request_id"],
        tool_name=row.get("tool_name") or "",
        arguments=row.get("arguments") or {},
        thread_id=run_id if run_id not in (None, "chat_session") else None,
        mode=None,
        command_preview=row.get("command_preview"),
        risk_reason=row.get("risk_reason"),
        command_prefix=row.get("command_prefix"),
        created_at=created,
        ttl_seconds=max(0, int(round(expires - created))),
        status=row.get("status") or "pending",
        resolved_by=row.get("resolved_by"),
    )
    _APPROVALS[request_id] = req
    return req


# Una richiesta che non si può più decidere: codice del dettaglio -> stato HTTP della risposta
CLOSED_HTTP_STATUS = {"not_found": 404, "already_resolved": 409, "expired": 410}

_ACTION_LABELS = {"approved": "approvata", "denied": "rifiutata"}


def _iso_or_none(epoch: Optional[float]) -> Optional[str]:
    # Al secondo: la UI la mostra in ore e minuti
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="seconds") if epoch is not None else None


def closed_approval(request_id: str) -> Dict[str, Any]:
    """Perché una richiesta non si può più decidere, come `detail` della risposta HTTP.

    `code` è `not_found` (id sconosciuto), `already_resolved` (con l'azione registrata e chi l'ha presa)
    oppure `expired` (con la scadenza). Legge la memoria e poi il database: dopo un riavvio vale la riga.
    """
    with _approval_lock:
        req = _APPROVALS.get(request_id)
    status, resolved_by, expires_at = None, None, None
    if req is not None and req.status != "pending":
        status, resolved_by, expires_at = req.status, req.resolved_by, _expires_at_iso(req)
    else:
        try:
            row = approvals_db.get_automation_approval(request_id)
        except Exception as e:
            logger.debug(f"Lettura approval '{request_id}' non riuscita: {e}")
            row = None
        if row:
            status = str(row.get("resolution_action") or row.get("status") or "")
            resolved_by = row.get("resolved_by")
            expires_at = _iso_or_none(_parse_utc(row.get("expires_at")))
    if status == "expired":
        return {"code": "expired", "expires_at": expires_at,
                "message": f"Richiesta '{request_id}' scaduta: il tool non è stato eseguito"}
    if status in _ACTION_LABELS:
        return {"code": "already_resolved", "action": status, "resolved_by": resolved_by,
                "message": f"Richiesta '{request_id}' già risolta: {_ACTION_LABELS[status]}"}
    return {"code": "not_found", "message": f"Richiesta '{request_id}' non trovata"}


def expire_if_overdue(row: Dict[str, Any]) -> bool:
    """True se la riga pending ha superato la sua expires_at: la segna expired (database e memoria)."""
    deadline = _parse_utc(row.get("expires_at"))
    if row.get("status") != "pending" or deadline is None or time.time() <= deadline:
        return False
    request_id = row["request_id"]
    with _approval_lock:
        req = _APPROVALS.get(request_id)
        if req is not None and req.status == "pending":
            req.status = "expired"
    _mark_expired([request_id])
    return True


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
            req = _restore_approval(request_id)

        if not req:
            return None
        # Scaduta (già segnata, o oltre la scadenza vera): il click non è un approve né un deny
        if req.status == "pending" and _is_past_deadline(req, time.time()):
            req.status = "expired"
            try:
                approvals_db.expire_automation_approval(request_id)
            except Exception:
                pass
            return req
        if req.status != "pending":
            return None

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

        from app.security import flows
        if normalized_action in ("approve_always", "always") and flows.is_flow_capability(req.command_prefix):
            # Un'uscita di dati non si autorizza per sempre: vale per questa chat. Il livello ammesso di una
            # destinazione si alza dalle impostazioni, non da una richiesta
            logger.info(f"Approval {request_id}: 'sempre' su un'uscita di dati vale solo per questa chat")
            normalized_action = "approve_thread"

        if normalized_action == "approve_thread" and req.thread_id:
            permissions.grant_permission(req.tool_name, "thread", thread_id=req.thread_id, command_prefix=req.command_prefix, created_by=resolved_by)
            logger.info(f"Approval {request_id}: APPROVATA per l'intero thread '{req.thread_id}'")
        elif normalized_action in ("approve_always", "always"):
            from app.security import network
            host = network.host_from_capability(req.command_prefix)
            if host:
                # Un host contattato da http_get / inspect_image: "sempre" lo mette nella lista degli host ammessi,
                # che l'utente vede e modifica dalle impostazioni
                network.add_allowed_host(host, note=f"Approvato da una richiesta di {req.tool_name}", origin="approval")
            else:
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
        expired_ids: List[str] = []
        for req in _APPROVALS.values():
            if req.status != "pending":
                continue
            if _is_past_deadline(req, now):
                req.status = "expired"
                expired_ids.append(req.request_id)
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
        _mark_expired(expired_ids)

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
