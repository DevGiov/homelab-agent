from app.agent.state import AgentState
from app.memory import letta_client


def commit_memory_node(state: AgentState) -> AgentState:
    """Commits task and final response to Letta thread in a single atomic turn to prevent duplicate responses. Skipped in incognito."""
    if state.get("incognito"):
        return state

    agent_id = state.get("agent_id")
    final_response = state.get("final_response", "")
    task = state.get("task", "")

    if agent_id and final_response:
        combined_entry = f"User: {task}\nAssistant: {final_response}"
        letta_client.send_message(agent_id, "user", combined_entry)

    return state
