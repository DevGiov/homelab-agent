"""Memoria del turno, in due tempi.

Prima del router (`recent_turns_node`) servono solo gli ultimi messaggi e la modalità dell'ultima risposta. Dopo il
router (`retrieve_memory_node`) la memoria si compone secondo la `MemoryPolicy` della modalità scelta: profilo
dell'utente, riassunto della parte vecchia del thread, messaggi recenti entro il budget, fatti di altri thread ed
esecuzioni passate simili (act e plan).

L'ordine va dal più stabile al più variabile, così llama.cpp riusa da un turno all'altro la parte iniziale del prompt:
il profilo cambia di rado, il riassunto a ogni ripiegamento, i messaggi si accodano; fatti ed episodi dipendono dalla richiesta.

La cronologia esclude il messaggio corrente (salvato prima dell'esecuzione del grafo, arriva come `task`). Quando i
messaggi non ancora riassunti superano `RECENT_MAX` o `CONTEXT_TOKEN_BUDGET`, i più vecchi vengono aggiunti al
riassunto del thread, che ricorda quanti messaggi copre: la finestra recente riparte da lì, senza buchi.
"""
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.agent import llm_calls
from app.agent.mode_policy import MemoryPolicy, get_mode_policy
from app.agent.state import AgentState
from app.memory import episodes, facts, profile, thread_store

logger = logging.getLogger("graph")

CONTEXT_TOKEN_BUDGET = 6000  # token stimati dei messaggi non riassunti oltre i quali si aggiorna il riassunto
RECENT_MAX = 20  # messaggi non riassunti oltre i quali si aggiorna il riassunto
RECENT_KEEP = 10  # messaggi che restano nella finestra dopo l'aggiornamento
ROUTING_MESSAGES = 4  # messaggi recenti visti dal router
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


def _history(state: AgentState) -> List[Dict[str, Any]]:
    """Cronologia del thread senza il messaggio corrente."""
    history = thread_store.get_history(state["thread_id"])
    if history and history[-1]["role"] == "user" and history[-1]["content"] == state.get("task", "").strip():
        history = history[:-1]
    return history


def _tail_within(messages: List[Dict[str, Any]], tokens: int) -> List[Dict[str, Any]]:
    """Gli ultimi messaggi che stanno nel budget (almeno l'ultimo)."""
    kept: List[Dict[str, Any]] = []
    total = 0
    for message in reversed(messages):
        total += _estimate_tokens([message])
        if kept and total > tokens:
            break
        kept.append(message)
    return kept[::-1]


def _recalled_facts(task: str, thread_id: str, policy: MemoryPolicy) -> str:
    """Fatti di altri thread pertinenti alla richiesta (quelli del thread sono già nella conversazione), con la data."""
    if not policy.facts_k:
        return ""
    try:
        hits = facts.search_facts(task, k=policy.facts_k * 2, min_score=RECALL_MIN_SCORE)
    except Exception as e:
        logger.warning(f"Recall semantico non riuscito (non bloccante): {e}")
        return ""
    relevant = [h for h in hits if h["thread_id"] != thread_id][:policy.facts_k]
    if not relevant:
        return ""
    header = "### Fatti ricordati da altre conversazioni"
    if policy.verify_facts:
        header += " (possono essere superati: verificali con i tool prima di agire)"
    lines = [f"- [{(h['created_at'] or '')[:10]}] {h['content']}" for h in relevant]
    return f"{header}:\n" + "\n".join(lines)


def _past_executions(task: str, policy: MemoryPolicy) -> str:
    """Episodi di esecuzione simili alla richiesta: tool usati, errori ed esito."""
    if not policy.episodes_k:
        return ""
    try:
        similar = episodes.similar_episodes(task, policy.episodes_k)
    except Exception as e:
        logger.warning(f"Ricerca degli episodi non riuscita (non bloccante): {e}")
        return ""
    if not similar:
        return ""
    return "### Esecuzioni simili passate (tool usati ed esito):\n" + "\n".join(f"- [{e['date']}] {e['content']}" for e in similar)


def recent_turns_node(state: AgentState) -> AgentState:
    """Prima del router: ultimi messaggi e modalità dell'ultima risposta, senza chiamate al modello."""
    if not state.get("thread_id") or state.get("incognito"):
        return {"routing_context": None}
    history = _history(state)
    last_assistant = next((m for m in reversed(history) if m["role"] == "assistant"), None)
    return {
        "routing_context": _transcript(history[-ROUTING_MESSAGES:]) or None,
        "previous_mode": last_assistant["mode"] if last_assistant else None,
        "last_tool_used": last_assistant["tool_used"] if last_assistant else None,
    }


def retrieve_memory_node(state: AgentState) -> AgentState:
    """Dopo il router: memoria del turno secondo la modalità scelta. Saltata in incognito."""
    thread_id = state.get("thread_id")
    if not thread_id or state.get("incognito"):
        return {"memory_context": None}

    started = time.monotonic()
    mode = state.get("mode") or "chat"
    policy = get_mode_policy(mode).memory
    task = state.get("task", "")
    history = _history(state)
    summary, window = conversation_window(thread_id, history, state.get("model"))
    recent = _tail_within(window, max(policy.context_tokens - len(summary) // 4, 0))

    parts = []
    user_profile = profile.get_profile()["content"]
    if user_profile:
        parts.append(f"### Profilo dell'utente (scritto dall'utente):\n{user_profile}")
    if summary:
        parts.append(f"### Riepilogo conversazione precedente:\n{summary}")
    if recent:
        parts.append("### Messaggi recenti:\n" + _transcript(recent))
    recalled = _recalled_facts(task, thread_id, policy)
    if recalled:
        parts.append(recalled)
    executions = _past_executions(task, policy)
    if executions:
        parts.append(executions)

    logger.info(
        f"Memoria [{mode}] del thread '{thread_id}': {len(history)} messaggi, profilo={'sì' if user_profile else 'no'}, "
        f"riassunto={'sì' if summary else 'no'}, finestra={len(recent)}/{len(window)}, "
        f"fatti={max(len(recalled.splitlines()) - 1, 0)}, episodi={max(len(executions.splitlines()) - 1, 0)}, {(time.monotonic() - started) * 1000:.0f} ms"
    )
    return {"memory_context": "\n\n".join(parts)}
