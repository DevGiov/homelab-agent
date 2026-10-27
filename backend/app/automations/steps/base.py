"""Contesto ed esiti condivisi dai gestori degli step.

Un gestore riceve uno `StepContext` e restituisce un esito: un dict con `status`, `output`,
`tokens`, `tool_calls` e, a seconda dello stato, `error_message` o `approval_request_id`.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.automations.models import AutomationDefinition, AutomationRun, RunStatus, WorkflowStepDefinition
from app.registry.manager import ToolRegistryManager

Outcome = Dict[str, Any]


@dataclass
class StepContext:
    step: WorkflowStepDefinition
    automation: AutomationDefinition
    run: AutomationRun
    # inputs, config, secrets, output degli step completati ("steps"), run_id, automation_id
    data: Dict[str, Any]
    registry_manager: ToolRegistryManager
    db_path: Optional[str] = None

    @property
    def step_run_id(self) -> str:
        return f"sr_{self.run.run_id}_{self.step.step_id}"


def completed(output: Any, tool_calls: Optional[List[Dict[str, Any]]] = None, tokens: int = 0) -> Outcome:
    return {"status": RunStatus.COMPLETED, "output": output, "tokens": tokens, "tool_calls": tool_calls or []}


def failed(error_message: str, output: Any = None, tool_calls: Optional[List[Dict[str, Any]]] = None) -> Outcome:
    return {"status": RunStatus.FAILED, "error_message": error_message, "output": output, "tokens": 0,
            "tool_calls": tool_calls or []}


def waiting_approval(request_id: Optional[str], output: Any = None,
                     tool_calls: Optional[List[Dict[str, Any]]] = None) -> Outcome:
    return {"status": RunStatus.WAITING_APPROVAL, "approval_request_id": request_id, "output": output, "tokens": 0,
            "tool_calls": tool_calls or []}
