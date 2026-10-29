"""Memoria conversazionale del turno: fatti rilevanti di altri thread, riassunto della parte vecchia del thread e
messaggi recenti, tutti da `thread_store`.

La cronologia esclude il messaggio corrente (salvato prima dell'esecuzione del grafo, arriva come `task`). Quando i
messaggi non ancora riassunti superano `RECENT_MAX` o il budget di token, i più vecchi vengono aggiunti al
riassunto del thread, che ricorda quanti messaggi copre: la finestra recente riparte da lì, senza buchi.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.agent import llm_calls
from app.agent.state import AgentState
from app.memory import thread_store

logger = logging.getLogger("graph")

CONTEXT_TOKEN_BUDGET = 6000  # token stimati per riassunto e messaggi recenti
RECENT_MAX = 20  # messaggi non riassunti oltre i quali si aggiorna il riassunto
RECENT_KEEP = 10  # messaggi che restano nella finestra dopo l'aggiornamento
RECALL_K = 3
RECALL_MIN_SCORE = 0.35


def _estimate_tokens(messages: List[Dict[str, Any]]) -> int:
    return sum(len(m["content"]) // 4 for m in messages)  # ~4 caratteri per token


def _transcript(messages: List[Dict[str, Any]]) -> str:
    return "\n".join(f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}" for m in messages)


def _update_summary(previous: str, messages: List[Dict[str, Any]], model: Optional[str]) -> str:
    """Il riassunto precedente esteso con i messaggi indicati; stringa vuota se il modello non risponde."""
    previous_block = f"Current summary:\n{previous}\n\n" if previous else ""
    prompt = f"""{previous_block}Messages to add:
{_transcript(messages)}

Write the updated summary of the whole conversation in at most 8 sentences, in the language of the conversation.
Keep names, exact values (IP addresses, container IDs, hostnames, paths, versions), preferences, decisions and open tasks.
When a later message changes something, keep only the current value."""
    result = llm_calls.call_llm(
        prompt,
        system_prompt="You maintain a concise running summary of a conversation.",
        max_tokens=512,
        temperature=0.2,
        reasoning_budget=0,
        model=model,
        stream_mode="none",
    )
    return (result.get("content") or "").strip() if isinstance(result, dict) else ""


def conversation_window(thread_id: str, history: List[Dict[str, Any]], model: Optional[str]) -> Tuple[str, List[Dict[str, Any]]]:
    """Riassunto e messaggi recenti da mettere nel prompt, aggiornando il riassunto salvato se serve."""
    summary, covered = thread_store.get_summary(thread_id)
    if covered > len(history):  # messaggi eliminati dopo il riassunto
        summary, covered = "", 0
    window = history[covered:]
    if len(window) <= RECENT_MAX and _estimate_tokens(window) <= CONTEXT_TOKEN_BUDGET:
        return summary, window

    keep = RECENT_KEEP
    while keep > 4 and _estimate_tokens(window[-keep:]) > CONTEXT_TOKEN_BUDGET:
        keep = max(4, keep // 2)
    folded = window[:-keep]
    if folded:
        updated = _update_summary(summary, folded, model)
        if updated:
            summary, covered = updated, covered + len(folded)
            thread_store.save_summary(thread_id, summary, covered)
            logger.info(f"Riassunto del thread '{thread_id}' aggiornato: copre {covered} messaggi")
        else:
            logger.warning(f"Riassunto del thread '{thread_id}' non aggiornato: {len(folded)} messaggi fuori dalla finestra")
    return summary, window[-keep:]


def _semantic_recall(task: str, thread_id: str) -> str:
    """Fatti di altri thread pertinenti alla richiesta (quelli del thread sono già nella conversazione)."""
    try:
        from app.memory.vector_store import search_memory

        hits = search_memory(task, k=RECALL_K, kind="fact")
    except Exception as e:
        logger.warning(f"Recall semantico non riuscito (non bloccante): {e}")
        return ""
    relevant = [h for h in hits if h.get("score", 0) > RECALL_MIN_SCORE and h.get("thread_id") != thread_id]
    if not relevant:
        return ""
    return "### Memoria a lungo termine rilevante:\n" + "\n".join(f"- {h['content']}" for h in relevant)


def retrieve_memory_node(state: AgentState) -> AgentState:
    """Contesto di memoria del turno e modalità dell'ultima risposta. Saltato in incognito."""
    thread_id = state.get("thread_id")
    if not thread_id or state.get("incognito"):
        return {"memory_context": None}

    task = state.get("task", "")
    history = thread_store.get_history(thread_id)
    if history and history[-1]["role"] == "user" and history[-1]["content"] == task.strip():
        history = history[:-1]

    summary, recent = conversation_window(thread_id, history, state.get("model"))
    parts = [p for p in (_semantic_recall(task, thread_id),) if p]
    if summary:
        parts.append(f"### Riepilogo conversazione precedente:\n{summary}")
    if recent:
        parts.append("### Messaggi recenti:\n" + _transcript(recent))

    last_assistant = next((m for m in reversed(history) if m["role"] == "assistant"), None)
    previous_mode = last_assistant["mode"] if last_assistant else None
    logger.info(
        f"Memoria del thread '{thread_id}': {len(history)} messaggi, riassunto={'sì' if summary else 'no'}, "
        f"finestra={len(recent)}, modalità precedente={previous_mode}"
    )
    return {
        "memory_context": "\n\n".join(parts),
        "previous_mode": previous_mode,
        "last_tool_used": last_assistant["tool_used"] if last_assistant else None,
    }
