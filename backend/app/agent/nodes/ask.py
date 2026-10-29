from app.agent import llm_calls
from app.agent.agent_loop import is_tools_discovery_query, run_agent_loop
from app.agent.state import AgentState
from app.agent.tool_catalog import format_available_tools_catalog


def ask_graph_node(state: AgentState) -> AgentState:
    """Subgraph for memory & knowledge retrieval queries (with Web Search & Code Exec tools enabled)."""
    task = state.get("task", "")
    memory_context = state.get("memory_context") or ""

    if is_tools_discovery_query(task):
        ans = format_available_tools_catalog()
        return {"plan": {"mode": "ask", "tool_needed": False, "direct_answer": ans}, "final_response": ans}

    model = state.get("model")

    loop_res = run_agent_loop(
        task=task,
        mode="ask",
        memory_context=memory_context,
        thread_id=state.get("thread_id"),
        web_prefetch_data=state.get("web_prefetch_data"),
        images=state.get("images"),
        security_mode=state.get("security_mode") or "normal",
        **llm_calls.agent_loop_llm_fns(state.get("reasoning_budget"), model, state.get("images")),
    )

    ans = loop_res.get("final_response", "")
    trace = loop_res.get("execution_trace", [])
    reasoning = loop_res.get("reasoning_content")
    plan = {"mode": "ask", "tool_needed": len(trace) > 0, "direct_answer": ans, "execution_log": trace}
    return {"plan": plan, "execution_trace": trace, "final_response": ans, "reasoning_content": reasoning}
