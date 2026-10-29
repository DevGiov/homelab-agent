from app.agent import llm_calls
from app.agent.agent_loop import run_agent_loop
from app.agent.execution_log import execute_plan
from app.agent.state import AgentState

PLAN_EXECUTION_KEYWORDS = ("esegui il piano", "esegui piano", "avvia esecuzione", "esecuzione piano")


def execute_plan_node(state: AgentState) -> AgentState:
    """Esegue il plan_structure del turno come Saga (vedi execution_log); senza piano ricade sull'agent loop di act."""
    plan_struct = state.get("plan_structure") or state.get("plan", {}).get("plan_structure")
    if not plan_struct or not isinstance(plan_struct, dict) or "steps" not in plan_struct:
        return act_graph_node(state)
    return execute_plan(
        plan_struct,
        task=state.get("task", ""),
        thread_id=state.get("thread_id"),
        security_mode=state.get("security_mode") or "normal",
        model=state.get("model"),
    )


def act_graph_node(state: AgentState) -> AgentState:
    """Subgraph for single tool or plan execution.

    Con un piano strutturato nel thread e una richiesta di esecuzione esegue il piano;
    altrimenti la richiesta passa all'agent loop, che agisce solo tramite tool reali e guardrail.
    """
    task = state.get("task", "")
    task_lower = task.lower()

    if state.get("plan_structure") or state.get("plan", {}).get("plan_structure"):
        if state.get("execute") or any(kw in task_lower for kw in PLAN_EXECUTION_KEYWORDS):
            return execute_plan_node(state)

    model = state.get("model")

    memory_context = state.get("memory_context") or ""
    loop_res = run_agent_loop(
        task=task,
        mode="act",
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
    plan = {"mode": "act", "tool_needed": len(trace) > 0, "direct_answer": ans, "execution_log": trace}
    return {
        "plan": plan,
        "execution_trace": trace,
        "final_response": ans,
        "reasoning_content": reasoning,
        "approval_required": loop_res.get("approval_required"),
        "request_id": loop_res.get("request_id"),
        "approval_prompt": loop_res.get("approval_prompt"),
        "command_preview": loop_res.get("command_preview"),
        "command_prefix": loop_res.get("command_prefix"),
        "risk_reason": loop_res.get("risk_reason"),
        "security_mode": state.get("security_mode") or "normal",
    }
