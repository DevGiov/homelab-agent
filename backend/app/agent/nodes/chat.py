from app.agent import llm_calls
from app.agent.agent_loop import is_tools_discovery_query
from app.agent.agent_prompts import current_time
from app.agent.mode_policy import get_mode_policy
from app.agent.state import AgentState
from app.agent.tool_catalog import format_available_tools_catalog
from app.core.text_utils import clean_synthesis_content


def chat_graph_node(state: AgentState) -> AgentState:
    """Subgraph for free conversation & fast queries with direct LLM response (non-agentic, 0 tools)."""
    task = state.get("task", "")
    task_lower = task.lower()
    memory_context = state.get("memory_context") or ""

    if any(kw in task_lower for kw in ["chi sei", "presentati", "chi sei tu"]):
        ans = "Sono l'agente AI per la gestione del tuo homelab. Posso assisterti sull'infrastruttura e sui servizi, eseguire azioni operative tramite i tool MCP connessi, condurre analisi visive su immagini e grafici, eseguire ricerche web ed elaborare codice in sandbox."
        return {"plan": {"mode": "chat", "tool_needed": False, "direct_answer": ans}, "final_response": ans}
    elif is_tools_discovery_query(task):
        ans = format_available_tools_catalog()
        return {"plan": {"mode": "chat", "tool_needed": False, "direct_answer": ans}, "final_response": ans}

    policy = get_mode_policy("chat")
    budget = state.get("reasoning_budget") if state.get("reasoning_budget") is not None else policy.reasoning_budget
    model = state.get("model")
    prefetch_data = state.get("web_prefetch_data")

    from app.registry.search_security import UNTRUSTED_CONTEXT_POLICY, wrap_untrusted_web_evidence

    system_prompt = (
        "You are the Homelab AI Management Assistant (mode: CHAT).\n"
        "Language Directive: English is your internal instruction language. ALWAYS detect and respond in the language used by the user in their message (e.g. if the user writes in Italian, respond in natural and fluent Italian; if in English, respond in English), unless explicitly instructed otherwise.\n"
        "You do not have access to execution tools in this mode: respond directly in conversational natural language using your internal knowledge, visual perception, and web prefetch data if provided.\n"
        "Homelab Core Knowledge:\n"
        "- The homelab has a dedicated native 'Automazioni & Loop' engine and UI tab.\n"
        "- It allows scheduled cron automations, multi-step deterministic pipelines, and autonomous agent loops.\n"
        "- Built-in templates include:\n"
        "  1) Daily Email Briefing & Triage (tpl_email_briefing): Scheduled morning digest checking unread emails and Proxmox CT status, drafting replies safely (zero auto-send policy).\n"
        "  2) GitHub Issue Auto-Repair Loop (tpl_github_repair_loop): Autonomous loop monitoring GitHub repo issues, testing container health, analyzing error logs, and preparing proposed fixes with human-in-the-loop approval.\n"
        "- Never confuse Homelab Automations with third-party software like Home Assistant or ActiveCampaign. Inform the user they can ask you to list templates or propose an automation directly in the chat, or navigate to the 'Automazioni' tab.\n"
        f"{UNTRUSTED_CONTEXT_POLICY}"
    )

    prompt_sections = []
    if memory_context:
        prompt_sections.append(f"Contesto memoria conversazionale:\n{memory_context}")
    prompt_sections.append(f"Data e ora correnti: {current_time()}")

    if prefetch_data and prefetch_data.get("summary_text"):
        wrapped_evidence = wrap_untrusted_web_evidence(
            query=prefetch_data.get("query", task),
            formatted_content=prefetch_data.get("summary_text", ""),
            sources=prefetch_data.get("sources", [])
        )
        prompt_sections.append(wrapped_evidence)

    prompt_sections.append(f"Richiesta Utente: '{task}'")
    user_prompt = "\n\n".join(prompt_sections)

    ans_res = llm_calls.call_llm(user_prompt, system_prompt=system_prompt, max_tokens=4096, reasoning_budget=budget, model=model, stream_mode="all", reasoning_phase="Elaborazione Risposta", images=state.get("images"))
    raw_ans = ans_res.get("content", "") if isinstance(ans_res, dict) else (ans_res or "")
    reasoning = ans_res.get("reasoning_content", "") if isinstance(ans_res, dict) else ""
    ans = clean_synthesis_content(raw_ans) or raw_ans

    plan = {"mode": "chat", "tool_needed": False, "direct_answer": ans, "execution_log": []}
    return {
        "plan": plan,
        "execution_trace": [],
        "final_response": ans,
        "reasoning_content": reasoning,
    }
