"""Modelli di dominio Pydantic per Automations & Loops.

Include schemi canonici validati per definizioni, workflow, policy,
budget, run, step ed esecuzioni.
"""

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class SourceType(str, Enum):
    UI = "ui"
    AGENT = "agent"
    CODE = "code"
    IMPORTED = "imported"


class TriggerType(str, Enum):
    CRON = "cron"
    WEBHOOK = "webhook"
    MANUAL = "manual"
    EVENT = "event"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    EXHAUSTED = "exhausted"


class StepType(str, Enum):
    DETERMINISTIC_ACTION = "deterministic_action"
    AGENTIC_TASK = "agentic_task"
    APPROVAL_GATE = "approval_gate"
    EVALUATION_GATE = "evaluation_gate"
    CUSTOM_CODE = "custom_code"


# --- Policy & Budget ---

class Budget(BaseModel):
    max_duration_seconds: int = Field(default=300, ge=1, description="Timeout globale della run in secondi")
    max_llm_calls: int = Field(default=10, ge=0, description="Numero massimo chiamate LLM")
    max_tool_calls: int = Field(default=25, ge=0, description="Numero massimo invocazioni tool")
    max_tokens: int = Field(default=50000, ge=0, description="Tetto massimo di token consumabili")
    max_cost_usd: float = Field(default=0.0, ge=0.0, description="Budget di spesa stimato")
    max_retries_per_step: int = Field(default=2, ge=0, description="Tentativi di retry ammessi per step")


class ExecutionPolicy(BaseModel):
    execution_identity: str = Field(default="automation-default-sa", description="Identità/Service Account per permessi")
    allowed_tools: List[str] = Field(default_factory=list, description="Allowlist rigida di tool invocabili")
    allowed_registries: List[str] = Field(default_factory=lambda: ["metamcp", "web", "code", "memory", "vision", "email", "automations"])
    security_mode: str = Field(default="normal", description="safest | normal | dangerous")
    require_approval_for: List[str] = Field(default_factory=list, description="Azioni che forzano l'approval gate")
    target_scopes: Dict[str, List[str]] = Field(
        default_factory=lambda: {"allowed_containers": [], "allowed_repos": [], "allowed_recipients": []},
        description="Perimetrazione di sicurezza per container, repository e destinatari autorizzati"
    )
    secrets_whitelist: List[str] = Field(default_factory=list, description="Nomi dei secret accessibili")
    dry_run_supported: bool = Field(default=True, description="Indica se l'automazione supporta la modalità anteprima")


class NotificationPolicy(BaseModel):
    on_success: bool = Field(default=False)
    on_failure: bool = Field(default=True)
    on_approval_needed: bool = Field(default=True)
    channels: List[str] = Field(default_factory=lambda: ["ui_inbox"])
    destination_webhook: Optional[str] = None


# --- Definizione & Workflow ---

class Trigger(BaseModel):
    id: str
    type: TriggerType
    cron_expression: Optional[str] = None
    timezone: str = "Europe/Rome"
    webhook_path: Optional[str] = None
    webhook_secret_ref: Optional[str] = None
    event_pattern: Optional[Dict[str, Any]] = None
    enabled: bool = True


class WorkflowStepDefinition(BaseModel):
    step_id: str
    name: str
    type: StepType
    action_or_tool: Optional[str] = None
    prompt_template: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    condition: Optional[str] = None
    on_failure_step_id: Optional[str] = None
    timeout_seconds: int = Field(default=60, ge=1)
    idempotency_key_template: Optional[str] = None


class WorkflowSpec(BaseModel):
    initial_step_id: str
    steps: List[WorkflowStepDefinition]
    output_schema: Optional[Dict[str, Any]] = None


