"""Workflow di approvazione dei tool e permessi concessi."""
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.agent.llm_calls import call_llm
from app.api.deps import verify_api_key
from app.api.schemas import (
    ResolveApprovalRequest,
)
from app.core.text_utils import clean_synthesis_content
from app.memory import thread_store

logger = logging.getLogger("api")

router = APIRouter(tags=["approvals"])


# --- Approval workflow (Fase 3.2) ---

@router.get("/v1/approvals", dependencies=[Depends(verify_api_key)])
async def list_approvals(thread_id: Optional[str] = None):
    """Elenca le richieste di approvazione tool pendenti."""
    from app.security import approvals
    return {"pending": approvals.get_pending_approvals(thread_id=thread_id)}

@router.post("/v1/approvals/{request_id}/resolve", dependencies=[Depends(verify_api_key)])
async def resolve_approval_endpoint(request_id: str, req_body: ResolveApprovalRequest):
    """
    Risolve una richiesta di approvazione tool con scope:
    - 'deny': rifiuta l'azione
    - 'approve': autorizza l'azione una tantum
    - 'approve_thread': autorizza per l'intera sessione/chat
    - 'approve_always': autorizza in modo permanente (tabella tool_permissions)
    """
    from app.registry.manager import get_registry_manager
    from app.security import approvals

    action = req_body.action.lower().strip()
    req = approvals.resolve_approval(request_id, action=action, resolved_by=req_body.resolved_by)
    if req is None:
        raise HTTPException(status_code=404, detail=f"Richiesta '{request_id}' non trovata o già risolta")
    if req.status == "expired":
        raise HTTPException(status_code=410, detail="Richiesta scaduta")

    if action in ("deny", "false", "refuse"):
        if req.thread_id:
            thread_store.save_assistant_message(req.thread_id, {
                "response": f"🛑 **Azione annullata**: L'esecuzione del tool `{req.tool_name}` è stata rifiutata dall'utente.",
                "tool_used": req.tool_name,
                "error": True
            })
        return {
            "request_id": request_id,
            "status": "denied",
            "tool_name": req.tool_name,
            "message": f"Azione per il tool '{req.tool_name}' rifiutata."
        }

    # Esecuzione del tool autorizzato
    result = get_registry_manager().execute_approved_tool(request_id)

    # L'esecuzione ha fatto emergere un'ulteriore approvazione (es. sandbox codice non disponibile):
    # nessuna sintesi, la nuova richiesta viene mostrata come card inline
    if isinstance(result, dict) and result.get("approval_required"):
        trace = [{
            "step_id": 1,
            "tool_name": req.tool_name,
            "args": req.arguments,
            "result": result,
            "reasoning": f"Tool autorizzato dall'utente ({action}): richiesta un'ulteriore autorizzazione",
            "approval_required": True,
            "request_id": result.get("request_id"),
            "approval_prompt": result.get("message"),
            "command_preview": result.get("command_preview"),
            "command_prefix": result.get("command_prefix"),
            "risk_reason": result.get("risk_reason"),
        }]
        if req.thread_id:
            thread_store.save_assistant_message(req.thread_id, {
                "response": result.get("message", ""),
                "tool_used": req.tool_name,
                "execution_trace": trace,
                "mode": req.mode or "act",
                "error": False,
            })
        return {
            "request_id": request_id,
            "status": "approved",
            "action": action,
            "tool_name": req.tool_name,
            "arguments": req.arguments,
            "result": result,
            "response": result.get("message", ""),
            "execution_trace": trace,
        }

    # Recupera task utente associato alla richiesta
    user_task = getattr(req, "task", None)
    if not user_task and req.thread_id:
        try:
            msgs = thread_store.get_thread_messages(req.thread_id)
            user_msgs = [m for m in msgs if m.get("sender") == "user"]
            if user_msgs:
                user_task = user_msgs[-1].get("content") or user_msgs[-1].get("text") or ""
        except Exception as e:
            logger.warning(f"Impossibile recuperare ultimo messaggio utente: {e}")

    # Sintesi LLM del risultato
    from app.registry.search_security import UNTRUSTED_CONTEXT_POLICY
    res_str = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
    obs_text = f"Tool '{req.tool_name}' con argomenti {json.dumps(req.arguments, ensure_ascii=False)} -> {res_str}"
    if len(obs_text) > 4000:
        obs_text = obs_text[:4000] + "\n... [output troncato per brevità]"

    summary_system_prompt = (
        f"Current System Date and Time: {datetime.now().strftime('%A %d %B %Y, %H:%M:%S')}\n"
        f"You are the Homelab Proxmox VE AI Assistant. Synthesize action results.\n"
        f"Language Directive: Always detect and respond in the language used by the user in their request (e.g., Italian if the user writes in Italian, English if they write in English), unless explicitly instructed otherwise.\n"
        f"{UNTRUSTED_CONTEXT_POLICY}"
    )
    summary_prompt = (
        f"User's original request: '{user_task or 'Execute the requested command'}'\n\n"
        f"Authorized and executed action result:\n{obs_text}\n\n"
        f"Provide a comprehensive, conversational, and detailed final response. "
        f"Interpret the tool output, directly address the user's request, "
        f"and clearly explain the outcome (highlight any errors such as missing files, missing configurations, or non-existent containers). "
        f"Respond in natural prose (never provide raw JSON as your only response): this is the direct answer for the user."
    )

    synthesized_text = ""
    try:
        syn_res = call_llm(
            summary_prompt,
            system_prompt=summary_system_prompt,
            max_tokens=4096,
            stream_mode="none",
        )
        raw_ans = syn_res.get("content", "") if syn_res else ""
        synthesized_text = clean_synthesis_content(raw_ans)
    except Exception as e:
        logger.warning(f"Errore durante la sintesi LLM post-approvazione: {e}")

    if not synthesized_text:
        res_preview = res_str[:1500] + ("\n... [troncato]" if len(res_str) > 1500 else "")
        synthesized_text = f"Tool `{req.tool_name}` approvato ed eseguito con successo.\n\n```json\n{res_preview}\n```"

    trace = [
        {
            "step_id": 1,
            "tool_name": req.tool_name,
            "args": req.arguments,
            "result": result,
            "reasoning": f"Tool autorizzato dall'utente ({action})"
        }
    ]

    if req.thread_id:
        thread_store.save_assistant_message(req.thread_id, {
            "response": synthesized_text,
            "tool_used": req.tool_name,
            "execution_trace": trace,
            "mode": req.mode or "act",
            "error": isinstance(result, dict) and bool(result.get("error"))
        })

    return {
        "request_id": request_id,
        "status": "approved",
        "action": action,
        "tool_name": req.tool_name,
        "arguments": req.arguments,
        "result": result,
        "response": synthesized_text,
        "execution_trace": trace
    }

