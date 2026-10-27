"""Step di codice Python custom, eseguito nel sandbox `SandboxedCodeRunner`."""
import os
import uuid

from app.automations.code_runner import SandboxedCodeRunner
from app.automations.db import artifacts as artifacts_db
from app.automations.steps.base import Outcome, StepContext, completed, failed
from app.automations.templating import resolve_parameters
from app.core.config import settings

DEFAULT_TIMEOUT_SECONDS = 60


def run(ctx: StepContext) -> Outcome:
    step = ctx.step
    script_path = step.parameters.get("script_path") or step.action_or_tool

    if ctx.run.is_dry_run:
        return completed({"dry_run": True, "simulated_code": script_path},
                         [{"tool_name": "custom_code", "script": script_path, "dry_run": True}])

    code_res = SandboxedCodeRunner().run_script(
        script_path=script_path,
        context_payload={
            "automation_id": ctx.automation.id,
            "run_id": ctx.run.run_id,
            "step_id": step.step_id,
            "inputs": resolve_parameters(step.parameters, ctx.data),
            "step_outputs": ctx.data.get("steps", {}),
            "artifacts_dir": os.path.join(settings.artifacts_dir, ctx.run.run_id),
        },
        entrypoint_func=step.parameters.get("entrypoint"),
        timeout_seconds=step.timeout_seconds or DEFAULT_TIMEOUT_SECONDS,
        secrets_whitelist=ctx.automation.permission_policy.secrets_whitelist,
    )

    for art in code_res.get("artifacts", []):
        artifacts_db.save_artifact({
            "artifact_id": f"art_{uuid.uuid4().hex[:8]}",
            "run_id": ctx.run.run_id,
            "step_run_id": ctx.step_run_id,
            "name": art["name"],
            "type": art.get("type", "report"),
            "mime_type": art.get("mime_type", "text/plain"),
            "storage_uri": art["storage_uri"],
            "checksum_sha256": art.get("checksum_sha256"),
        }, db_path=ctx.db_path)

    tool_calls = [{"tool_name": "custom_code", "script": script_path, "result": code_res}]
    if not code_res.get("success"):
        return failed(code_res.get("error", "Errore esecuzione codice custom"), code_res.get("output"), tool_calls)
    return completed(code_res.get("output"), tool_calls)
