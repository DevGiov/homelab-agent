"""Esecuzione dei piani multi-step come Saga: log write-ahead per step e rollback LIFO (dichiarativo, poi LLM)."""
import json
import logging
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from app.agent import llm_calls
from app.agent.tool_catalog import get_rollback_info, get_tool_catalog
from app.mcp.hub import get_mcp_hub
from app.security import policy

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


def execute_plan(
    plan_struct: Dict[str, Any],
    *,
    task: str,
    thread_id: Optional[str],
    security_mode: str,
    model: Optional[str],
) -> Dict[str, Any]:
    """Esegue in sequenza gli step di plan_struct sui tool MetaMCP; al primo errore annulla gli step completati."""
    steps = plan_struct.get("steps", [])
    sorted_steps = topological_sort_steps(steps)

    context_vars = {}
    execution_log: List[ExecutionLog] = []
    exec_lines = [
        f"🚀 **Avvio esecuzione reale del piano MetaMCP**: *'{task}'*\n",
        "### Esito Esecuzione Tool Real-Time:\n"
    ]

    has_error = False

    for step in sorted_steps:
        step_id = step.get("id", 1)
        depends_on = step.get("depends_on")
        desc = step.get("description", "")
        tool_name = step.get("tool", "")
        args = step.get("args", {})
        output_var = step.get("output_var")

        logger.info(f"Esecuzione step {step_id} (dipende da: {depends_on}): {tool_name}")

        resolved_args = {}
        if isinstance(args, dict):
            for k, v in args.items():
                if isinstance(v, str):
                    val_str = v
                    for var_k, var_v in context_vars.items():
                        placeholder = f"{{{{{var_k}}}}}"
                        if placeholder in val_str:
                            val_str = val_str.replace(placeholder, str(var_v))
                    resolved_args[k] = val_str
                else:
                    resolved_args[k] = v

        # Log entry creata PRIMA dell'esecuzione (Write-Ahead Logging / WAL)
        log_entry = ExecutionLog(step, tool_name, resolved_args)
        execution_log.append(log_entry)

        # Verifica guardrail di sicurezza e autorizzazioni
        guard = policy.enforce_guardrails(
            tool_name,
            resolved_args,
            thread_id=thread_id,
            mode="plan",
            security_mode=security_mode,
            task=task,
        )
        if guard:
            if guard.get("blocked"):
                has_error = True
                err_msg = guard["reason"]
                log_entry.error = err_msg
                exec_lines.append(f"{step_id}. ⛔ `{desc}` — Bloccato dal guardrail di sicurezza: `{err_msg}`")
                break
            if guard.get("approval_required"):
                has_error = True
                err_msg = guard["message"]
                log_entry.error = err_msg
                exec_lines.append(f"{step_id}. ⚠️ `{desc}` — Richiede approvazione utente: `{guard.get('risk_reason')}` (ID: {guard.get('request_id')})")
                break

        try:
            result = get_mcp_hub().call_tool(tool_name, resolved_args)
            log_entry.result = result
            log_entry.timestamp_end = datetime.now(UTC)
            logger.info(f"Step {step_id} completato: {result}")

            if isinstance(result, dict) and "error" in result:
                has_error = True
                err_msg = result["error"]
                log_entry.error = err_msg
                exec_lines.append(f"{step_id}. ❌ `{desc}` — Tool `{tool_name}` fallito: `{err_msg}`")
                break

            if output_var:
                extracted_val = extract_output_var(result, output_var, step_id)
                if extracted_val is not None:
                    context_vars[output_var] = extracted_val

            args_str = json.dumps(resolved_args, ensure_ascii=False) if resolved_args else "{}"
            exec_lines.append(f"{step_id}. ✅ `{desc}` — `{tool_name}`({args_str}) → *OK*")
        except Exception as e:
            has_error = True
            log_entry.error = str(e)
            log_entry.timestamp_end = datetime.now(UTC)
            logger.error(f"Step {step_id} fallito con eccezione: {e}")
            exec_lines.append(f"{step_id}. ❌ `{desc}` — Errore di chiamata tool `{tool_name}`: `{e}`")
            break

    # Rollback dichiarativo in ordine inverso (LIFO Undo Stack)
    if has_error and execution_log:
        exec_lines.append("\n### 🔄 Rollback parziale degli step eseguiti:\n")
        tools_catalog = get_tool_catalog()

        for log_entry in reversed(execution_log):
            if not log_entry.error:  # Rollback solo degli step eseguiti con successo
                success = execute_rollback_for_step(log_entry, tools_catalog)
                step_id = log_entry.step.get("id")
                if success:
                    exec_lines.append(f"  ✅ Rollback step {step_id}: `{log_entry.tool_name}`")
                else:
                    exec_lines.append(f"  ❌ Rollback FALLITO/SKIPPATO step {step_id}: `{log_entry.tool_name}` — {log_entry.rollback_error}")

        # Se alcuni rollback dichiarativi falliscono o non sono reversibili, attiva LLM Rollback Planning
        failed_rollbacks = [e for e in execution_log if not e.rollback_executed and not e.error]
        if failed_rollbacks:
            exec_lines.append("\n### 🤖 LLM-based Rollback Planning:\n")
            error_ctx = "Step non reversibili o rollback dichiarativo non completato"
            llm_plan = generate_rollback_plan_with_llm(execution_log, task, error_ctx, model=model)
            if llm_plan:
                exec_lines.append(f"```\n{llm_plan}\n```")
                exec_lines.append("\n⚠️ **Piano LLM generato: esegui manualmente i passaggi sopra se necessario.**")

        exec_lines.append("\n⚠️ **Rollback parziale completato. Verifica dello stato raccomandata.**")

    if not has_error:
        exec_lines.append("\n🎉 **Tutti i passaggi del piano sono stati eseguiti con successo su Proxmox!**")

    ans = "\n".join(exec_lines)
    log_dicts = [log.to_dict() for log in execution_log]
    plan = {"mode": "act", "tool_needed": True, "direct_answer": ans, "execution_log": log_dicts}
    return {"plan": plan, "plan_structure": plan_struct, "execution_trace": log_dicts, "final_response": ans}
