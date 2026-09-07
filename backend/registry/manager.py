import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audit_log
import guardrails
from guardrails import _APPROVALS
from registry.base import BaseToolRegistry
from registry.code_exec import CodeExecRegistry
from registry.memory import MemoryRegistry
from registry.metamcp import MetaMCPRegistry
from registry.vision import VisionRegistry
from registry.web_search import WebSearchRegistry

logger = logging.getLogger("registry_manager")

class ToolRegistryManager:
    def __init__(self):
        self._registries: Dict[str, BaseToolRegistry] = {}
        # Registra i registry ufficiali
        self.register_registry(MetaMCPRegistry())
        self.register_registry(WebSearchRegistry())
        self.register_registry(CodeExecRegistry())
        self.register_registry(MemoryRegistry())
        self.register_registry(VisionRegistry())

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
                     thread_id: Optional[str] = None, mode: Optional[str] = None) -> Any:
        """Individua il registry che possiede il tool, applica i guardrail/approval, esegue e registra l'audit."""
        start_ms = time.monotonic() * 1000

        for reg_name in allowed_registries:
            reg = self._registries.get(reg_name)
            if not reg:
                continue

            reg_tools = reg.get_tools()
            tool_names = [t.get("name") for t in reg_tools if isinstance(t, dict)]
            if tool_name in tool_names:
                # --- Guardrail + Approval workflow (Fase 3.2) ---
                guard = guardrails.enforce_guardrails(tool_name, args, thread_id=thread_id, mode=mode)
                if guard is not None:
                    if guard.get("blocked"):
                        audit_log.log_tool_call(
                            tool_name, args, thread_id=thread_id, mode=mode,
                            registry=reg_name, result={"blocked": guard["reason"]},
                            is_error=True, duration_ms=0,
                        )
                        return {"error": guard["reason"], "blocked_by_guardrail": True}
                    if guard.get("approval_required"):
                        audit_log.log_tool_call(
                            tool_name, args, thread_id=thread_id, mode=mode,
                            registry=reg_name, result={"approval_pending": guard["request_id"]},
                            is_error=False, duration_ms=0,
                        )
                        return {
                            "approval_required": True,
                            "request_id": guard["request_id"],
                            "message": guard["message"],
                            "tool_name": tool_name,
                            "arguments": args,
                        }

                logger.info(f"Esecuzione tool '{tool_name}' tramite registry '{reg_name}'")
                try:
                    result = reg.execute_tool(tool_name, args)
                except Exception as e:
                    result = {"error": str(e)}

                duration_ms = int(time.monotonic() * 1000 - start_ms)
                is_error = isinstance(result, dict) and bool(result.get("error"))
                # --- Audit log (Fase 0.4) ---
                audit_log.log_tool_call(
                    tool_name, args, thread_id=thread_id, mode=mode,
                    registry=reg_name, result=result,
                    is_error=is_error, duration_ms=duration_ms,
                )
                return result

        return {"error": f"Tool '{tool_name}' non trovato o non consentito nei registry: {allowed_registries}"}

    def execute_approved_tool(self, request_id: str) -> Dict[str, Any]:
        """Esegue un tool dopo approvazione utente (Fase 3.2)."""
        req = _APPROVALS.get(request_id) if hasattr(guardrails, "_APPROVALS") else None
        if req is None:
            return {"error": f"Richiesta di approvazione '{request_id}' non trovata."}
        if req.status == "denied":
            return {"error": "Richiesta negata dall'utente.", "status": "denied"}
        if req.status == "expired":
            return {"error": "Richiesta scaduta.", "status": "expired"}
        if req.status != "approved":
            return {"error": "Richiesta non ancora approvata.", "status": req.status}

        logger.info(f"Esecuzione tool approvato '{req.tool_name}' (richiesta {request_id})")
        return self.execute_tool(req.tool_name, req.arguments, ["metamcp", "web", "code", "memory"],
                                 thread_id=req.thread_id, mode=req.mode)

    def execute_tools_parallel(self, calls: List[Dict[str, Any]], allowed_registries: List[str],
                               thread_id: Optional[str] = None, mode: Optional[str] = None,
                               max_workers: int = 4) -> List[Any]:
        """Esegue in parallelo più tool read-only (Fase 3.3). Ordine dei risultati = ordine delle chiamate."""
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(self.execute_tool, c["tool_name"], c.get("arguments", {}),
                            allowed_registries, thread_id=thread_id, mode=mode)
                for c in calls
            ]
            return [f.result() for f in futures]

_global_manager = ToolRegistryManager()

def get_registry_manager() -> ToolRegistryManager:
    return _global_manager
