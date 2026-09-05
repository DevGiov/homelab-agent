from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    input: str
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


class ThreadSummary(BaseModel):
    thread_id: str
    last_message: Optional[str] = None
    checkpoint_count: int


class ProviderInfo(BaseModel):
    name: str
    is_default: bool
    healthy: bool
    default_model: str


class ProvidersResponse(BaseModel):
    active_provider: str
    active_model: str
    providers: List[ProviderInfo]


class ProviderModelsResponse(BaseModel):
    provider: str
    models: List[str]


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
