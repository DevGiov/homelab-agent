from app.agent.state import AgentState
from app.memory import transcript


def intake_node(state: AgentState) -> AgentState:
    """Receives the task and settings, and appends user message to JSONL file memory if not incognito."""
    thread_id = state.get("thread_id")
    task = state.get("task", "")
    images = state.get("images")
    if not task and images:
        task = "Analizza e descrivi l'immagine allegata."
        state["task"] = task
    incognito = state.get("incognito", False)
    if thread_id and task and not incognito:
        transcript.append_message(thread_id, "user", task)
    return state
