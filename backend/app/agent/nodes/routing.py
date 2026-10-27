import logging

from app.agent import mode_router as router
from app.agent.state import AgentState

logger = logging.getLogger("graph")


def mode_router_node(state: AgentState) -> AgentState:
    """Classifies user task into one of 4 modes (chat, ask, act, plan) and evaluates web prefetch."""
    task = state.get("task", "")
    force_mode = state.get("force_mode")
    model = state.get("model")
    images = state.get("images")
    has_images = bool(images and len(images) > 0)
    memory_context = state.get("memory_context")
    previous_mode = state.get("previous_mode")
    last_tool_used = state.get("last_tool_used")
    web_search_val = state.get("web_search")

    decision = router.route_turn(
        user_input=task,
        previous_mode=previous_mode,
        last_tool_used=last_tool_used,
        conversation_context=memory_context,
        force_mode=force_mode,
        model=model,
        has_images=has_images,
        web_search_override=web_search_val
    )
    logger.info(f"Mode Router decision: mode='{decision.mode}', web_search_needed={decision.web_search_needed}, query='{decision.web_search_query}' (has_images={has_images}, prev_mode={previous_mode})")
    return {
        "mode": decision.mode,
        "route_decision": decision.to_dict()
    }
