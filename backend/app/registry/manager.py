import logging
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from app.registry.automations_tool import AutomationRegistry
from app.registry.base import BaseToolRegistry
from app.registry.calendar_tool import CalendarRegistry
from app.registry.code_exec import CodeExecRegistry
from app.registry.email_tool import EmailRegistry
from app.registry.mcp import MCPRegistry
from app.registry.memory import MemoryRegistry
from app.registry.vision import VisionRegistry
from app.registry.web_search import WebSearchRegistry
from app.security import approvals, audit_log, flows, network, permissions, policy

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
                     step_run_id: Optional[str] = None, approved_request: Optional[approvals.ApprovalRequest] = None,
                     tag: Optional[Any] = None, clean: bool = False) -> Any:
        """Individua il registry che possiede il tool, applica i guardrail/approval, esegue e registra l'audit.

        `approved_request`: richiesta già approvata dall'utente. Salta la conferma preventiva (resta il
        blocco Tier 1) e autorizza solo la capability runtime per cui era stata emessa.

        `tag`: sensibilità di ciò che ha scritto gli argomenti (app.security.flows). Se la destinazione del tool non
        può riceverla serve un'approvazione di tipo "uscita di dati", che nessuna modalità di sicurezza salta. Senza tag
        (chiamate interne che non vengono da un modello) il controllo non si applica.

        `clean`: argomenti riscritti dall'agent loop senza i dati riservati del turno (`AgentLoop._clean_call`); un'uscita
        consentita finisce nell'audit come `clean` invece che `allow`, così si vede quante conferme la riscrittura evita.
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

                flow_record, flow_stop, flow_capability = self._flow_check(
                    tool_name, args, tag, thread_id=thread_id, mode=mode, task=task, approved_request=approved_request)
                if clean and flow_record and flow_record["flow"] == "allow":
                    flow_record["flow"] = "clean"
                if flow_stop is not None:
                    audit_log.log_tool_call(
                        tool_name, args, thread_id=thread_id, mode=mode, registry=reg_name,
                        result={"approval_pending": flow_stop["request_id"]} if flow_stop.get("request_id") else flow_stop,
                        is_error=not flow_stop.get("request_id"), duration_ms=0,
                        automation_id=automation_id, run_id=run_id, step_run_id=step_run_id, flow=flow_record,
                    )
                    return flow_stop

                logger.info(f"Esecuzione tool '{tool_name}' tramite registry '{reg_name}'")
                approved_capability = approved_request.command_prefix if approved_request else None
                if flow_capability:
                    # L'utente ha approvato l'invio verso questo host vedendo l'indirizzo: vale anche come conferma di rete
                    approved_capability = flow_capability
                # Host che la policy dell'automazione in corso dichiara: per http_get e inspect_image valgono come ammessi
                scope_hosts = self._automation_hosts(automation_id)
                call_tag = flows.join(tag) if tag is not None else flows.PUBLIC_TAG
                try:
                    result = self._run(reg, tool_name, args, approved_capability, scope_hosts, call_tag)
                except approvals.ApprovalRequired as needed:
                    if self._capability_preapproved(tool_name, needed.capability, thread_id, security_mode, approved_request):
                        logger.info(f"Capability '{needed.capability}' per '{tool_name}' già autorizzata: esecuzione")
                        result = self._run(reg, tool_name, args, needed.capability, scope_hosts, call_tag)
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
                    automation_id=automation_id, run_id=run_id, step_run_id=step_run_id, flow=flow_record,
                )
                return result

        return {"error": f"Tool '{tool_name}' non trovato o non consentito nei registry: {allowed_registries}"}

    @staticmethod
    def _flow_check(tool_name: str, args: Dict[str, Any], tag: Optional[Any], *, thread_id: Optional[str],
                    mode: Optional[str], task: Optional[str], approved_request: Optional[approvals.ApprovalRequest],
                    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
        """(riga per l'audit, risposta che sostituisce l'esecuzione, capability di rete concessa dall'approvazione).

        Un flusso negato chiede conferma mostrando il testo che uscirebbe. Vale l'approvazione di questa richiesta,
        oppure un permesso per la chat, che però non vale in un turno che ha letto contenuto non attendibile
        (decisione 6). "Sempre" non esiste per un'uscita di dati: alzare un livello ammesso si fa dalle impostazioni."""
        if tag is None:
            return None, None, None
        tag = flows.join(tag)
        dest = flows.destination_for_tool(tool_name, args)
        if dest is None:
            return None, None, None
        decision = flows.can_flow(tag, dest)
        record = {"label": tag.label.key, "destination": dest.id, "flow": "allow"}
        if decision.allowed:
            return record, None, None
        if tag.label == flows.Label.SECRET:
            record["flow"] = "deny"
            return record, {"error": decision.reason, "blocked_by_guardrail": True, "blocked_by_flow": True}, None

        capability = flows.flow_capability(dest, tag)
        net_capability = network.capability_for(dest.id.split(":", 1)[1]) if dest.kind == "http" else None
        if approved_request is not None and approved_request.command_prefix == capability:
            record["flow"] = "approved"
            return record, None, net_capability
        if not tag.untrusted and permissions.is_command_preapproved(tool_name, capability, thread_id=thread_id):
            record["flow"] = "approved"
            return record, None, net_capability

        record["flow"] = "ask"
        reason = decision.reason
        if tag.untrusted:
            reason += (" Il turno ha letto contenuto non attendibile (web, posta, file): un'autorizzazione già data per "
                       "questa chat non vale, serve una conferma esplicita.")
        req = approvals.create_approval_request(
            tool_name, args, thread_id=thread_id, mode=mode, risk_reason=reason, task=task,
            command_preview=flows.outgoing_preview(tool_name, args, dest), command_prefix=capability,
        )
        return record, approvals.approval_response(
            req, f"Uscita di dati: '{tool_name}' invierebbe a {dest.id} dati {tag.label.key}. Controlla il testo e decidi."), None

    @staticmethod
    def _run(reg: BaseToolRegistry, tool_name: str, args: Dict[str, Any], capability: Optional[str],
             scope_hosts: List[str], call_tag: Any = None) -> Any:
        """Il tool, con la capability autorizzata (se c'è), gli host ammessi in più della policy dell'automazione e il
        tag di chi l'ha chiamato (per i tool che a loro volta chiamano un modello, come inspect_image)."""
        return flows.run_with_call_tag(
            call_tag or flows.PUBLIC_TAG, network.run_with_scope_hosts,
            scope_hosts, approvals.run_with_approved_capability, capability, reg.execute_tool, tool_name, args)

    @staticmethod
    def _automation_hosts(automation_id: Optional[str]) -> List[str]:
        """`allowed_hosts` della policy dell'automazione, letti a ogni chiamata: una modifica vale dal passo successivo."""
        if not automation_id:
            return []
        try:
            from app.automations.db.definitions import get_definition
            definition = get_definition(automation_id) or {}
        except Exception as e:
            logger.warning(f"Policy dell'automazione '{automation_id}' non leggibile: {e}")
            return []
        policy_def = definition.get("permission_policy") or {}
        hosts = policy_def.get("allowed_hosts") if isinstance(policy_def, dict) else None
        return list(hosts) if isinstance(hosts, list) else []

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
                               security_mode: str = "normal", max_workers: int = 4, task: Optional[str] = None,
                               tag: Optional[Any] = None, **audit: Optional[str]) -> List[Any]:
        """Esegue in parallelo più tool read-only (Fase 3.3). Ordine dei risultati = ordine delle chiamate.

        `audit`: automation_id, run_id, step_run_id, come per execute_tool."""
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(self.execute_tool, c["tool_name"], c.get("arguments", {}),
                            allowed_registries, thread_id=thread_id, mode=mode, security_mode=security_mode,
                            task=task, tag=tag, **audit)
                for c in calls
            ]
            return [f.result() for f in futures]

@lru_cache(maxsize=1)
def get_registry_manager() -> ToolRegistryManager:
    return ToolRegistryManager()
