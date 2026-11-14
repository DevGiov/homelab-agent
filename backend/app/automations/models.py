"""Modelli di dominio Pydantic per Automations & Loops.

Include schemi canonici validati per definizioni, workflow, policy,
budget, run, step ed esecuzioni.
"""

import re
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.automations.proposal_normalization import (
    expand_single_step_template,
    normalize_budget,
    normalize_identity,
    normalize_notification_policy,
    normalize_parameters_and_settings,
    normalize_permission_policy,
    normalize_steps,
    normalize_triggers,
    normalize_workflow_shape,
)


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
    CALENDAR = "calendar"


def _as_dict(value: Any, model: type[BaseModel]) -> Any:
    """Il dump di un'istanza del modello dato; ogni altro valore resta com'è."""
    return value.model_dump() if isinstance(value, model) else value


# --- Policy & Budget ---

class Budget(BaseModel):
    max_duration_seconds: int = Field(default=300, ge=1, description="Timeout globale della run in secondi")
    max_llm_calls: int = Field(default=10, ge=0, description="Numero massimo chiamate LLM")
    max_tool_calls: int = Field(default=25, ge=0, description="Numero massimo invocazioni tool")
    max_tokens: int = Field(default=50000, ge=0, description="Tetto massimo di token consumabili")
    max_cost_usd: float = Field(default=0.0, ge=0.0, description="Budget di spesa stimato")
    max_retries_per_step: int = Field(default=2, ge=0, description="Tentativi di retry ammessi per step")

    @model_validator(mode="before")
    @classmethod
    def sanitize_budget_input(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return {}
        d = dict(data)
        if "max_tokens_per_run" in d and "max_tokens" not in d:
            d["max_tokens"] = d["max_tokens_per_run"]
        if "timeout_seconds" in d and "max_duration_seconds" not in d:
            d["max_duration_seconds"] = d["timeout_seconds"]
        if "duration_seconds" in d and "max_duration_seconds" not in d:
            d["max_duration_seconds"] = d["duration_seconds"]
        return {k: v for k, v in d.items() if v is not None}


class ExecutionPolicy(BaseModel):
    execution_identity: str = Field(default="automation-default-sa", description="Identità/Service Account per permessi")
    allowed_tools: List[str] = Field(default_factory=list, description="Allowlist rigida di tool invocabili")
    allowed_registries: List[str] = Field(default_factory=lambda: ["mcp", "web", "code", "memory", "vision", "email", "automations", "calendar"])
    security_mode: str = Field(default="normal", description="safest | normal | dangerous")
    require_approval_for: List[str] = Field(default_factory=list, description="Azioni che forzano l'approval gate")
    target_scopes: Dict[str, List[str]] = Field(
        default_factory=lambda: {"allowed_containers": [], "allowed_repos": [], "allowed_recipients": []},
        description="Perimetrazione di sicurezza per container, repository e destinatari autorizzati"
    )
    secrets_whitelist: List[str] = Field(default_factory=list, description="Nomi dei secret accessibili")
    allowed_hosts: List[str] = Field(
        default_factory=list,
        description="Host che http_get e inspect_image possono contattare senza conferma durante le run, oltre alla "
                    "lista generale degli host ammessi (nome, '*.dominio' o indirizzo IP)",
    )
    dry_run_supported: bool = Field(default=True, description="Indica se l'automazione supporta la modalità anteprima")

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _normalize_hosts(cls, value: Any) -> List[str]:
        from app.security.network import normalize_pattern

        if value is None:
            return []
        if isinstance(value, str):
            value = [part for part in re.split(r"[\s,]+", value) if part]
        hosts: List[str] = []
        for raw in value:
            host = normalize_pattern(raw)  # ValueError -> errore di validazione con il motivo
            if host not in hosts:
                hosts.append(host)
        return hosts


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
    webhook_token: Optional[str] = None
    event_pattern: Optional[Dict[str, Any]] = None
    enabled: bool = True


class WorkflowStepDefinition(BaseModel):
    step_id: str
    name: str
    type: StepType
    action_or_tool: Optional[str] = None
    prompt_template: Optional[str] = None
    tools: Optional[List[str]] = Field(default=None, description="Tool di uno step agentico, dentro l'allowlist dell'automazione: null = tutti, [] = nessuno (solo testo)")
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
    settings: Dict[str, Any] = Field(default_factory=dict, description="Impostazioni dedicate, override integrazioni e credenziali per l'automazione")
    retention_days: Optional[int] = Field(default=None, ge=1, description="Giorni di retention per le run (default globale se non specificato)")
    model: Optional[str] = Field(default=None, description="Modello LLM degli step agentici: null = default del provider, 'loaded' = quello caricato quando lo step parte (il default se nessuno), altrimenti il nome del modello")
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
        """Normalizza tollerantemente payload raw generati da LLM o client UI, un passo per sezione."""
        if not isinstance(data, dict):
            return data
        d = dict(data)
        normalize_identity(d)
        normalize_parameters_and_settings(d)
        normalize_workflow_shape(d)
        expand_single_step_template(d)
        normalize_steps(d, {t.value for t in StepType})
        normalize_triggers(d, {t.value for t in TriggerType})
        d["budget"] = normalize_budget(_as_dict(d.get("budget"), Budget), Budget().model_dump())
        d["permission_policy"] = normalize_permission_policy(
            _as_dict(d.get("permission_policy"), ExecutionPolicy), d.get("workflow")
        )
        d["notification_policy"] = normalize_notification_policy(
            _as_dict(d.get("notification_policy"), NotificationPolicy), NotificationPolicy().model_dump()
        )
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
    title: Optional[str] = None
    content: Optional[str] = None
    type: str = "report"
    mime_type: str = "text/plain"
    storage_uri: str
    checksum_sha256: Optional[str] = None
    is_preserved: bool = False
    is_favorite: bool = False
    automation_id: Optional[str] = None
    automation_name: Optional[str] = None
    created_at: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def set_title_and_content(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("title") and data.get("name"):
                data["title"] = data["name"]
        return data


class AutomationRun(BaseModel):
    run_id: str
    automation_id: str
    version_applied: int = 1
    trigger_type: TriggerType = TriggerType.MANUAL
    trigger_payload: Dict[str, Any] = Field(default_factory=dict)
    status: RunStatus = RunStatus.PENDING
    current_step_id: Optional[str] = None
    is_dry_run: bool = False
    is_preserved: bool = False
    is_favorite: bool = False
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
    retention_days: Optional[int] = None
    last_run_status: Optional[str] = None
    last_run_at: Optional[str] = None
    last_artifact_id: Optional[str] = None
    last_artifact_name: Optional[str] = None
    last_artifact_at: Optional[str] = None
    triggers: List[Dict[str, Any]] = Field(default_factory=list)
    webhook_url: Optional[str] = None


class AutomationRunSummary(BaseModel):
    run_id: str
    automation_id: str
    version_applied: int
    trigger_type: str
    status: str
    current_step_id: Optional[str] = None
    is_dry_run: bool
    is_preserved: bool = False
    is_favorite: bool = False
    artifacts_count: int = 0
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

