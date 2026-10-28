import logging
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any, Dict, List, Optional

from app.registry.automations_tool import AutomationRegistry
from app.registry.base import BaseToolRegistry
from app.registry.calendar_tool import CalendarRegistry
from app.registry.code_exec import CodeExecRegistry
from app.registry.email_tool import EmailRegistry
from app.registry.mcp import MCPRegistry
from app.registry.memory import MemoryRegistry
from app.registry.vision import VisionRegistry
from app.registry.web_search import WebSearchRegistry
from app.security import approvals, audit_log, permissions, policy

logger = logging.getLogger("registry_manager")

class ToolRegistryManager:
    def __init__(self):
        self._registries: Dict[str, BaseToolRegistry] = {}
        # Registra i registry ufficiali
        self.register_registry(MCPRegistry())
        self.register_registry(WebSearchRegistry())
        self.register_registry(CodeExecRegistry())
        self.register_registry(MemoryRegistry())
        self.register_registry(VisionRegistry())
        self.register_registry(EmailRegistry())
        self.register_registry(AutomationRegistry())
        self.register_registry(CalendarRegistry())

    def register_registry(self, registry: BaseToolRegistry):
        self._registries[registry.name] = registry
        logger.info(f"Tool registry registrato: '{registry.name}'")

    def get_tools_for_mode(self, allowed_registries: List[str]) -> List[Dict[str, Any]]:
        """Restituisce la lista di tool aggregati per i soli registry consentiti."""
        tools = []
        for reg_name in allowed_registries:
            reg = self._registries.get(reg_name)
            if reg:
                try:
                    tlist = reg.get_tools()
                    if tlist:
                        tools.extend(tlist)
                except Exception as e:
                    logger.warning(f"Errore nel recupero tool per registry '{reg_name}': {e}")
        return tools

    def execute_tool(self, tool_name: str, args: Dict[str, Any], allowed_registries: List[str],
                     thread_id: Optional[str] = None, mode: Optional[str] = None,
                     security_mode: str = "normal", task: Optional[str] = None,
                     automation_id: Optional[str] = None, run_id: Optional[str] = None,
                     step_run_id: Optional[str] = None, approved_request: Optional[approvals.ApprovalRequest] = None) -> Any:
        """Individua il registry che possiede il tool, applica i guardrail/approval, esegue e registra l'audit.

        `approved_request`: richiesta già approvata dall'utente. Salta la conferma preventiva (resta il
        blocco Tier 1) e autorizza solo la capability runtime per cui era stata emessa.
        """
        start_ms = time.monotonic() * 1000

        for reg_name in allowed_registries:
            reg = self._registries.get(reg_name)
            if not reg:
                continue

            reg_tools = reg.get_tools()
            tool_names = [t.get("name") for t in reg_tools if isinstance(t, dict)]
            if tool_name in tool_names:
                # --- Guardrail + Approval workflow (Fase 3.2) ---
                guard_mode = "dangerous" if approved_request else security_mode
                guard = policy.enforce_guardrails(tool_name, args, thread_id=thread_id, mode=mode, security_mode=guard_mode, task=task)
                if guard is not None:
                    if guard.get("blocked"):
                        audit_log.log_tool_call(
                            tool_name, args, thread_id=thread_id, mode=mode,
                            registry=reg_name, result={"blocked": guard["reason"]},
                            is_error=True, duration_ms=0,
                            automation_id=automation_id, run_id=run_id, step_run_id=step_run_id,
                        )
                        return {"error": guard["reason"], "blocked_by_guardrail": True}
                    if guard.get("approval_required"):
                        audit_log.log_tool_call(
                            tool_name, args, thread_id=thread_id, mode=mode,
                            registry=reg_name, result={"approval_pending": guard["request_id"]},
                            is_error=False, duration_ms=0,
                            automation_id=automation_id, run_id=run_id, step_run_id=step_run_id,
                        )
                        return guard

                logger.info(f"Esecuzione tool '{tool_name}' tramite registry '{reg_name}'")
                approved_capability = approved_request.command_prefix if approved_request else None
                try:
                    result = approvals.run_with_approved_capability(approved_capability, reg.execute_tool, tool_name, args)
                except approvals.ApprovalRequired as needed:
                    if self._capability_preapproved(tool_name, needed.capability, thread_id, security_mode, approved_request):
                        logger.info(f"Capability '{needed.capability}' per '{tool_name}' già autorizzata: esecuzione")
                        result = approvals.run_with_approved_capability(needed.capability, reg.execute_tool, tool_name, args)
                    else:
                        guard = approvals.request_runtime_approval(
                            tool_name, args, needed, thread_id=thread_id, mode=mode, task=task
                        )
                        audit_log.log_tool_call(
                            tool_name, args, thread_id=thread_id, mode=mode,
                            registry=reg_name, result={"approval_pending": guard["request_id"]},
                            is_error=False, duration_ms=0,
                            automation_id=automation_id, run_id=run_id, step_run_id=step_run_id,
                        )
                        return guard
                except Exception as e:
                    result = {"error": str(e)}

                duration_ms = int(time.monotonic() * 1000 - start_ms)
                is_error = isinstance(result, dict) and bool(result.get("error"))
                # --- Audit log (Fase 0.4 & Fase M4) ---
                audit_log.log_tool_call(
                    tool_name, args, thread_id=thread_id, mode=mode,
                    registry=reg_name, result=result,
                    is_error=is_error, duration_ms=duration_ms,
                    automation_id=automation_id, run_id=run_id, step_run_id=step_run_id,
                )
                return result

        return {"error": f"Tool '{tool_name}' non trovato o non consentito nei registry: {allowed_registries}"}

    @staticmethod
    def _capability_preapproved(tool_name: str, capability: str, thread_id: Optional[str],
                                security_mode: str, approved_request: Optional[approvals.ApprovalRequest]) -> bool:
        # Un'approvazione emessa per l'esecuzione normale del tool non vale per la capability runtime
        if approved_request is None and (security_mode or "").lower() in ("dangerous", "bypass-dangerous", "bypass"):
            return True
        return permissions.is_command_preapproved(tool_name, capability, thread_id=thread_id)

    def execute_approved_tool(self, request_id: str) -> Dict[str, Any]:
        """Esegue un tool dopo approvazione utente (Fase 3.2)."""
        req = approvals.get_approval_request(request_id)
        if req is None:
            return {"error": f"Richiesta di approvazione '{request_id}' non trovata."}
        if req.status == "denied":
            return {"error": "Richiesta negata dall'utente.", "status": "denied"}
        if req.status == "expired":
            return {"error": "Richiesta scaduta.", "status": "expired"}
        if req.status != "approved":
            return {"error": "Richiesta non ancora approvata.", "status": req.status}

        logger.info(f"Esecuzione tool approvato '{req.tool_name}' (richiesta {request_id})")
        all_registries = list(self._registries.keys())
        return self.execute_tool(req.tool_name, req.arguments, all_registries,
                                 thread_id=req.thread_id, mode=req.mode, approved_request=req)

    def execute_tools_parallel(self, calls: List[Dict[str, Any]], allowed_registries: List[str],
                               thread_id: Optional[str] = None, mode: Optional[str] = None,
                               security_mode: str = "normal", max_workers: int = 4) -> List[Any]:
        """Esegue in parallelo più tool read-only (Fase 3.3). Ordine dei risultati = ordine delle chiamate."""
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(self.execute_tool, c["tool_name"], c.get("arguments", {}),
                            allowed_registries, thread_id=thread_id, mode=mode, security_mode=security_mode)
                for c in calls
            ]
            return [f.result() for f in futures]

@lru_cache(maxsize=1)
def get_registry_manager() -> ToolRegistryManager:
    return ToolRegistryManager()