class AutomationDefinition(BaseModel):
    id: str
    name: str
    description: str = ""
    version: int = 1
    enabled: bool = True
    triggers: List[Trigger] = Field(default_factory=list)
    workflow: WorkflowSpec
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parametri e variabili configurabili per l'automazione")
    input_schema: Optional[Dict[str, Any]] = None
    permission_policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
    budget: Budget = Field(default_factory=Budget)
    notification_policy: NotificationPolicy = Field(default_factory=NotificationPolicy)
    created_by: str = "user"
    source_type: SourceType = SourceType.UI
    source_reference: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_proposal(cls, data: Any) -> Any:
        """Normalizza tollerantemente payload raw generati da LLM o client UI."""
        if not isinstance(data, dict):
            return data
        d = dict(data)

        # 1. Normalizzazione ID e nome
        if not d.get("id"):
            import uuid
            d["id"] = f"auto_{uuid.uuid4().hex[:8]}"
        if not d.get("name"):
            d["name"] = d.get("id", "Nuova Automazione")

        # 1.1 Normalizzazione Parametri
        raw_params = d.get("parameters") or d.get("params") or d.get("inputs") or d.get("config") or {}
        if isinstance(raw_params, dict):
            d["parameters"] = dict(raw_params)
        else:
            d["parameters"] = {}

        # 2. Normalizzazione Workflow (array -> oggetto WorkflowSpec)
        wf = d.get("workflow")
        if isinstance(wf, list):
            steps = list(wf)
            initial_id = steps[0].get("step_id", "step_1") if (steps and isinstance(steps[0], dict)) else "step_1"
            d["workflow"] = {"initial_step_id": initial_id, "steps": steps}
        elif isinstance(wf, dict):
            wf = dict(wf)
            if not wf.get("initial_step_id") and wf.get("steps"):
                first_step = wf["steps"][0]
                if isinstance(first_step, dict):
                    wf["initial_step_id"] = first_step.get("step_id", "step_1")
            d["workflow"] = wf
        elif not wf and "steps" in d:
            steps = list(d.pop("steps", []))
            initial_id = steps[0].get("step_id", "step_1") if (steps and isinstance(steps[0], dict)) else "step_1"
            d["workflow"] = {"initial_step_id": initial_id, "steps": steps}

        # 2.1 Template Expansion Auto-Fix: se il workflow ha un singolo step con action che coincide con un template noto
        if isinstance(d.get("workflow"), dict) and "steps" in d["workflow"]:
            cur_steps = d["workflow"]["steps"]
            if len(cur_steps) == 1 and isinstance(cur_steps[0], dict):
                act = str(cur_steps[0].get("action_or_tool") or cur_steps[0].get("action") or "").lower()
                clean_act = act.replace("-", "_")
                from pathlib import Path
                tpl_dir = Path(__file__).parent / "templates"
                if tpl_dir.exists():
                    for tpl_file in tpl_dir.glob("*.json"):
                        stem_clean = tpl_file.stem.lower().replace("-", "_")
                        if (stem_clean in clean_act or clean_act in stem_clean) and len(clean_act) >= 5:
                            try:
                                with open(tpl_file, "r", encoding="utf-8") as tf:
                                    tpl_data = json.load(tf)
                                    if "workflow" in tpl_data and "steps" in tpl_data["workflow"]:
                                        d["workflow"]["steps"] = tpl_data["workflow"]["steps"]
                                        d["workflow"]["initial_step_id"] = tpl_data["workflow"].get("initial_step_id", "step_1")
                                        if "permission_policy" in tpl_data:
                                            d["permission_policy"] = tpl_data["permission_policy"]
                                        break
                            except Exception:
                                pass

        # 3. Normalizzazione Steps all'interno del workflow
        if isinstance(d.get("workflow"), dict) and "steps" in d["workflow"]:
            norm_steps = []
            for idx, s in enumerate(d["workflow"].get("steps", [])):
                if not isinstance(s, dict):
                    continue
                s = dict(s)
                if not s.get("step_id"):
                    s["step_id"] = s.get("id") or f"step_{idx+1}"
                if not s.get("name"):
                    s["name"] = s.get("title") or s.get("step_id") or f"Step {idx+1}"
                if not s.get("action_or_tool"):
                    s["action_or_tool"] = s.get("action") or s.get("tool")
                if not s.get("parameters"):
                    s["parameters"] = s.get("params") or {}
                # Normalizza input_source e content_source sia da top-level che da parameters
                if "input_source" in s and "input_source" not in s["parameters"]:
                    s["parameters"]["input_source"] = s["input_source"]
                if "content_source" in s and "content_source" not in s["parameters"]:
                    s["parameters"]["content_source"] = s["content_source"]
                if "filename" in s["parameters"] and "path" not in s["parameters"]:
                    s["parameters"]["path"] = s["parameters"]["filename"]

                if not s.get("prompt_template") and s.get("parameters", {}).get("prompt"):
                    s["prompt_template"] = s["parameters"]["prompt"]

                # Normalizzazione alias per tool noti
                tool = s.get("action_or_tool")
                if tool:
                    tool_lower = str(tool).lower()
                    if tool_lower in ("http_get", "curl", "fetch_url", "web_fetch", "fetch_web"):
                        s["action_or_tool"] = "http_get"
                    elif tool_lower in ("file_write", "write_file", "save_file", "save_report", "save_artifact"):
                        s["action_or_tool"] = "save_artifact"

                raw_type = str(s.get("type", "")).lower()
                valid_step_types = {t.value for t in StepType}
                if raw_type in valid_step_types:
                    s["type"] = raw_type
                elif raw_type in ("llm_call", "agent", "llm") or s.get("prompt_template"):
                    s["type"] = StepType.AGENTIC_TASK.value
                elif raw_type in ("code", "python"):
                    s["type"] = StepType.CUSTOM_CODE.value
                elif raw_type in ("approval", "gate"):
                    s["type"] = StepType.APPROVAL_GATE.value
                else:
                    s["type"] = StepType.DETERMINISTIC_ACTION.value

                if "timeout" in s and "timeout_seconds" not in s:
                    s["timeout_seconds"] = int(s["timeout"])
                norm_steps.append(s)
            d["workflow"]["steps"] = norm_steps

        # 4. Normalizzazione Triggers
        trgs = d.get("triggers")
        if not trgs or not isinstance(trgs, list):
            d["triggers"] = [{"id": "trg_manual", "type": "manual", "enabled": True}]
        else:
            norm_trgs = []
            for idx, t in enumerate(trgs):
                if not isinstance(t, dict):
                    continue
                t = dict(t)
                if not t.get("id"):
                    t["id"] = f"trg_{idx+1}"
                raw_t_type = str(t.get("type", "")).lower()
                if not raw_t_type:
                    raw_t_type = "cron" if ("cron_expression" in t or "schedule" in t) else "manual"
                t["type"] = raw_t_type if raw_t_type in {tt.value for tt in TriggerType} else "cron"
                if t["type"] == "cron" and not t.get("cron_expression"):
                    t["cron_expression"] = t.get("schedule") or t.get("cron") or "0 9 * * *"
                if not t.get("timezone"):
                    t["timezone"] = "Europe/Rome"
                norm_trgs.append(t)
            d["triggers"] = norm_trgs

        # 5. Normalizzazione Budget
        b = d.get("budget")
        if isinstance(b, dict):
            b_copy = dict(b)
            if "max_tokens_per_run" in b_copy and "max_tokens" not in b_copy:
                b_copy["max_tokens"] = b_copy["max_tokens_per_run"]
            if "timeout_seconds" in b_copy and "max_duration_seconds" not in b_copy:
                b_copy["max_duration_seconds"] = b_copy["timeout_seconds"]
            d["budget"] = b_copy

        # 6. Normalizzazione Permission Policy
        p = d.get("permission_policy") or {}
        p_copy = dict(p) if isinstance(p, dict) else {}
        tools = set(p_copy.get("allowed_tools") or [])
        if isinstance(d.get("workflow"), dict):
            for st in d["workflow"].get("steps", []):
                if isinstance(st, dict) and st.get("action_or_tool"):
                    tools.add(st["action_or_tool"])
        p_copy["allowed_tools"] = list(tools)
        if "allowed_registries" not in p_copy:
            p_copy["allowed_registries"] = ["metamcp", "web", "code", "memory", "vision", "email", "automations"]
        d["permission_policy"] = p_copy

        return d


