"""Motore di esecuzione a stati finiti (Durable Step Runner) per Automations & Loops.

Esegue workflow sequenziali salvando su DB ogni step, si ferma in WAITING_APPROVAL senza
bloccare e riprende alla conferma. La logica dei singoli tipi di step sta in `automations/steps/`,
il rendering dei template in `automations/templating.py`.
"""

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.automations.circuit_breaker import CircuitBreakerManager
from app.automations.db import approvals as approvals_db
from app.automations.db import definitions as definitions_db
from app.automations.db import runs as runs_db
from app.automations.models import (
    AutomationDefinition,
    AutomationRun,
    Budget,
    RunStatus,
    StepRun,
    TriggerType,
    WorkflowStepDefinition,
)
from app.automations.run_secrets import collect_secrets
from app.automations.steps import Outcome, StepContext, select_handler
from app.registry.manager import get_registry_manager

logger = logging.getLogger("automations.runner")

FINAL_STATUSES = (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.BLOCKED)


def _effective_inputs(auto_def: AutomationDefinition, run: AutomationRun) -> Dict[str, Any]:
    """Parametri di default dell'automazione sovrascritti dal payload del trigger (anche `inputs`/`parameters`)."""
    payload = dict(run.trigger_payload or {})
    overrides: Dict[str, Any] = {}
    for key in ("inputs", "parameters"):
        if isinstance(payload.get(key), dict):
            overrides.update(payload[key])
    return {**dict(auto_def.parameters or {}), **payload, **overrides}


def _budget_exceeded(budget: Budget, elapsed_sec: float, total_tokens: int) -> Optional[str]:
    if elapsed_sec > budget.max_duration_seconds:
        return f"Timeout globale run superato: {elapsed_sec:.1f}s > {budget.max_duration_seconds}s"
    if total_tokens > budget.max_tokens:
        return f"Tetto massimo token superato: {total_tokens} > {budget.max_tokens}"
    return None


def _next_step_id(steps: List[WorkflowStepDefinition], current_step_id: str) -> Optional[str]:
    ids = [s.step_id for s in steps]
    if current_step_id not in ids:
        return None
    idx = ids.index(current_step_id)
    return ids[idx + 1] if idx + 1 < len(ids) else None


