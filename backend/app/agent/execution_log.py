"""Esecuzione dei piani multi-step come Saga: log write-ahead per step e rollback LIFO (dichiarativo, poi LLM)."""
import json
import logging
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from app.agent import llm_calls, turn_checkpoints
from app.agent.mode_policy import get_mode_policy
from app.agent.tool_catalog import get_rollback_info, get_tool_catalog
from app.mcp.hub import get_mcp_hub
from app.registry.manager import get_registry_manager
from app.security import approvals, policy

logger = logging.getLogger("graph")


def extract_output_var(result: Any, output_var: str, step_id: int) -> Any:
    """Estrae una variabile da un result di tool MetaMCP con fallback a euristiche annidate."""
    if not output_var:
        return None

    def find_key_in_nested(obj: Any, key: str, max_depth: int = 5) -> Any:
        if max_depth <= 0:
            return None
        if isinstance(obj, dict):
            if key in obj and obj[key] is not None:
                return obj[key]
            for v in obj.values():
                found = find_key_in_nested(v, key, max_depth - 1)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = find_key_in_nested(item, key, max_depth - 1)
                if found is not None:
                    return found
        elif isinstance(obj, str):
            try:
                parsed = json.loads(obj)
                return find_key_in_nested(parsed, key, max_depth - 1)
            except Exception:
                pass
        return None

    # 1. Cerca output_var esplicito
    val = find_key_in_nested(result, output_var)
    if val is not None:
        logger.info(f"Step {step_id}: estratta variabile '{output_var}'={val}")
        return val

    # 2. Fallback a euristiche generiche
    for heuristic_key in ["ip", "vmid", "id", "value", "result"]:
        val = find_key_in_nested(result, heuristic_key)
        if val is not None:
            logger.info(f"Step {step_id}: estratta variabile '{output_var}'={val} (fallback su '{heuristic_key}')")
            return val

    # 3. Non trovato
    logger.warning(f"Step {step_id}: variabile '{output_var}' non trovata nel result, uso None")
    return None


def topological_sort_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ordina gli step in ordine topologico basato su depends_on."""
    if not steps:
        return []
    sorted_steps = []
    remaining = list(steps)
    executed_ids = set()

    while remaining:
        ready = [s for s in remaining if s.get("depends_on") is None or s.get("depends_on") in executed_ids]
        if not ready:
            ready = [remaining[0]]

        for step in ready:
            sorted_steps.append(step)
            remaining.remove(step)
            step_id = step.get("id")
            if step_id is not None:
                executed_ids.add(step_id)

    return sorted_steps


class ExecutionLog:
    """Transaction log entry per un singolo step (WAL pattern)."""
    def __init__(self, step: dict, tool_name: str, args: dict):
        self.step = step
        self.tool_name = tool_name
        self.args = args
        self.result = None
        self.error = None
        self.timestamp_start = datetime.now(UTC)
        self.timestamp_end = None
        self.rollback_executed = False
        self.rollback_error = None

    def to_dict(self) -> dict:
        return {
            "step_id": self.step.get("id"),
            "tool_name": self.tool_name,
            "args": self.args,
            "result": self.result,
            "error": self.error,
            "timestamp_start": self.timestamp_start.isoformat(),
            "timestamp_end": self.timestamp_end.isoformat() if self.timestamp_end else None,
            "rollback_executed": self.rollback_executed,
            "rollback_error": self.rollback_error
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionLog":
        """Dallo stato di un piano sospeso: `step` più i campi di `to_dict`."""
        entry = cls(data["step"], data["tool_name"], data["args"])
        entry.result, entry.error = data.get("result"), data.get("error")
        entry.timestamp_start = datetime.fromisoformat(data["timestamp_start"])
        entry.timestamp_end = datetime.fromisoformat(data["timestamp_end"]) if data.get("timestamp_end") else None
        entry.rollback_executed, entry.rollback_error = data.get("rollback_executed", False), data.get("rollback_error")
        return entry


def execute_rollback_for_step(log: ExecutionLog, tools_catalog: list[dict]) -> bool:
    """
    Esegue il rollback per un singolo step, usando info dichiarative e popolamento template.
    Ritorna True se successo, False se fallito.
    """
    tool_name = log.tool_name
    result = log.result
    step_id = log.step.get("id")

    rollback_info = get_rollback_info(tool_name)
    if not rollback_info or not rollback_info.get("reversible"):
        logger.warning(f"Step {step_id}: tool `{tool_name}` non è reversibile, impossibile rollback")
        log.rollback_executed = False
        log.rollback_error = "Tool non reversibile"
        return False

    rollback_tool = rollback_info.get("rollback_tool")
    rollback_args_template = rollback_info.get("rollback_args_template", {})

    if not rollback_tool:
        logger.error(f"Step {step_id}: rollback_info per `{tool_name}` non specifica rollback_tool")
        log.rollback_executed = False
        log.rollback_error = "Rollback tool non specificato"
        return False

    rollback_args = {}
    value_map = {}
    if isinstance(log.args, dict):
        value_map.update(log.args)
    if isinstance(result, dict):
        value_map.update(result)

    for arg_key, template_val in rollback_args_template.items():
        if isinstance(template_val, str):
            val_str = template_val
            for res_key, res_val in value_map.items():
                placeholder = f"{{{{{res_key}}}}}"
                if placeholder in val_str:
                    val_str = val_str.replace(placeholder, str(res_val))
            if "{{" in val_str and "}}" in val_str:
                raw_var = val_str.replace("{", "").replace("}", "").strip()
                extracted = extract_output_var(result, raw_var, step_id)
                if extracted is not None:
                    val_str = str(extracted)
            rollback_args[arg_key] = val_str
        else:
            rollback_args[arg_key] = template_val

    logger.info(f"Rollback step {step_id}: `{rollback_tool}` con args {rollback_args}")

    try:
        rollback_result = get_mcp_hub().call_tool(rollback_tool, rollback_args)
        if isinstance(rollback_result, dict) and "error" in rollback_result:
            log.rollback_executed = False
            log.rollback_error = rollback_result["error"]
            logger.error(f"Rollback fallito per step {step_id}: {rollback_result['error']}")
            return False
        else:
            log.rollback_executed = True
            logger.info(f"Rollback riuscito per step {step_id}")
            return True
    except Exception as e:
        log.rollback_executed = False
        log.rollback_error = str(e)
        logger.error(f"Eccezione nel rollback per step {step_id}: {e}")
        return False


def generate_rollback_plan_with_llm(execution_log: List[ExecutionLog], task: str, error_context: str, model: Optional[str] = None) -> Optional[str]:
    """
    Usa l'LLM per generare un piano di rollback contestuale quando quello dichiarativo non basta.
    """
    log_summary = "\n".join([
        f"- Step {e.step.get('id')}: `{e.tool_name}`({e.args}) → {'OK ' + json.dumps(e.result, default=str)[:200] if not e.error else 'ERROR: ' + str(e.error)}"
        for e in execution_log
    ])
    # Compensazioni dichiarate per i passi riusciti: il modello non deve indovinare nomi di tool
    known = [
        f"- `{e.tool_name}` → `{info['rollback_tool']}`"
        for e in execution_log
        if not e.error and (info := get_rollback_info(e.tool_name)).get("reversible") and info.get("rollback_tool")
    ]
    known_block = ("Known compensating tools:\n" + "\n".join(known) + "\n\n") if known else ""

    prompt = f"""Language Directive: Respond in the language used in the task.