# --- Runtime Models ---

class StepRun(BaseModel):
    step_run_id: str
    run_id: str
    step_id: str
    status: RunStatus
    attempt: int = 1
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    input_payload: Dict[str, Any] = Field(default_factory=dict)
    output_payload: Optional[Any] = None
    error_message: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    tokens_consumed: int = 0
    approval_request_id: Optional[str] = None


class Artifact(BaseModel):
    artifact_id: str
    run_id: str
    step_run_id: Optional[str] = None
    name: str
    type: str = "report"
    mime_type: str = "text/plain"
    storage_uri: str
    checksum_sha256: Optional[str] = None
    created_at: Optional[str] = None


class AutomationRun(BaseModel):
    run_id: str
    automation_id: str
    version_applied: int = 1
    trigger_type: TriggerType = TriggerType.MANUAL
    trigger_payload: Dict[str, Any] = Field(default_factory=dict)
    status: RunStatus = RunStatus.PENDING
    current_step_id: Optional[str] = None
    is_dry_run: bool = False
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    step_runs: List[StepRun] = Field(default_factory=list)
    artifacts: List[Artifact] = Field(default_factory=list)
    pending_approval_id: Optional[str] = None
    total_tokens: int = 0
    total_duration_ms: int = 0
    idempotency_key: Optional[str] = None
    associated_thread_id: Optional[str] = None
    error_message: Optional[str] = None


# --- API Request / Response Schemas ---

class AutomationSummary(BaseModel):
    id: str
    name: str
    description: str
    version: int
    enabled: bool
    triggers_count: int
    steps_count: int
    created_by: str
    source_type: SourceType


class AutomationRunSummary(BaseModel):
    run_id: str
    automation_id: str
    version_applied: int
    trigger_type: str
    status: str
    current_step_id: Optional[str] = None
    is_dry_run: bool
    started_at: str
    completed_at: Optional[str] = None
    total_tokens: int
    total_duration_ms: int
    error_message: Optional[str] = None


class TriggerRunRequest(BaseModel):
    dry_run: bool = False
    trigger_payload: Dict[str, Any] = Field(default_factory=dict)
    associated_thread_id: Optional[str] = None


class ResolveApprovalRequest(BaseModel):
    action: str = Field(description="approve | deny")
    resolved_by: str = "user"