class AutomationRunner:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.registry_manager = get_registry_manager()
        self.circuit_breaker = CircuitBreakerManager(db_path=self.db_path)

    # --- caricamento ----------------------------------------------------------

    def _load_run(self, run_id: str) -> AutomationRun:
        run_dict = runs_db.get_run(run_id, db_path=self.db_path)
        if not run_dict:
            raise ValueError(f"Run '{run_id}' non trovata.")
        return AutomationRun(**run_dict)

    def _load_definition(self, automation_id: str) -> Optional[AutomationDefinition]:
        definition = definitions_db.get_definition(automation_id, db_path=self.db_path)
        return AutomationDefinition(**definition) if definition else None

    # --- ciclo di vita della run ----------------------------------------------

    def start_run(
        self,
        automation_id: str,
        trigger_type: TriggerType = TriggerType.MANUAL,
        trigger_payload: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        associated_thread_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        trigger_id: Optional[str] = None,
    ) -> AutomationRun:
        """Crea ed inizializza una nuova run su database in stato PENDING (o BLOCKED dal circuit breaker)."""
        payload = dict(trigger_payload or {})
        if trigger_id and "trigger_id" not in payload:
            payload["trigger_id"] = trigger_id

        auto_def = self._load_definition(automation_id)
        if not auto_def:
            raise ValueError(f"Automazione '{automation_id}' non trovata.")
        if not auto_def.enabled and trigger_type != TriggerType.MANUAL:
            raise ValueError(f"Automazione '{automation_id}' è disabilitata.")

        idemp_key = idempotency_key or f"{automation_id}_{time.time()}_{uuid.uuid4().hex[:6]}"
        existing = runs_db.get_run_by_idempotency_key(idemp_key, db_path=self.db_path)
        if existing and existing["status"] in ("pending", "running", "completed"):
            logger.info(f"Run con idempotency_key '{idemp_key}' già registrata. Ritorno istanza esistente.")
            return self._load_run(existing["run_id"])

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run_data = {
            "run_id": run_id,
            "automation_id": automation_id,
            "version_applied": auto_def.version,
            "trigger_type": trigger_type.value if hasattr(trigger_type, "value") else str(trigger_type),
            "trigger_payload": payload,
            "status": RunStatus.PENDING.value,
            "current_step_id": auto_def.workflow.initial_step_id,
            "is_dry_run": dry_run,
            "idempotency_key": idemp_key,
            "associated_thread_id": associated_thread_id,
        }

        allowed, reason = self.circuit_breaker.check_execution_allowed(automation_id, budget=auto_def.budget)
        if not allowed:
            logger.warning(f"Esecuzione automazione '{automation_id}' bloccata dal circuit breaker: {reason}")
            run_data.update({"status": RunStatus.BLOCKED.value, "error_message": reason})
        else:
            logger.info(f"Run '{run_id}' creata per automazione '{automation_id}' (dry_run={dry_run})")

        runs_db.create_run(run_data, db_path=self.db_path)
        return AutomationRun(**run_data)

    def execute_run(self, run_id: str) -> AutomationRun:
        """Esegue sequenzialmente gli step della run fino a completamento, blocco o approval."""
        run = self._load_run(run_id)
        if run.status in FINAL_STATUSES:
            return run

        auto_def = self._load_definition(run.automation_id)
        if not auto_def:
            raise ValueError(f"Definizione '{run.automation_id}' mancante per run '{run_id}'.")

        runs_db.update_run_status(run_id, RunStatus.RUNNING.value, db_path=self.db_path)
        run.status = RunStatus.RUNNING

        default_params = dict(auto_def.parameters or {})
        data: Dict[str, Any] = {
            "inputs": _effective_inputs(auto_def, run),
            "config": default_params,
            "secrets": collect_secrets(auto_def, db_path=self.db_path),
            "steps": {s.step_id: {"output": s.output_payload} for s in run.step_runs if s.status == RunStatus.COMPLETED},
            "is_dry_run": run.is_dry_run,
            "run_id": run_id,
            "automation_id": run.automation_id,
        }
        steps_map = {s.step_id: s for s in auto_def.workflow.steps}
        current_step_id = run.current_step_id or auto_def.workflow.initial_step_id
        start_time = time.monotonic()
        total_tokens = run.total_tokens

        while current_step_id:
            # Pausa e annullamento sono cooperativi: l'API cambia lo stato su DB, il runner lo legge tra uno step e l'altro
            db_status = (runs_db.get_run(run_id, db_path=self.db_path) or {}).get("status")
            if db_status == RunStatus.PAUSED.value:
                logger.info(f"Run '{run_id}' congelata in PAUSA prima dello step '{current_step_id}'.")
                runs_db.update_run_status(run_id, RunStatus.PAUSED.value, current_step_id=current_step_id, db_path=self.db_path)
                run.status, run.current_step_id = RunStatus.PAUSED, current_step_id
                return run
            if db_status == RunStatus.CANCELLED.value:
                logger.info(f"Run '{run_id}' annullata dall'utente.")
                run.status = RunStatus.CANCELLED
                return run

            step_def = steps_map.get(current_step_id)
            if not step_def:
                logger.error(f"Step '{current_step_id}' non trovato nel workflow.")
                runs_db.update_run_status(run_id, RunStatus.FAILED.value, error_message=f"Step '{current_step_id}' mancante", db_path=self.db_path)
                run.status = RunStatus.FAILED
                break

            exceeded = _budget_exceeded(auto_def.budget, time.monotonic() - start_time, total_tokens)
            if exceeded:
                logger.warning(f"Run '{run_id}': {exceeded}")
                runs_db.update_run_status(run_id, RunStatus.EXHAUSTED.value, error_message=exceeded, db_path=self.db_path)
                run.status = RunStatus.EXHAUSTED
                break

            already_done = next((s for s in run.step_runs if s.step_id == current_step_id and s.status == RunStatus.COMPLETED), None)
            if already_done:
                data["steps"][current_step_id] = {"output": already_done.output_payload}
                current_step_id = _next_step_id(auto_def.workflow.steps, current_step_id)
                continue

            step_run = self._run_step(run, step_def, data, auto_def)
            total_tokens += step_run.tokens_consumed

            if step_run.status == RunStatus.WAITING_APPROVAL:
                logger.info(f"Run '{run_id}' sospesa su step '{current_step_id}' in attesa di approvazione.")
                runs_db.update_run_status(
                    run_id, RunStatus.WAITING_APPROVAL.value,
                    current_step_id=current_step_id, total_tokens=total_tokens, db_path=self.db_path,
                )
                return self._load_run(run_id)

            if step_run.status == RunStatus.FAILED:
                logger.warning(f"Run '{run_id}' fallita su step '{current_step_id}': {step_run.error_message}")
                self.circuit_breaker.record_failure(auto_def.id, step_run.error_message or "Fallimento step")
                runs_db.update_run_status(
                    run_id, RunStatus.FAILED.value,
                    current_step_id=current_step_id,
                    error_message=step_run.error_message,
                    total_tokens=total_tokens,
                    total_duration_ms=int((time.monotonic() - start_time) * 1000),
                    db_path=self.db_path,
                )
                return self._load_run(run_id)

            data["steps"][current_step_id] = {"output": step_run.output_payload}
            current_step_id = _next_step_id(auto_def.workflow.steps, current_step_id)

        if run.status not in (RunStatus.FAILED, RunStatus.EXHAUSTED, RunStatus.BLOCKED):
            self.circuit_breaker.record_success(auto_def.id)
            total_duration_ms = int((time.monotonic() - start_time) * 1000)
            runs_db.update_run_status(
                run_id, RunStatus.COMPLETED.value,
                current_step_id=None, total_tokens=total_tokens, total_duration_ms=total_duration_ms, db_path=self.db_path,
            )
            logger.info(f"Run '{run_id}' completata con successo ({total_duration_ms}ms, {total_tokens} tokens).")

        return self._load_run(run_id)

    def _run_step(
        self,
        run: AutomationRun,
        step_def: WorkflowStepDefinition,
        data: Dict[str, Any],
        auto_def: AutomationDefinition,
    ) -> StepRun:
        """Esegue uno step registrando su DB lo StepRun prima (RUNNING) e dopo (esito)."""
        step_run = StepRun(
            step_run_id=f"sr_{run.run_id}_{step_def.step_id}",
            run_id=run.run_id,
            step_id=step_def.step_id,
            status=RunStatus.RUNNING,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        runs_db.save_step_run(step_run.model_dump(mode="json"), db_path=self.db_path)
        runs_db.update_run_status(run.run_id, RunStatus.RUNNING.value, current_step_id=step_def.step_id, db_path=self.db_path)

        try:
            outcome = self._execute_step(step_def, data, auto_def, run)
        except Exception as e:
            logger.error(f"Errore esecuzione step '{step_def.step_id}': {e}", exc_info=True)
            outcome = {"status": RunStatus.FAILED, "error_message": str(e), "tokens": 0, "output": None}

        step_run.status = outcome.get("status", RunStatus.COMPLETED)
        step_run.completed_at = datetime.now(timezone.utc).isoformat()
        step_run.output_payload = outcome.get("output")
        step_run.error_message = outcome.get("error_message")
        step_run.tool_calls = outcome.get("tool_calls", [])
        step_run.tokens_consumed = outcome.get("tokens", 0)
        step_run.approval_request_id = outcome.get("approval_request_id")
        runs_db.save_step_run(step_run.model_dump(mode="json"), db_path=self.db_path)
        return step_run

    def _execute_step(
        self,
        step_def: WorkflowStepDefinition,
        data: Dict[str, Any],
        auto_def: AutomationDefinition,
        run: AutomationRun,
    ) -> Outcome:
        ctx = StepContext(step=step_def, automation=auto_def, run=run, data=data,
                          registry_manager=self.registry_manager, db_path=self.db_path)
        return select_handler(step_def)(ctx)

    # --- approvazioni e pausa -------------------------------------------------

    def resume_run(self, run_id: str, approval_id: str, action: str = "approve", resolved_by: str = "user") -> AutomationRun:
        """Risolve l'approvazione pendente e riprende l'esecuzione della run."""
        run = self._load_run(run_id)

        resolved = approvals_db.resolve_automation_approval(approval_id, action, resolved_by=resolved_by, db_path=self.db_path)
        if not resolved:
            raise ValueError(f"Approvazione '{approval_id}' non trovata o già risolta.")

        if action.lower() in ("deny", "false", "refuse"):
            runs_db.update_run_status(
                run_id, RunStatus.BLOCKED.value, error_message=f"Azione negata dall'utente ({resolved_by})", db_path=self.db_path,
            )
            return self._load_run(run_id)

        # Approvata: lo step in attesa conta come completato e la run riparte dal successivo
        if run.current_step_id:
            runs_db.save_step_run({
                "step_run_id": f"sr_{run_id}_{run.current_step_id}",
                "run_id": run_id,
                "step_id": run.current_step_id,
                "status": RunStatus.COMPLETED.value,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "output_payload": {"approval": "granted", "resolved_by": resolved_by},
            }, db_path=self.db_path)

            auto_def = self._load_definition(run.automation_id)
            if auto_def:
                next_step = _next_step_id(auto_def.workflow.steps, run.current_step_id)
                runs_db.update_run_status(run_id, RunStatus.RUNNING.value, current_step_id=next_step, db_path=self.db_path)

        logger.info(f"Approvazione '{approval_id}' concessa. Ripresa esecuzione run '{run_id}'...")
        return self.execute_run(run_id)

    def pause_run(self, run_id: str) -> Dict[str, Any]:
        """Richiede la messa in pausa cooperativa di una run in corso."""
        run = self._load_run(run_id)
        if run.status not in (RunStatus.RUNNING, RunStatus.PENDING):
            raise ValueError(f"Impossibile mettere in pausa una run in stato '{run.status.value}'.")

        runs_db.update_run_status(run_id, RunStatus.PAUSED.value, db_path=self.db_path)
        logger.info(f"Stato della run '{run_id}' impostato a PAUSED.")
        return {"paused": True, "run_id": run_id, "status": RunStatus.PAUSED.value}

    def resume_paused_run(self, run_id: str) -> AutomationRun:
        """Riprende l'esecuzione di una run precedentemente messa in pausa."""
        run = self._load_run(run_id)
        if run.status != RunStatus.PAUSED:
            raise ValueError(f"La run '{run_id}' non è in pausa (stato attuale: {run.status.value}).")

        runs_db.update_run_status(run_id, RunStatus.RUNNING.value, db_path=self.db_path)
        logger.info(f"Ripresa esecuzione della run in pausa '{run_id}'...")
        return self.execute_run(run_id)
