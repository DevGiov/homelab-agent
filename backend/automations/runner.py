"""Motore di esecuzione a stati finiti (Durable Step Runner) per Automations & Loops.

Esegue workflow sequenziali separando step deterministici da compiti agentici,
gestisce il salvataggio persistente su DB ad ogni passaggio, il congelamento
non-bloccante in WAITING_APPROVAL e la ripresa automatica su conferma.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import config
from automations import db as auto_db
from automations.models import (
    AutomationDefinition,
    AutomationRun,
    RunStatus,
    StepRun,
    StepType,
    TriggerType,
    WorkflowStepDefinition,
)
from registry.manager import get_registry_manager

logger = logging.getLogger("automations.runner")


def _render_template(template_str: str, context: Dict[str, Any]) -> str:
    """Sostituisce espressioni tipo {{steps.step_id.output}} o {{inputs.key}}."""
    if not template_str or not isinstance(template_str, str):
        return template_str

    result = template_str
    # Sostituzioni dirette da context
    import re
    placeholders = re.findall(r"\{\{([a-zA-Z0-9_\.]+)\}\}", template_str)
    for p in placeholders:
        parts = p.split(".")
        val = context
        found = True
        for part in parts:
            if isinstance(val, dict) and part in val:
                val = val[part]
            else:
                found = False
                break
        if found:
            replacement = json.dumps(val, ensure_ascii=False, indent=2) if isinstance(val, (dict, list)) else str(val)
            result = result.replace(f"{{{{{p}}}}}", replacement)
    return result


def _resolve_parameters(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    resolved = {}
    for k, v in params.items():
        if isinstance(v, str):
            resolved[k] = _render_template(v, context)
        elif isinstance(v, dict):
            resolved[k] = _resolve_parameters(v, context)
        else:
            resolved[k] = v
    return resolved


class AutomationRunner:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.registry_manager = get_registry_manager()
        from automations.circuit_breaker import CircuitBreakerManager
        self.circuit_breaker = CircuitBreakerManager(db_path=self.db_path)

    def start_run(
        self,
        automation_id: str,
        trigger_type: TriggerType = TriggerType.MANUAL,
        trigger_payload: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        associated_thread_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AutomationRun:
        """Crea ed inizializza una nuova run su database in stato PENDING."""
        definition_dict = auto_db.get_definition(automation_id, db_path=self.db_path)
        if not definition_dict:
            raise ValueError(f"Automazione '{automation_id}' non trovata.")

        auto_def = AutomationDefinition(**definition_dict)
        if not auto_def.enabled and trigger_type != TriggerType.MANUAL:
            raise ValueError(f"Automazione '{automation_id}' è disabilitata.")

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        idemp_key = idempotency_key or f"{automation_id}_{time.time()}_{uuid.uuid4().hex[:6]}"

        # Verifica duplicati
        existing = auto_db.get_run_by_idempotency_key(idemp_key, db_path=self.db_path)
        if existing and existing["status"] in ("pending", "running", "completed"):
            logger.info(f"Run con idempotency_key '{idemp_key}' già registrata. Ritorno istanza esistente.")
            loaded = auto_db.get_run(existing["run_id"], db_path=self.db_path)
            return AutomationRun(**loaded)

        # Verifica Circuit Breaker (Milestone M4)
        allowed, reason = self.circuit_breaker.check_execution_allowed(automation_id, budget=auto_def.budget)
        if not allowed:
            logger.warning(f"Esecuzione automazione '{automation_id}' bloccata dal circuit breaker: {reason}")
            run_data = {
                "run_id": run_id,
                "automation_id": automation_id,
                "version_applied": auto_def.version,
                "trigger_type": trigger_type.value if hasattr(trigger_type, "value") else str(trigger_type),
                "trigger_payload": trigger_payload or {},
                "status": RunStatus.BLOCKED.value,
                "current_step_id": auto_def.workflow.initial_step_id,
                "is_dry_run": dry_run,
                "idempotency_key": idemp_key,
                "associated_thread_id": associated_thread_id,
                "error_message": reason,
            }
            auto_db.create_run(run_data, db_path=self.db_path)
            return AutomationRun(**run_data)

        run_data = {
            "run_id": run_id,
            "automation_id": automation_id,
            "version_applied": auto_def.version,
            "trigger_type": trigger_type.value if hasattr(trigger_type, "value") else str(trigger_type),
            "trigger_payload": trigger_payload or {},
            "status": RunStatus.PENDING.value,
            "current_step_id": auto_def.workflow.initial_step_id,
            "is_dry_run": dry_run,
            "idempotency_key": idemp_key,
            "associated_thread_id": associated_thread_id,
        }

        auto_db.create_run(run_data, db_path=self.db_path)
        logger.info(f"Run '{run_id}' creata per automazione '{automation_id}' (dry_run={dry_run})")
        return AutomationRun(**run_data)

    create_run = start_run

    def execute_run(self, run_id: str) -> AutomationRun:
        """Esegue sequenzialmente gli step della run fino a completamento, blocco o approval."""
        run_dict = auto_db.get_run(run_id, db_path=self.db_path)
        if not run_dict:
            raise ValueError(f"Run '{run_id}' non trovata.")

        run = AutomationRun(**run_dict)
        if run.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.BLOCKED):
            return run

        auto_dict = auto_db.get_definition(run.automation_id, db_path=self.db_path)
        if not auto_dict:
            raise ValueError(f"Definizione '{run.automation_id}' mancante per run '{run_id}'.")
        auto_def = AutomationDefinition(**auto_dict)

        # Transizione a RUNNING
        auto_db.update_run_status(run_id, RunStatus.RUNNING.value, db_path=self.db_path)
        run.status = RunStatus.RUNNING

        # Ricostruzione contesto dalle esecuzioni precedenti
        context: Dict[str, Any] = {
            "inputs": run.trigger_payload,
            "steps": {},
            "is_dry_run": run.is_dry_run,
            "run_id": run_id,
            "automation_id": run.automation_id,
        }
        for s in run.step_runs:
            if s.status == RunStatus.COMPLETED:
                context["steps"][s.step_id] = {"output": s.output_payload}

        steps_map: Dict[str, WorkflowStepDefinition] = {s.step_id: s for s in auto_def.workflow.steps}
        current_step_id = run.current_step_id or auto_def.workflow.initial_step_id

        start_time = time.monotonic()
        total_tokens = run.total_tokens

        while current_step_id:
            step_def = steps_map.get(current_step_id)
            if not step_def:
                logger.error(f"Step '{current_step_id}' non trovato nel workflow.")
                auto_db.update_run_status(run_id, RunStatus.FAILED.value, error_message=f"Step '{current_step_id}' mancante", db_path=self.db_path)
                run.status = RunStatus.FAILED
                break

            # 1. Verifica Hard Budget Limiti
            elapsed_sec = time.monotonic() - start_time
            if elapsed_sec > auto_def.budget.max_duration_seconds:
                err_msg = f"Timeout globale run superato: {elapsed_sec:.1f}s > {auto_def.budget.max_duration_seconds}s"
                logger.warning(f"Run '{run_id}': {err_msg}")
                auto_db.update_run_status(run_id, RunStatus.EXHAUSTED.value, error_message=err_msg, db_path=self.db_path)
                run.status = RunStatus.EXHAUSTED
                break

            if total_tokens > auto_def.budget.max_tokens:
                err_msg = f"Tetto massimo token superato: {total_tokens} > {auto_def.budget.max_tokens}"
                logger.warning(f"Run '{run_id}': {err_msg}")
                auto_db.update_run_status(run_id, RunStatus.EXHAUSTED.value, error_message=err_msg, db_path=self.db_path)
                run.status = RunStatus.EXHAUSTED
                break

            # 2. Controllo se lo step è già completato
            existing_step = next((s for s in run.step_runs if s.step_id == current_step_id and s.status == RunStatus.COMPLETED), None)
            if existing_step:
                context["steps"][current_step_id] = {"output": existing_step.output_payload}
                current_step_id = self._next_step_id(auto_def.workflow.steps, current_step_id)
                continue

            # 3. Creazione o ricaricamento StepRun
            step_run_id = f"sr_{run_id}_{current_step_id}"
            step_run = StepRun(
                step_run_id=step_run_id,
                run_id=run_id,
                step_id=current_step_id,
                status=RunStatus.RUNNING,
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            auto_db.save_step_run(step_run.model_dump(mode="json"), db_path=self.db_path)
            auto_db.update_run_status(run_id, RunStatus.RUNNING.value, current_step_id=current_step_id, db_path=self.db_path)

            # 4. Esecuzione Step in base al tipo
            try:
                outcome = self._execute_step(step_def, context, auto_def, run)
            except Exception as e:
                logger.error(f"Errore esecuzione step '{current_step_id}': {e}", exc_info=True)
                outcome = {
                    "status": RunStatus.FAILED,
                    "error_message": str(e),
                    "tokens": 0,
                    "output": None,
                }

            # 5. Gestione esito dello step
            step_status = outcome.get("status", RunStatus.COMPLETED)
            step_run.status = step_status
            step_run.completed_at = datetime.now(timezone.utc).isoformat()
            step_run.output_payload = outcome.get("output")
            step_run.error_message = outcome.get("error_message")
            step_run.tool_calls = outcome.get("tool_calls", [])
            tokens_step = outcome.get("tokens", 0)
            step_run.tokens_consumed = tokens_step
            total_tokens += tokens_step
            step_run.approval_request_id = outcome.get("approval_request_id")

            auto_db.save_step_run(step_run.model_dump(mode="json"), db_path=self.db_path)

            if step_status == RunStatus.WAITING_APPROVAL:
                logger.info(f"Run '{run_id}' sospesa su step '{current_step_id}' in attesa di approvazione.")
                auto_db.update_run_status(
                    run_id, RunStatus.WAITING_APPROVAL.value,
                    current_step_id=current_step_id,
                    total_tokens=total_tokens,
                    db_path=self.db_path
                )
                updated_run = auto_db.get_run(run_id, db_path=self.db_path)
                return AutomationRun(**updated_run)

            if step_status == RunStatus.FAILED:
                logger.warning(f"Run '{run_id}' fallita su step '{current_step_id}': {step_run.error_message}")
                self.circuit_breaker.record_failure(auto_def.id, step_run.error_message or "Fallimento step")
                auto_db.update_run_status(
                    run_id, RunStatus.FAILED.value,
                    current_step_id=current_step_id,
                    error_message=step_run.error_message,
                    total_tokens=total_tokens,
                    total_duration_ms=int((time.monotonic() - start_time) * 1000),
                    db_path=self.db_path
                )
                updated_run = auto_db.get_run(run_id, db_path=self.db_path)
                return AutomationRun(**updated_run)

            # Step completato con successo: memorizzazione in contesto e avanzamento
            context["steps"][current_step_id] = {"output": outcome.get("output")}
            current_step_id = self._next_step_id(auto_def.workflow.steps, current_step_id)

        # 6. Workflow terminato
        if run.status != RunStatus.FAILED and run.status != RunStatus.EXHAUSTED and run.status != RunStatus.BLOCKED:
            self.circuit_breaker.record_success(auto_def.id)
            total_duration_ms = int((time.monotonic() - start_time) * 1000)
            auto_db.update_run_status(
                run_id, RunStatus.COMPLETED.value,
                current_step_id=None,
                total_tokens=total_tokens,
                total_duration_ms=total_duration_ms,
                db_path=self.db_path
            )
            logger.info(f"Run '{run_id}' completata con successo ({total_duration_ms}ms, {total_tokens} tokens).")

        updated_run = auto_db.get_run(run_id, db_path=self.db_path)
        return AutomationRun(**updated_run)

    def resume_run(
        self,
        run_id: str,
        approval_id: str,
        action: str = "approve",
        resolved_by: str = "user"
    ) -> AutomationRun:
        """Risolve l'approvazione pendente e riprende l'esecuzione della run."""
        run_dict = auto_db.get_run(run_id, db_path=self.db_path)
        if not run_dict:
            raise ValueError(f"Run '{run_id}' non trovata.")

        resolved = auto_db.resolve_automation_approval(approval_id, action, resolved_by=resolved_by, db_path=self.db_path)
        if not resolved:
            raise ValueError(f"Approvazione '{approval_id}' non trovata o già risolta.")

        if action.lower() in ("deny", "false", "refuse"):
            auto_db.update_run_status(
                run_id, RunStatus.BLOCKED.value,
                error_message=f"Azione negata dall'utente ({resolved_by})",
                db_path=self.db_path
            )
            updated_run = auto_db.get_run(run_id, db_path=self.db_path)
            return AutomationRun(**updated_run)

        # Se approvata, segniamo lo step che era in attesa come completato e avanziamo
        current_step_id = run_dict.get("current_step_id")
        if current_step_id:
            sr_id = f"sr_{run_id}_{current_step_id}"
            auto_db.save_step_run({
                "step_run_id": sr_id,
                "run_id": run_id,
                "step_id": current_step_id,
                "status": RunStatus.COMPLETED.value,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "output_payload": {"approval": "granted", "resolved_by": resolved_by}
            }, db_path=self.db_path)

            auto_dict = auto_db.get_definition(run_dict["automation_id"], db_path=self.db_path)
            if auto_dict:
                auto_def = AutomationDefinition(**auto_dict)
                next_step = self._next_step_id(auto_def.workflow.steps, current_step_id)
                auto_db.update_run_status(run_id, RunStatus.RUNNING.value, current_step_id=next_step, db_path=self.db_path)

        logger.info(f"Approvazione '{approval_id}' concessa. Ripresa esecuzione run '{run_id}'...")
        return self.execute_run(run_id)

    def _execute_step(
        self,
        step_def: WorkflowStepDefinition,
        context: Dict[str, Any],
        auto_def: AutomationDefinition,
        run: AutomationRun,
    ) -> Dict[str, Any]:
        """Esegue la logica di un singolo step differenziando deterministic da agentic."""
        step_type = step_def.type

        # Se lo step è esplicitamente un Approval Gate manuale
        if step_type == StepType.APPROVAL_GATE or step_def.requires_approval:
            req_id = f"apr_{uuid.uuid4().hex[:12]}"
            auto_db.create_automation_approval({
                "request_id": req_id,
                "run_id": run.run_id,
                "step_run_id": f"sr_{run.run_id}_{step_def.step_id}",
                "tool_name": step_def.action_or_tool or "manual_approval_gate",
                "arguments": step_def.parameters,
                "command_preview": f"Step '{step_def.name}' richiede conferma esplicita",
                "risk_reason": f"Approval Gate richiesto dalla definizione del workflow per '{step_def.name}'",
                "status": "pending",
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
            }, db_path=self.db_path)
            return {
                "status": RunStatus.WAITING_APPROVAL,
                "approval_request_id": req_id,
                "output": None,
                "tokens": 0,
            }

        # Step Codice Custom / Python Script (Milestone M5)
        if step_type in (StepType.CUSTOM_CODE, "custom_code") or (
            step_type == StepType.DETERMINISTIC_ACTION
            and step_def.action_or_tool
            and (step_def.action_or_tool.endswith(".py") or step_def.action_or_tool == "custom_code")
        ):
            script_path = step_def.parameters.get("script_path") or step_def.action_or_tool
            entrypoint_func = step_def.parameters.get("entrypoint")
            timeout_sec = step_def.timeout_seconds or 60

            if run.is_dry_run:
                return {
                    "status": RunStatus.COMPLETED,
                    "output": {"dry_run": True, "simulated_code": script_path},
                    "tokens": 0,
                    "tool_calls": [{"tool_name": "custom_code", "script": script_path, "dry_run": True}],
                }

            from automations.code_runner import SandboxedCodeRunner
            code_runner = SandboxedCodeRunner()
            if self.db_path:
                artifacts_base = os.path.join(os.path.dirname(self.db_path), "artifacts")
            else:
                artifacts_base = getattr(config, "ARTIFACTS_DIR", "/data/artifacts")
            artifacts_dir = os.path.join(artifacts_base, run.run_id)
            ctx_payload = {
                "automation_id": auto_def.id,
                "run_id": run.run_id,
                "step_id": step_def.step_id,
                "inputs": _resolve_parameters(step_def.parameters, context),
                "step_outputs": context.get("steps", {}),
                "artifacts_dir": artifacts_dir,
            }
            code_res = code_runner.run_script(
                script_path=script_path,
                context_payload=ctx_payload,
                entrypoint_func=entrypoint_func,
                timeout_seconds=timeout_sec,
                secrets_whitelist=auto_def.permission_policy.secrets_whitelist,
            )

            # Salva gli eventuali artefatti prodotti nel database
            for art in code_res.get("artifacts", []):
                art_id = f"art_{uuid.uuid4().hex[:8]}"
                auto_db.save_artifact({
                    "artifact_id": art_id,
                    "run_id": run.run_id,
                    "step_run_id": f"sr_{run.run_id}_{step_def.step_id}",
                    "name": art["name"],
                    "type": art.get("type", "report"),
                    "mime_type": art.get("mime_type", "text/plain"),
                    "storage_uri": art["storage_uri"],
                    "checksum_sha256": art.get("checksum_sha256"),
                }, db_path=self.db_path)

            if not code_res.get("success"):
                return {
                    "status": RunStatus.FAILED,
                    "error_message": code_res.get("error", "Errore esecuzione codice custom"),
                    "output": code_res.get("output"),
                    "tokens": 0,
                    "tool_calls": [{"tool_name": "custom_code", "script": script_path, "result": code_res}],
                }

            return {
                "status": RunStatus.COMPLETED,
                "output": code_res.get("output"),
                "tokens": 0,
                "tool_calls": [{"tool_name": "custom_code", "script": script_path, "result": code_res}],
            }

        # Step Deterministico
        if step_type == StepType.DETERMINISTIC_ACTION:
            tool_name = step_def.action_or_tool
            if not tool_name:
                raise ValueError(f"Step '{step_def.step_id}' non specifica 'action_or_tool'.")

            # Verifica tool allowlist
            if auto_def.permission_policy.allowed_tools and tool_name not in auto_def.permission_policy.allowed_tools:
                raise PermissionError(f"Tool '{tool_name}' non autorizzato dalla policy dell'automazione.")

            params = _resolve_parameters(step_def.parameters, context)

            if run.is_dry_run:
                return {
                    "status": RunStatus.COMPLETED,
                    "output": {"dry_run": True, "simulated_tool": tool_name, "parameters": params},
                    "tokens": 0,
                    "tool_calls": [{"tool_name": tool_name, "args": params, "dry_run": True}]
                }

            # Esecuzione effettiva del tool tramite Registry Manager
            res = self.registry_manager.execute_tool(
                tool_name,
                params,
                allowed_registries=auto_def.permission_policy.allowed_registries,
                thread_id=run.associated_thread_id,
                mode="act",
                security_mode=auto_def.permission_policy.security_mode,
                task=f"Automation {auto_def.name} Step {step_def.name}",
                automation_id=auto_def.id,
                run_id=run.run_id,
                step_run_id=f"sr_{run.run_id}_{step_def.step_id}",
            )

            # Se il guardrail ha intercettato un'azione che richiede approvazione
            if isinstance(res, dict) and res.get("approval_required"):
                req_id = res.get("request_id")
                return {
                    "status": RunStatus.WAITING_APPROVAL,
                    "approval_request_id": req_id,
                    "output": res,
                    "tokens": 0,
                    "tool_calls": [{"tool_name": tool_name, "args": params, "result": res}]
                }

            # Se il tool ha ritornato errore bloccante da guardrail
            if isinstance(res, dict) and res.get("blocked_by_guardrail"):
                return {
                    "status": RunStatus.FAILED,
                    "error_message": f"Azione bloccata categoricamente dal guardrail di sicurezza: {res.get('error')}",
                    "output": res,
                    "tokens": 0,
                    "tool_calls": [{"tool_name": tool_name, "args": params, "result": res}]
                }

            # Se il tool ha ritornato un errore di esecuzione
            if isinstance(res, dict) and res.get("error"):
                return {
                    "status": RunStatus.FAILED,
                    "error_message": f"Errore esecuzione tool '{tool_name}': {res.get('error')}",
                    "output": res,
                    "tokens": 0,
                    "tool_calls": [{"tool_name": tool_name, "args": params, "result": res}]
                }

            return {
                "status": RunStatus.COMPLETED,
                "output": res,
                "tokens": 0,
                "tool_calls": [{"tool_name": tool_name, "args": params, "result": res}]
            }

        # Step Agentico (Ragionamento / Sintesi LLM)
        if step_type == StepType.AGENTIC_TASK:
            rendered_prompt = _render_template(step_def.prompt_template or "", context)

            if run.is_dry_run:
                return {
                    "status": RunStatus.COMPLETED,
                    "output": {"dry_run": True, "prompt_preview": rendered_prompt[:500]},
                    "tokens": 0,
                    "tool_calls": []
                }

            # Invocazione loop agentico controllato
            from agent_loop import run_agent_loop
            from graph import _call_llm, _call_llm_structured

            loop_res = run_agent_loop(
                task=rendered_prompt,
                mode="act",
                security_mode=auto_def.permission_policy.security_mode,
                call_llm_fn=lambda p, system_prompt=None, reasoning_budget=0, model=None, reasoning_phase=None: _call_llm(
                    p, system_prompt=system_prompt, max_tokens=2048, reasoning_budget=0, model=model, stream_mode="none"
                ),
                call_llm_structured_fn=None,  # Sintesi diretta per prompt deterministico
            )

            final_text = loop_res.get("final_response", "")
            trace = loop_res.get("execution_trace", [])
            estimated_tokens = int(len(rendered_prompt.split()) * 1.3) + int(len(final_text.split()) * 1.3)

            return {
                "status": RunStatus.COMPLETED,
                "output": {"text": final_text},
                "tokens": estimated_tokens,
                "tool_calls": trace
            }

        # Step di Valutazione (Assert / Gating)
        if step_type == StepType.EVALUATION_GATE:
            return {
                "status": RunStatus.COMPLETED,
                "output": {"evaluation": "passed"},
                "tokens": 0,
            }

        raise NotImplementedError(f"Tipo di step '{step_type}' non supportato.")

    def _next_step_id(self, steps: List[WorkflowStepDefinition], current_step_id: str) -> Optional[str]:
        for i, s in enumerate(steps):
            if s.step_id == current_step_id:
                if i + 1 < len(steps):
                    return steps[i + 1].step_id
                return None
        return None
