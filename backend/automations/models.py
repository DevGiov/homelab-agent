"""Modelli di dominio Pydantic per Automations & Loops.

Include schemi canonici validati per definizioni, workflow, policy,
budget, run, step ed esecuzioni.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


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
    input_schema: Optional[Dict[str, Any]] = None
    permission_policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
    budget: Budget = Field(default_factory=Budget)
    notification_policy: NotificationPolicy = Field(default_factory=NotificationPolicy)
    created_by: str = "user"
    source_type: SourceType = SourceType.UI
    source_reference: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


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
