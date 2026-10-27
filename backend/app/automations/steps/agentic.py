"""Step agentico: prompt renderizzato, dati dello step precedente in input, agent loop in modalità act."""
from typing import Tuple

from app.agent.agent_loop import run_agent_loop
from app.agent.llm_calls import call_llm
from app.automations.steps.base import Outcome, StepContext, completed
from app.automations.templating import extract_step_content, render_template

MAX_TOKENS = 2048


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


def _call_llm(prompt, system_prompt=None, reasoning_budget=0, model=None, reasoning_phase=None):
    # Sintesi diretta, senza thinking né streaming verso la UI
    return call_llm(prompt, system_prompt=system_prompt, max_tokens=MAX_TOKENS, reasoning_budget=0, model=model,
                    stream_mode="none")


def run(ctx: StepContext) -> Outcome:
    prompt = render_template(ctx.step.prompt_template or "", ctx.data)
    source, data = _input_data(ctx)
    if data:
        prompt = f"{prompt}\n\n--- DATI DI INPUT (da Step: {source}) ---\n{data}\n--- FINE DATI DI INPUT ---"

    if ctx.run.is_dry_run:
        return completed({"dry_run": True, "prompt_preview": prompt[:500]})

    loop_res = run_agent_loop(
        task=prompt,
        mode="act",
        security_mode=ctx.automation.permission_policy.security_mode,
        call_llm_fn=_call_llm,
        call_llm_structured_fn=None,
    )
    final_text = loop_res.get("final_response", "")
    # Stima: l'agent loop non restituisce il conteggio reale dei token
    estimated_tokens = int(len(prompt.split()) * 1.3) + int(len(final_text.split()) * 1.3)
    return completed({"text": final_text}, loop_res.get("execution_trace", []), estimated_tokens)
