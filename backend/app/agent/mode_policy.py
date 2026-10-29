from typing import Dict, List

from pydantic import BaseModel


class MemoryPolicy(BaseModel):
    """Quanta memoria entra nel prompt della modalità."""
    context_tokens: int  # riassunto e messaggi recenti del thread
    facts_k: int  # fatti di altri thread richiamati per somiglianza (0 = nessuno)
    verify_facts: bool = False  # i fatti vanno verificati prima di agire
    episodes_k: int = 0  # esecuzioni passate simili alla richiesta (tool usati ed esito)


class ModePolicy(BaseModel):
    mode: str
    max_tool_calls: int
    allowed_registries: List[str]
    allow_react_loop: bool
    timeout_seconds: int
    reasoning_budget: int
    memory: MemoryPolicy

DEFAULT_MODE_POLICIES: Dict[str, ModePolicy] = {
    "chat": ModePolicy(
        mode="chat",
        max_tool_calls=0,
        allowed_registries=[],
        allow_react_loop=False,
        timeout_seconds=15,
        reasoning_budget=0,
        memory=MemoryPolicy(context_tokens=1500, facts_k=0)
    ),
    "ask": ModePolicy(
        mode="ask",
        max_tool_calls=5,
        allowed_registries=["web", "code", "memory", "vision", "automations", "calendar"],
        allow_react_loop=True,
        timeout_seconds=30,
        reasoning_budget=2048,
        memory=MemoryPolicy(context_tokens=6000, facts_k=5)
    ),
    "act": ModePolicy(
        mode="act",
        max_tool_calls=10,
        allowed_registries=["mcp", "web", "code", "memory", "vision", "email", "automations", "calendar"],
        allow_react_loop=True,
        timeout_seconds=120,
        reasoning_budget=8192,
        memory=MemoryPolicy(context_tokens=6000, facts_k=5, verify_facts=True, episodes_k=3)
    ),
    "plan": ModePolicy(
        mode="plan",
        max_tool_calls=15,
        allowed_registries=["mcp", "web", "code", "memory", "vision", "email", "automations", "calendar"],
        allow_react_loop=True,
        timeout_seconds=300,
        reasoning_budget=-1,
        memory=MemoryPolicy(context_tokens=6000, facts_k=5, verify_facts=True, episodes_k=5)
    ),
}

def get_mode_policy(mode: str) -> ModePolicy:
    """Restituisce la policy associata a una determinata modalità (default chat)."""
    clean_mode = (mode or "chat").lower().strip()
    return DEFAULT_MODE_POLICIES.get(clean_mode, DEFAULT_MODE_POLICIES["chat"])
