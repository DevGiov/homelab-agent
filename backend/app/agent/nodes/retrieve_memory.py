import logging
import os
from typing import Any, Dict, List, Optional

from app.agent import llm_calls
from app.agent.state import AgentState
from app.core.config import settings
from app.memory import letta_client, transcript

logger = logging.getLogger("graph")


def _generate_summary(messages: List[Dict[str, Any]], model: Optional[str] = None) -> str:
    """Genera un riassunto di una lista di messaggi mediante LLM."""
    text = "\n".join([f"{'User' if 'user' in str(m.get('message_type','')).lower() else 'Assistant'}: {m.get('content', '')}" for m in messages])
    prompt = f"""Summarize the following conversation in at most 5 sentences, preserving:
- Names of persons/entities (e.g. "Alice")
- Expressed preferences (e.g. "prefers Debian")
- Decisions made (e.g. "created web service")
- Open questions or ongoing tasks

Conversation:
{text}

Summary:"""
    summary_res = llm_calls.call_llm(prompt, system_prompt="You are an assistant that summarizes conversations concisely.", max_tokens=512, temperature=0.3, reasoning_budget=0, model=model, stream_mode="none")
    summary = summary_res.get("content", "") if isinstance(summary_res, dict) else ""
    return summary.strip() if summary else ""


def retrieve_memory_node(state: AgentState) -> AgentState:
    """Retrieves relevant memory context combining sliding window + incremental summary + semantic recall. Skipped in incognito mode."""
    thread_id = state.get("thread_id")
    if not thread_id or state.get("incognito"):
        return {"memory_context": None, "agent_id": None}

    agent_id = letta_client.create_thread(thread_id)
    raw_messages = letta_client.get_messages(agent_id) if agent_id else []
    clean_messages = letta_client.filter_clean_messages(raw_messages) if raw_messages else []

    # Fallback su file JSONL se Letta è offline o non ha messaggi
    if not clean_messages:
        clean_messages = transcript.read_messages(thread_id)

    # --- Fase 2.1: recall semantico dalla memoria vettoriale (fatti salienti passati) ---
    semantic_recall = ""
    try:
        from app.memory.vector_store import search_memory
        task_text = state.get("task", "")
        hits = search_memory(task_text, k=3, kind="fact")
        relevant = [h for h in hits if h.get("score", 0) > 0.35 and h.get("thread_id") != thread_id]
        if relevant:
            lines = [f"- {h['content']}" for h in relevant]
            semantic_recall = "### Memoria a lungo termine rilevante:\n" + "\n".join(lines)
            logger.info(f"Semantic recall: {len(relevant)} fatti rilevanti da altri thread")
    except Exception as e:
        logger.warning(f"Semantic recall fallito (non bloccante): {e}")

    summary = ""
    recent_messages = []

    # --- Fase 2.4: compattazione basata su token stimati (non solo numero messaggi) ---
    def _estimate_tokens(msgs: List[Dict[str, Any]]) -> int:
        return sum(len(str(m.get("content", ""))) // 4 for m in msgs)  # ~4 char/token

    CONTEXT_TOKEN_BUDGET = 6000  # budget per la memoria conversazionale nel prompt
    RECENT_KEEP = 20

    total_tokens = _estimate_tokens(clean_messages)
    needs_compaction = len(clean_messages) > 30 or total_tokens > CONTEXT_TOKEN_BUDGET

    if needs_compaction:
        summary_key = f"summary_1_30_{thread_id}"
        summary_file = os.path.join(settings.memory_dir, f"summary_{thread_id}.txt")

        if agent_id:
            summary = letta_client.get_archival_memory(agent_id, key=summary_key)

        if not summary and os.path.exists(summary_file):
            try:
                with open(summary_file, "r", encoding="utf-8") as sf:
                    summary = sf.read().strip()
            except Exception:
                pass

        # Compattazione progressiva: riduci la finestra recente finché non rientra nel budget
        keep = RECENT_KEEP
        recent_messages = clean_messages[-keep:]
        while _estimate_tokens(recent_messages) > CONTEXT_TOKEN_BUDGET and keep > 4:
            keep = max(4, keep // 2)
            recent_messages = clean_messages[-keep:]

        if not summary:
            old_messages = clean_messages[:-keep] if len(clean_messages) > keep else clean_messages
            if old_messages:
                logger.info(f"Generazione summary incrementale per thread '{thread_id}' su {len(old_messages)} vecchi messaggi...")
                summary = _generate_summary(old_messages, model=state.get("model"))
                if summary:
                    if agent_id:
                        letta_client.save_archival_memory(agent_id, key=summary_key, value=summary)
                    try:
                        os.makedirs(settings.memory_dir, exist_ok=True)
                        with open(summary_file, "w", encoding="utf-8") as sf:
                            sf.write(summary)
                    except Exception as e:
                        logger.warning(f"Errore salvataggio summary locale {summary_file}: {e}")
    else:
        recent_messages = clean_messages

    memory_parts = []
    if semantic_recall:
        memory_parts.append(semantic_recall)
    if summary:
        memory_parts.append(f"### Riepilogo conversazione precedente:\n{summary}")

    if recent_messages:
        memory_parts.append("### Messaggi recenti:")
        for msg in recent_messages:
            m_type = str(msg.get("message_type", "")).lower()
            role_label = "User" if "user" in m_type else "Assistant"
            txt = msg.get("content", "")
            if txt:
                memory_parts.append(f"{role_label}: {txt}")

    previous_mode = None
    last_tool_used = None
    try:
        from app.memory import thread_store
        t_msgs = thread_store.get_thread_messages(thread_id)
        for m in reversed(t_msgs):
            if m.get("sender") == "assistant":
                previous_mode = m.get("mode")
                last_tool_used = m.get("tool_used")
                break
    except Exception as e:
        logger.warning(f"Impossibile ricavare previous_mode dal thread_store per '{thread_id}': {e}")

    memory_context = "\n\n".join(memory_parts) if memory_parts else ""
    logger.info(f"Retrieval memoria per thread '{thread_id}': total_messages={len(clean_messages)}, has_summary={bool(summary)}, recent_window={len(recent_messages)}, prev_mode={previous_mode}")
    return {
        "memory_context": memory_context,
        "agent_id": agent_id,
        "previous_mode": previous_mode,
        "last_tool_used": last_tool_used
    }
