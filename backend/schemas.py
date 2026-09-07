from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    input: str
    images: Optional[List[str]] = None
    thread_id: Optional[str] = None
    force_mode: Optional[Literal["chat", "ask", "act", "plan"]] = None
    reasoning_budget: Optional[int] = None
    execute: bool = False
    model: Optional[str] = None
    incognito: bool = False
    web_search: bool = False

class ChatResponse(BaseModel):
    thread_id: Optional[str] = None
    mode: str
    response: str
    tool_used: Optional[str] = None
    plan_steps: Optional[List[str]] = None
    plan_structure: Optional[Dict[str, Any]] = None
    execution_trace: Optional[List[Dict[str, Any]]] = None
    rollback_trace: Optional[List[Dict[str, Any]]] = None
    reasoning_content: Optional[str] = None
    web_prefetch: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, Any]] = None
    thread_title: Optional[str] = None
    approval_required: Optional[bool] = None
    request_id: Optional[str] = None
    approval_prompt: Optional[str] = None
    command_preview: Optional[str] = None
    command_prefix: Optional[str] = None
    risk_reason: Optional[str] = None


class ThreadControlRequest(BaseModel):
    thread_id: str


class ThreadSummary(BaseModel):
    thread_id: str
    title: Optional[str] = None
    last_message: Optional[str] = None
    checkpoint_count: int
    is_active: bool = False


class SetThreadTitleRequest(BaseModel):
    title: str


class SwitchVersionRequest(BaseModel):
    version_index: int


class SaveVersionsDataRequest(BaseModel):
    versions: List[Dict[str, Any]]
    version_index: int


class ProviderInfo(BaseModel):
    name: str
    is_default: bool
    healthy: bool
    default_model: str


class ProvidersResponse(BaseModel):
    active_provider: str
    active_model: str
    providers: List[ProviderInfo]


class ModelDetail(BaseModel):
    id: str
    is_vision: bool = False
    input_modalities: Optional[List[str]] = None


class ProviderModelsResponse(BaseModel):
    provider: str
    models: List[str]
    models_detail: Optional[List[ModelDetail]] = None


class ImageUploadResponse(BaseModel):
    url: str
    data_url: str
    filename: str
    width: Optional[int] = None
    height: Optional[int] = None


class SetDefaultProviderRequest(BaseModel):
    provider: str
    model: Optional[str] = None


class MemoryItem(BaseModel):
    id: int
    kind: str
    thread_id: Optional[str] = None
    content: str
    metadata: Dict[str, Any] = {}
    created_at: Optional[str] = None


class MemoryListResponse(BaseModel):
    memories: List[MemoryItem]
    total: int


class AddMemoryRequest(BaseModel):
    content: str
    kind: str = "fact"
    thread_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ClearMemoryResponse(BaseModel):
    deleted_count: int
    letta_cleared: bool
    message: str


class ResolveApprovalRequest(BaseModel):
    action: str = "approve"  # "approve" | "deny" | "approve_thread" | "approve_always"
    resolved_by: str = "user"


class PermissionItem(BaseModel):
    id: Optional[int] = None
    tool_name: str
    command_prefix: Optional[str] = None
    scope: str = "always"
    created_at: Optional[str] = None
    created_by: Optional[str] = "user"
    thread_id: Optional[str] = None

