from app.agent.state import AgentState


def intake_node(state: AgentState) -> AgentState:
    """Riceve il task; senza testo ma con immagini usa una richiesta di descrizione. Il messaggio dell'utente è già
    in `thread_store`, salvato da chi invoca il grafo."""
    task = state.get("task", "")
    images = state.get("images")
    if not task and images:
        task = "Analizza e descrivi l'immagine allegata."
        state["task"] = task
    return state
