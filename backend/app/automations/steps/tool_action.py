"""Step deterministico: un tool del registry con parametri risolti, sotto guardrail e audit."""
from app.automations.steps.base import Outcome, StepContext, completed, failed, waiting_approval
from app.automations.templating import resolve_parameters

# Nomi con cui i template e gli LLM chiedono il salvataggio di un report: tutti equivalgono a save_artifact
ARTIFACT_TOOL_ALIASES = {"file_write", "write_file", "save_file", "save_report", "save_briefing_artifact"}


def _allowed_tools(policy_tools) -> set:
    allowed = set(policy_tools or [])
    if allowed & (ARTIFACT_TOOL_ALIASES | {"save_artifact"}):
        allowed |= ARTIFACT_TOOL_ALIASES | {"save_artifact"}
    return allowed


def run(ctx: StepContext) -> Outcome:
    step, automation, run_ = ctx.step, ctx.automation, ctx.run
    tool_name = step.action_or_tool
    if not tool_name:
        raise ValueError(f"Step '{step.step_id}' non specifica 'action_or_tool'.")
    if tool_name in ARTIFACT_TOOL_ALIASES:
        tool_name = "save_artifact"

    policy = automation.permission_policy
    if policy.allowed_tools and tool_name not in _allowed_tools(policy.allowed_tools):
        raise PermissionError(f"Tool '{tool_name}' non autorizzato dalla policy dell'automazione.")

    params = resolve_parameters(step.parameters, ctx.data)
    params.update({"run_id": run_.run_id, "step_run_id": ctx.step_run_id,
                   "_run_id": run_.run_id, "_step_run_id": ctx.step_run_id})

    if run_.is_dry_run:
        return completed({"dry_run": True, "simulated_tool": tool_name, "parameters": params},
                         [{"tool_name": tool_name, "args": params, "dry_run": True}])

    res = ctx.registry_manager.execute_tool(
        tool_name,
        params,
        allowed_registries=policy.allowed_registries,
        thread_id=run_.associated_thread_id,
        mode="act",
        security_mode=policy.security_mode,
        task=f"Automation {automation.name} Step {step.name}",
        automation_id=automation.id,
        run_id=run_.run_id,
        step_run_id=ctx.step_run_id,
    )
    tool_calls = [{"tool_name": tool_name, "args": params, "result": res}]

    if isinstance(res, dict):
        if res.get("approval_required"):
            return waiting_approval(res.get("request_id"), res, tool_calls)
        if res.get("blocked_by_guardrail"):
            return failed(f"Azione bloccata categoricamente dal guardrail di sicurezza: {res.get('error')}", res, tool_calls)
        if res.get("error"):
            return failed(f"Errore esecuzione tool '{tool_name}': {res.get('error')}", res, tool_calls)
    return completed(res, tool_calls)