An execution plan failed after these steps:
{log_summary}

Original task: {task}
Error context: {error_context}

{known_block}Generate a rollback plan to revert to the initial state. Only steps that succeeded (OK) changed the
state; the failed step needs no rollback. Undo them in reverse order, one numbered line per step:
the action, the tool (a known compensating tool when listed, otherwise "manual action") and its arguments.

Rollback plan:"""

    # Senza ragionamento: con il thinking attivo il modello esauriva i token prima di scrivere il piano
    plan_res = llm_calls.call_llm(prompt, system_prompt="You are an expert assistant for rollback operations on Proxmox infrastructure.", max_tokens=1024, temperature=0.3, model=model, stream_mode="none")
    plan = plan_res.get("content", "") if isinstance(plan_res, dict) else ""
    return plan.strip() if plan else None


class _PlanRun:
    """Esecuzione di un piano come Saga: passi in ordine, rollback al primo errore.

    Una richiesta di approvazione non è un errore: il piano si sospende sul passo, senza rollback, e riprende da lì quando
    l'utente decide (`resume`). Un rifiuto conta come errore del passo, quindi annulla i passi già eseguiti.
    """

    def __init__(self, plan_struct: Dict[str, Any], task: str, thread_id: Optional[str], security_mode: str,
                 model: Optional[str], meta: Optional[Dict[str, Any]] = None):
        self.plan_struct = plan_struct
        self.task = task
        self.thread_id = thread_id
        self.security_mode = security_mode
        self.model = model
        self.meta = meta or {}
        self.steps = topological_sort_steps(plan_struct.get("steps", []))
        self.index = 0
        self.context_vars: Dict[str, Any] = {}
        self.execution_log: List[ExecutionLog] = []
        self.exec_lines = [
            f"🚀 **Avvio esecuzione reale del piano MetaMCP**: *'{task}'*\n",
            "### Esito Esecuzione Tool Real-Time:\n"
        ]
        self.has_error = False

    def _checkpoint(self) -> Dict[str, Any]:
        return {
            "plan_struct": self.plan_struct, "task": self.task, "thread_id": self.thread_id, "security_mode": self.security_mode,
            "model": self.model, "meta": self.meta, "index": self.index, "context_vars": self.context_vars,
            "execution_log": [{"step": e.step, **e.to_dict()} for e in self.execution_log], "exec_lines": self.exec_lines,
        }

    @classmethod
    def restore(cls, state: Dict[str, Any]) -> "_PlanRun":
        run = cls(state["plan_struct"], state["task"], state["thread_id"], state["security_mode"], state["model"], state["meta"])
        run.index, run.context_vars, run.exec_lines = state["index"], state["context_vars"], state["exec_lines"]
        run.execution_log = [ExecutionLog.from_dict(e) for e in state["execution_log"]]
        return run

    def _resolve_args(self, args: Any) -> Dict[str, Any]:
        resolved = {}
        if isinstance(args, dict):
            for k, v in args.items():
                if isinstance(v, str):
                    val_str = v
                    for var_k, var_v in self.context_vars.items():
                        placeholder = f"{{{{{var_k}}}}}"
                        if placeholder in val_str:
                            val_str = val_str.replace(placeholder, str(var_v))
                    resolved[k] = val_str
                else:
                    resolved[k] = v
        return resolved

    def _record_result(self, step: Dict[str, Any], log_entry: ExecutionLog, result: Any) -> bool:
        """Registra il risultato del passo; False se il passo è fallito."""
        step_id, desc, tool_name = step.get("id", 1), step.get("description", ""), log_entry.tool_name
        log_entry.result = result
        log_entry.timestamp_end = datetime.now(UTC)
        logger.info(f"Step {step_id} completato: {result}")

        if isinstance(result, dict) and "error" in result:
            self.has_error = True
            log_entry.error = result["error"]
            self.exec_lines.append(f"{step_id}. ❌ `{desc}` — Tool `{tool_name}` fallito: `{result['error']}`")
            return False

        output_var = step.get("output_var")
        if output_var:
            extracted_val = extract_output_var(result, output_var, step_id)
            if extracted_val is not None:
                self.context_vars[output_var] = extracted_val

        args_str = json.dumps(log_entry.args, ensure_ascii=False) if log_entry.args else "{}"
        self.exec_lines.append(f"{step_id}. ✅ `{desc}` — `{tool_name}`({args_str}) → *OK*")
        return True

    def _suspend(self, step: Dict[str, Any], guard: Dict[str, Any]) -> Dict[str, Any]:
        """Il passo chiede conferma: salva lo stato del piano e chiude il turno in attesa della decisione."""
        turn_checkpoints.save(guard["request_id"], "plan", self._checkpoint())
        self.exec_lines.append(f"{step.get('id', 1)}. ⏸️ `{step.get('description', '')}` — In attesa di approvazione: "
                               f"`{guard.get('risk_reason')}`")
        approval = {
            "approval_required": True,
            "request_id": guard["request_id"],
            "approval_prompt": guard.get("message"),
            "command_preview": guard.get("command_preview"),
            "command_prefix": guard.get("command_prefix"),
            "risk_reason": guard.get("risk_reason"),
        }
        log_dicts = [log.to_dict() for log in self.execution_log]
        log_dicts[-1].update(approval)
        answer = "\n".join(self.exec_lines)
        return {"plan": {"mode": "act", "tool_needed": True, "direct_answer": answer, "execution_log": log_dicts},
                "plan_structure": self.plan_struct, "execution_trace": log_dicts, "final_response": answer, **approval}

    def advance(self) -> Dict[str, Any]:
        """Esegue i passi dall'indice corrente fino alla fine, al primo errore o a una richiesta di approvazione."""
        while self.index < len(self.steps):
            step = self.steps[self.index]
            step_id, desc, tool_name = step.get("id", 1), step.get("description", ""), step.get("tool", "")
            logger.info(f"Esecuzione step {step_id} (dipende da: {step.get('depends_on')}): {tool_name}")
            resolved_args = self._resolve_args(step.get("args", {}))

            # Log entry creata PRIMA dell'esecuzione (Write-Ahead Logging / WAL)
            log_entry = ExecutionLog(step, tool_name, resolved_args)
            self.execution_log.append(log_entry)

            # Verifica guardrail di sicurezza e autorizzazioni
            guard = policy.enforce_guardrails(tool_name, resolved_args, thread_id=self.thread_id, mode="plan",
                                              security_mode=self.security_mode, task=self.task)
            if guard:
                if guard.get("blocked"):
                    self.has_error = True
                    log_entry.error = guard["reason"]
                    self.exec_lines.append(f"{step_id}. ⛔ `{desc}` — Bloccato dal guardrail di sicurezza: `{guard['reason']}`")
                    break
                if guard.get("approval_required"):
                    return self._suspend(step, guard)

            try:
                if not self._record_result(step, log_entry, get_mcp_hub().call_tool(tool_name, resolved_args)):
                    break
            except Exception as e:
                self.has_error = True
                log_entry.error = str(e)
                log_entry.timestamp_end = datetime.now(UTC)
                logger.error(f"Step {step_id} fallito con eccezione: {e}")
                self.exec_lines.append(f"{step_id}. ❌ `{desc}` — Errore di chiamata tool `{tool_name}`: `{e}`")
                break
            self.index += 1
        return self._finish()

    def resume(self, request_id: str, approved: bool) -> Dict[str, Any]:
        """Riprende dal passo in attesa: approvato lo esegue e prosegue, rifiutato annulla i passi già eseguiti."""
        step, log_entry = self.steps[self.index], self.execution_log[-1]
        step_id, desc = step.get("id", 1), step.get("description", "")
        self.exec_lines = [line for line in self.exec_lines if "⏸️" not in line]

        if not approved:
            self.has_error = True
            log_entry.error = "Rifiutato dall'utente"
            log_entry.timestamp_end = datetime.now(UTC)
            self.exec_lines.append(f"{step_id}. 🛑 `{desc}` — Rifiutato dall'utente")
            return self._finish()

        request = approvals.approved_request_for(request_id, log_entry.tool_name, log_entry.args, self.thread_id, "plan")
        result = get_registry_manager().execute_tool(
            log_entry.tool_name, log_entry.args, get_mode_policy("act").allowed_registries, thread_id=self.thread_id, mode="plan",
            security_mode=self.security_mode, task=self.task, approved_request=request)
        if isinstance(result, dict) and result.get("approval_required"):
            return self._suspend(step, result)
        if self._record_result(step, log_entry, result):
            self.index += 1
            return self.advance()
        return self._finish()

    def _finish(self) -> Dict[str, Any]:
        """Rollback dichiarativo in ordine inverso se un passo è fallito (LIFO Undo Stack), poi l'esito del piano."""
        if self.has_error and self.execution_log:
            self.exec_lines.append("\n### 🔄 Rollback parziale degli step eseguiti:\n")
            tools_catalog = get_tool_catalog()

            for log_entry in reversed(self.execution_log):
                if not log_entry.error:  # Rollback solo degli step eseguiti con successo
                    success = execute_rollback_for_step(log_entry, tools_catalog)
                    step_id = log_entry.step.get("id")
                    if success:
                        self.exec_lines.append(f"  ✅ Rollback step {step_id}: `{log_entry.tool_name}`")
                    else:
                        self.exec_lines.append(f"  ❌ Rollback FALLITO/SKIPPATO step {step_id}: `{log_entry.tool_name}` — {log_entry.rollback_error}")

            # Se alcuni rollback dichiarativi falliscono o non sono reversibili, attiva LLM Rollback Planning
            failed_rollbacks = [e for e in self.execution_log if not e.rollback_executed and not e.error]
            if failed_rollbacks:
                self.exec_lines.append("\n### 🤖 LLM-based Rollback Planning:\n")
                error_ctx = "Step non reversibili o rollback dichiarativo non completato"
                llm_plan = generate_rollback_plan_with_llm(self.execution_log, self.task, error_ctx, model=self.model)
                if llm_plan:
                    self.exec_lines.append(f"```\n{llm_plan}\n```")
                    self.exec_lines.append("\n⚠️ **Piano LLM generato: esegui manualmente i passaggi sopra se necessario.**")

            self.exec_lines.append("\n⚠️ **Rollback parziale completato. Verifica dello stato raccomandata.**")

        if not self.has_error:
            self.exec_lines.append("\n🎉 **Tutti i passaggi del piano sono stati eseguiti con successo su Proxmox!**")

        ans = "\n".join(self.exec_lines)
        log_dicts = [log.to_dict() for log in self.execution_log]
        plan = {"mode": "act", "tool_needed": True, "direct_answer": ans, "execution_log": log_dicts}
        return {"plan": plan, "plan_structure": self.plan_struct, "execution_trace": log_dicts, "final_response": ans}


def execute_plan(
    plan_struct: Dict[str, Any],
    *,
    task: str,
    thread_id: Optional[str],
    security_mode: str,
    model: Optional[str],
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Esegue in sequenza gli step di plan_struct sui tool MetaMCP: al primo errore annulla gli step completati, a una richiesta
    di approvazione si sospende (`resume_plan`)."""
    return _PlanRun(plan_struct, task, thread_id, security_mode, model, meta).advance()


def resume_plan(state: Dict[str, Any], request_id: str, approved: bool) -> Dict[str, Any]:
    """Riprende il piano sospeso su `request_id`, con lo stato salvato da `_PlanRun`."""
    return _PlanRun.restore(state).resume(request_id, approved)
