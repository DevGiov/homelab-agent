"""Step agentico: prompt renderizzato, dati dello step precedente in input, agent loop in modalità act.

Il loop lavora dentro i limiti dell'automazione: registry e allowlist della policy (ristretta da `step.tools`), tool al massimo
`budget.max_tool_calls`, modalità di sicurezza della policy. Se un tool chiede conferma lo step si sospende: lo stato del loop
resta salvato con la richiesta e riprende quando l'utente decide, anche dopo un rifiuto.
"""
import json
from typing import Any, Dict, Optional, Set, Tuple

from app.agent import llm_calls, turn_checkpoints
from app.agent.agent_loop import AgentLoop, run_agent_loop
from app.automations.steps.base import Outcome, StepContext, completed, failed, waiting_approval
from app.automations.steps.tool_action import allowed_tools
from app.automations.templating import extract_step_content, render_template
from app.llm.providers import resolve_model
from app.security import approvals

# Senza allowlist esplicita lo step non gestisce le automazioni stesse: potrebbe rilanciarsi o riscriversi
AUTOMATION_MANAGEMENT_TOOLS = {"trigger_automation_run", "create_automation_from_template", "create_custom_automation", "update_automation"}


def _input_data(ctx: StepContext) -> Tuple[str, str]:
    """(nome sorgente, contenuto) da `input_source` o, se il prompt non cita step, dall'ultimo step completato."""
    step = ctx.step
    input_source = step.parameters.get("input_source") if step.parameters else None
    if input_source:
        return str(input_source), extract_step_content(str(input_source), ctx.data)
    if "{{steps." in (step.prompt_template or ""):
        return "", ""
    completed_steps = ctx.data.get("steps", {})
    for step_id in reversed([s.step_id for s in ctx.automation.workflow.steps if s.step_id != step.step_id]):
        if step_id in completed_steps:
            content = extract_step_content(step_id, ctx.data)
            if content:
                return step_id, content
    return "", ""


def _tool_scope(ctx: StepContext) -> Set[str]:
    """Tool che lo step può usare: `step.tools` dentro l'allowlist della policy; un'allowlist vuota vale tutto il catalogo
    dei registry dell'automazione, tranne la gestione delle automazioni."""
    policy = ctx.automation.permission_policy
    if policy.allowed_tools:
        scope = allowed_tools(policy.allowed_tools)
    else:
        catalog = ctx.registry_manager.get_tools_for_mode(policy.allowed_registries)
        scope = {t["name"] for t in catalog} - AUTOMATION_MANAGEMENT_TOOLS
    return scope if ctx.step.tools is None else scope & set(ctx.step.tools)


def _outcome(ctx: StepContext, prompt: str, model: Optional[str], result: Dict[str, Any]) -> Outcome:
    trace = result.get("execution_trace", [])
    if result.get("approval_required"):
        request_id = result.get("request_id")
        approvals.bind_to_run(request_id, ctx.run.run_id, ctx.step_run_id, db_path=ctx.db_path)
        return waiting_approval(request_id, {"text": result.get("approval_prompt"), "model": model}, trace)
    final_text = result.get("final_response", "")
    if result.get("llm_unavailable"):
        return failed(final_text, {"model": model}, trace)
    # Stima: l'agent loop non restituisce il conteggio reale dei token
    estimated_tokens = int(len((prompt + json.dumps(trace, default=str)).split()) * 1.3) + int(len(final_text.split()) * 1.3)
    # L'etichetta della risposta: gli step successivi che la leggono la ereditano (AutomationRunner._step_tag)
    return completed({"text": final_text, "model": model, "sensitivity": result.get("tag")}, trace, estimated_tokens)


def _resume(ctx: StepContext) -> Outcome:
    request_id = ctx.resume["request_id"]
    checkpoint = turn_checkpoints.load(request_id)
    if not checkpoint:
        return failed(f"Stato dello step sospeso sulla richiesta '{request_id}' non trovato: va rieseguita la run.")
    turn_checkpoints.delete(request_id)
    state = checkpoint["state"]
    model = state["constructor"]["meta"].get("model")
    fns = llm_calls.agent_loop_llm_fns(None, model, None)
    loop = AgentLoop.restore(state, fns["call_llm_fn"], fns["call_llm_structured_fn"])
    return _outcome(ctx, state["constructor"]["task"], model, loop.resume(request_id, ctx.resume["approved"]))


def run(ctx: StepContext) -> Outcome:
    if ctx.resume:
        return _resume(ctx)

    prompt = render_template(ctx.step.prompt_template or "", ctx.data)
    source, data = _input_data(ctx)
    if data:
        prompt = f"{prompt}\n\n--- DATI DI INPUT (da Step: {source}) ---\n{data}\n--- FINE DATI DI INPUT ---"

    if ctx.run.is_dry_run:
        return completed({"dry_run": True, "prompt_preview": prompt[:500]})

    # Il modello caricato si sceglie ora, all'esecuzione dello step (None = default del provider)
    model = resolve_model(ctx.automation.model)
    policy = ctx.automation.permission_policy
    result = run_agent_loop(
        task=prompt,
        mode="act",
        thread_id=ctx.run.associated_thread_id,
        security_mode=policy.security_mode,
        allowed_tools=_tool_scope(ctx),
        allowed_registries=policy.allowed_registries,
        max_tool_calls=ctx.automation.budget.max_tool_calls,
        audit={"automation_id": ctx.automation.id, "run_id": ctx.run.run_id, "step_run_id": ctx.step_run_id},
        meta={"model": model},
        checkpoint_kind="automation_step",
        tag=ctx.data.get("tag"),
        **llm_calls.agent_loop_llm_fns(None, model, None),
    )
    return _outcome(ctx, prompt, model, result)
