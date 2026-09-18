"""Homelab Agent Python SDK per Automations & Loops (Milestone M5).

Fornisce decoratori e contesti di runtime isolati per definire workflow
in codice Python nativo con accesso scoped ai secret e sandboxing.
"""

from sdk.context import AutomationContext, StepResult
from sdk.decorators import StepMetadata, WorkflowMetadata, step, workflow

__all__ = [
    "workflow",
    "step",
    "AutomationContext",
    "StepResult",
    "StepMetadata",
    "WorkflowMetadata",
]
