"""Ripresa di un turno di chat sospeso su un'approvazione: il loop o il piano ripartono dallo stato salvato."""
from typing import Any, Dict

from app.agent.state import AgentState


def clean_sources(state: AgentState) -> Dict[str, Any]:
    """Ciò che può leggere la chiamata che riscrive un'uscita di dati senza la memoria (AgentLoop._clean_call): la sola
    richiesta e gli ultimi messaggi che vede il router, ognuno con il suo tag."""
    return {
        "request_tag": state.get("request_tag"),
        "recent_turns": state.get("routing_context"),
        "recent_tag": state.get("routing_tag"),
    }


def turn_meta(state: AgentState) -> Dict[str, Any]:
    """Quello che serve per riprendere il turno, oltre allo stato del loop o del piano."""
    return {
        "thread_id": state.get("thread_id"),
        "task": state.get("task", ""),
        "mode": state.get("mode"),
        "model": state.get("model"),
        "thinking_budget": state.get("reasoning_budget"),
        "incognito": bool(state.get("incognito")),
        "security_mode": state.get("security_mode") or "normal",
    }


def meta_of(checkpoint: Dict[str, Any]) -> Dict[str, Any]:
    state = checkpoint["state"]
    return state["meta"] if checkpoint["kind"] == "plan" else state["constructor"]["meta"]


def resume_checkpoint(checkpoint: Dict[str, Any], request_id: str, approved: bool) -> Dict[str, Any]:
    """Esegue il seguito del turno e ne restituisce il risultato, nella forma degli stati del grafo."""
    from app.agent import llm_calls
    from app.agent.agent_loop import AgentLoop
    from app.agent.execution_log import resume_plan

    state = checkpoint["state"]
    if checkpoint["kind"] == "plan":
        return resume_plan(state, request_id, approved)
    meta = state["constructor"]["meta"]
    fns = llm_calls.agent_loop_llm_fns(meta.get("thinking_budget"), meta.get("model"), state["constructor"]["images"])
    return AgentLoop.restore(state, fns["call_llm_fn"], fns["call_llm_structured_fn"]).resume(request_id, approved)