@router.post("/v1/approvals/{request_id}/approve", dependencies=[Depends(verify_api_key)])
async def approve_request(request_id: str):
    """Retrocompatibilità: approva singola esecuzione."""
    return await resolve_approval_endpoint(request_id, ResolveApprovalRequest(action="approve"))

@router.post("/v1/approvals/{request_id}/deny", dependencies=[Depends(verify_api_key)])
async def deny_request(request_id: str):
    """Retrocompatibilità: nega esecuzione."""
    return await resolve_approval_endpoint(request_id, ResolveApprovalRequest(action="deny"))

@router.get("/v1/permissions", dependencies=[Depends(verify_api_key)])
async def get_permissions(thread_id: Optional[str] = None):
    """Elenca i permessi persistenti (ALWAYS) e quelli attivi per la sessione (THREAD)."""
    from app.security import permissions
    return permissions.list_granted_permissions(thread_id=thread_id)

@router.delete("/v1/permissions/{permission_id}", dependencies=[Depends(verify_api_key)])
async def delete_permission(permission_id: int):
    """Revoca un permesso persistente per ID."""
    from app.security import permissions
    success = permissions.revoke_permission(permission_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Permesso ID {permission_id} non trovato")
    return {"status": "ok", "revoked_id": permission_id}

@router.delete("/v1/threads/{thread_id}/permissions", dependencies=[Depends(verify_api_key)])
async def delete_thread_permissions(thread_id: str):
    """Revoca tutti i permessi temporanei di sessione per il thread specificato."""
    from app.security import permissions
    permissions.revoke_thread_permissions(thread_id)
    return {"status": "ok", "thread_id": thread_id, "message": "Permessi di sessione revocati"}
