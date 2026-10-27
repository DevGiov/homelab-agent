"""Approval gate: sospende la run finché un utente non approva lo step."""
import uuid
from datetime import datetime, timedelta, timezone

from app.automations.db import approvals as approvals_db
from app.automations.steps.base import Outcome, StepContext, waiting_approval

APPROVAL_TTL = timedelta(hours=24)


def run(ctx: StepContext) -> Outcome:
    step = ctx.step
    request_id = f"apr_{uuid.uuid4().hex[:12]}"
    approvals_db.create_automation_approval({
        "request_id": request_id,
        "run_id": ctx.run.run_id,
        "step_run_id": ctx.step_run_id,
        "tool_name": step.action_or_tool or "manual_approval_gate",
        "arguments": step.parameters,
        "command_preview": f"Step '{step.name}' richiede conferma esplicita",
        "risk_reason": f"Approval Gate richiesto dalla definizione del workflow per '{step.name}'",
        "status": "pending",
        "expires_at": (datetime.now(timezone.utc) + APPROVAL_TTL).isoformat(),
    }, db_path=ctx.db_path)
    return waiting_approval(request_id)
