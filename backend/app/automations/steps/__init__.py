"""Gestori degli step delle automazioni: un modulo per tipo, scelto da `select_handler`."""
from typing import Callable

from app.automations.models import StepType, WorkflowStepDefinition
from app.automations.steps import agentic, approval, calendar_action, custom_code, tool_action
from app.automations.steps.base import Outcome, StepContext, completed

StepHandler = Callable[[StepContext], Outcome]


def _evaluation_gate(ctx: StepContext) -> Outcome:
    return completed({"evaluation": "passed"})


def select_handler(step: WorkflowStepDefinition) -> StepHandler:
    """Gestore dello step. Un'azione deterministica su uno script `.py` o su `calendar_*`
    va ai gestori di codice e calendario; `requires_approval` trasforma qualunque step in un gate."""
    tool = step.action_or_tool or ""
    deterministic = step.type == StepType.DETERMINISTIC_ACTION

    if step.type == StepType.APPROVAL_GATE or step.requires_approval:
        return approval.run
    if step.type == StepType.CUSTOM_CODE or (deterministic and (tool.endswith(".py") or tool == "custom_code")):
        return custom_code.run
    if step.type == StepType.CALENDAR or (deterministic and tool.startswith(("calendar_", "calendar."))):
        return calendar_action.run
    if deterministic:
        return tool_action.run
    if step.type == StepType.AGENTIC_TASK:
        return agentic.run
    if step.type == StepType.EVALUATION_GATE:
        return _evaluation_gate
    raise NotImplementedError(f"Tipo di step '{step.type}' non supportato.")


__all__ = ["Outcome", "StepContext", "StepHandler", "select_handler"]
