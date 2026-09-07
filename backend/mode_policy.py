from typing import Dict, List

from pydantic import BaseModel


class ModePolicy(BaseModel):
    mode: str
    max_tool_calls: int
    allowed_registries: List[str]
    allow_react_loop: bool
    timeout_seconds: int
    reasoning_budget: int

DEFAULT_MODE_POLICIES: Dict[str, ModePolicy] = {
    "chat": ModePolicy(
        mode="chat",
        max_tool_calls=0,
        allowed_registries=[],
        allow_react_loop=False,
        timeout_seconds=15,
        reasoning_budget=0
    ),
    "ask": ModePolicy(
        mode="ask",
        max_tool_calls=3,
        allowed_registries=["web", "code", "memory", "vision"],
        allow_react_loop=True,
        timeout_seconds=30,
        reasoning_budget=2048
    ),
    "act": ModePolicy(
        mode="act",
        max_tool_calls=10,
        allowed_registries=["metamcp", "web", "code", "memory", "vision"],
        allow_react_loop=True,
        timeout_seconds=120,
        reasoning_budget=8192
    ),
    "plan": ModePolicy(
        mode="plan",
        max_tool_calls=15,
        allowed_registries=["metamcp", "web", "code", "memory", "vision"],
        allow_react_loop=True,
        timeout_seconds=300,
        reasoning_budget=-1
    ),
}

def get_mode_policy(mode: str) -> ModePolicy:
    """Restituisce la policy associata a una determinata modalità (default chat)."""
    clean_mode = (mode or "chat").lower().strip()
    return DEFAULT_MODE_POLICIES.get(clean_mode, DEFAULT_MODE_POLICIES["chat"])
