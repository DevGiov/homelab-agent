import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional

from app.agent import llm_calls
from app.agent.mode_policy import get_mode_policy
from app.agent.nodes.act import execute_plan_node
from app.agent.state import AgentState

logger = logging.getLogger("graph")


def generate_plan_structure(task: str, user_prompt: str, model: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Piano strutturato (passi con tool del catalogo, argomenti e dipendenze), o None se il modello non ne produce
    uno valido: in quel caso il piano resta solo testuale e l'esecuzione passa all'agent loop."""
    from app.agent.tool_catalog import format_catalog_for_prompt
    from app.registry.manager import get_registry_manager
    from app.registry.search_security import UNTRUSTED_CONTEXT_POLICY

    tools = get_registry_manager().get_tools_for_mode(get_mode_policy("act").allowed_registries)
    json_prompt = (
        f"Generate a structured JSON plan for the following user task: '{task}'.\n"
        f"{UNTRUSTED_CONTEXT_POLICY}\n"
        "Use ONLY tools from this catalog, with their exact names:\n"
        f"{format_catalog_for_prompt(tools)}\n\n"
        "Reply EXCLUSIVELY with valid JSON matching this schema:\n"
        "{\n"
        "  \"steps\": [\n"
        "    {\n"
        "      \"id\": 1,\n"
        "      \"description\": \"Step description\",\n"
        "      \"tool\": \"exact_tool_name\",\n"
        "      \"args\": {\"param\": \"value\"},\n"
        "      \"depends_on\": null,\n"
        "      \"output_var\": \"variable_name\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    res = llm_calls.call_llm(user_prompt, system_prompt=json_prompt, max_tokens=4096, temperature=0.1, model=model, stream_mode="none")
    content = res.get("content", "") if isinstance(res, dict) else ""
    clean = re.sub(r"```(?:json)?", "", content).strip()
    start = clean.find("{")
    if start < 0:
        logger.warning("Piano strutturato assente nella risposta del modello")
        return None
    try:
        # Solo il primo oggetto: il modello può continuare a scrivere dopo averlo chiuso
        parsed, _ = json.JSONDecoder().raw_decode(clean[start:])
    except ValueError as e:
        logger.warning(f"Piano strutturato non valido: {e}")
        return None
    steps = parsed.get("steps") if isinstance(parsed, dict) else None
    if not isinstance(steps, list) or not steps or not all(isinstance(st, dict) and st.get("tool") for st in steps):
        logger.warning("Piano strutturato senza passi validi")
        return None
    return {"steps": steps}


def plan_graph_node(state: AgentState) -> AgentState:
    """Subgraph for detailed multi-step planning (simulation/dry-run & JSON plan generation)."""
    task = state.get("task", "")
    memory_context = state.get("memory_context") or ""
    model = state.get("model")
    prefetch_data = state.get("web_prefetch_data")

    policy = get_mode_policy("plan")
    budget = state.get("reasoning_budget") if state.get("reasoning_budget") is not None else policy.reasoning_budget

    from app.registry.search_security import UNTRUSTED_CONTEXT_POLICY, wrap_untrusted_web_evidence

    now_str = datetime.now().strftime('%A %d %B %Y, %H:%M:%S')
    task_lower = task.lower()
    is_automation_request = any(kw in task_lower for kw in [
        "crea automazione", "crea un'automazione", "automatizza", "nuova automazione",
        "schedula", "task ricorrente", "crea loop", "programma ogni",
        "create automation", "create an automation", "automate", "schedule recurring", "schedule daily"
    ])

    if is_automation_request:
        system_prompt = (
            f"Current System Date and Time: {now_str}\n"
            "You are the Homelab AI Management Agent (mode: PLAN - AUTOMATION PROPOSAL).\n"
            "Language Directive: English is your internal instruction language. ALWAYS detect and respond in the language used by the user in their message (e.g. if the user writes in Italian, respond in natural and fluent Italian; if in English, respond in English), unless explicitly instructed otherwise.\n"
            "The user wants to create, schedule, or propose an automation/loop.\n"
            "Explain your proposal clearly to the user, and include an exact ```automation_proposal fenced code block containing a valid JSON object matching this schema:\n"
            "{\n"
            '  "id": "auto_id_univoco_snake_case",\n'
            '  "name": "Nome Descrittivo Automazione",\n'
            '  "description": "Descrizione chiara del task",\n'
            '  "triggers": [{"id": "trg_1", "type": "cron", "cron_expression": "0 8 * * *"}],\n'
            '  "workflow": {\n'
            '    "initial_step_id": "step_1",\n'
            '    "steps": [\n'
            '      {\n'
            '        "step_id": "step_1",\n'
            '        "name": "Nome Step",\n'
            '        "type": "deterministic_action",\n'
            '        "action_or_tool": "nome_tool",\n'
            '        "parameters": {}\n'
            '      }\n'
            '    ]\n'
            '  },\n'
            '  "permission_policy": {\n'
            '    "allowed_tools": ["nome_tool"],\n'
            '    "allowed_registries": ["mcp", "email", "code"]\n'
            '  },\n'
            '  "budget": {\n'
            '    "max_duration_seconds": 120,\n'
            '    "max_tokens": 10000\n'
            '  }\n'
            "}\n"
            f"{UNTRUSTED_CONTEXT_POLICY}\n"
            "Inform the user that they can inspect the proposal, run a safe Dry-Run test, or activate the automation with one click."
        )
    else:
        system_prompt = (
            f"Current System Date and Time: {now_str}\n"
            "You are the Homelab AI Management Agent (mode: PLAN).\n"
            "Language Directive: English is your internal instruction language. ALWAYS detect and respond in the language used by the user in their message (e.g. if the user writes in Italian, respond in natural and fluent Italian; if in English, respond in English), unless explicitly instructed otherwise.\n"
            "Generate a numbered step-by-step action plan (maximum 5 steps) specifically tailored to fulfill the user's request "
            "using the tools and connected MCP servers available in the system.\n"
            f"{UNTRUSTED_CONTEXT_POLICY}\n"
            "Reply ONLY with the numbered list of execution steps."
        )

    prompt_sections = []
    if memory_context:
        prompt_sections.append(f"Conversational memory context:\n{memory_context}")

    if prefetch_data and prefetch_data.get("summary_text"):
        wrapped_evidence = wrap_untrusted_web_evidence(
            query=prefetch_data.get("query", task),
            formatted_content=prefetch_data.get("summary_text", ""),
            sources=prefetch_data.get("sources", [])
        )
        prompt_sections.append(wrapped_evidence)

    prompt_sections.append(f"User Request: '{task}'")
    user_prompt = "\n\n".join(prompt_sections)

    llm_plan_res = llm_calls.call_llm(user_prompt, system_prompt=system_prompt, max_tokens=4096, temperature=0.2, reasoning_budget=budget, model=model, stream_mode="all", reasoning_phase="Pianificazione Strategica", images=state.get("images"))
    llm_plan = llm_plan_res.get("content", "") if isinstance(llm_plan_res, dict) else ""
    plan_steps = []
    if llm_plan:
        for line in llm_plan.split("\n"):
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith("-") or line.startswith("*")):
                cleaned = re.sub(r'^\d+[\.\)]\s*|^[-*]\s*', '', line).strip()
                if cleaned:
                    plan_steps.append(cleaned)

    plan_structure = generate_plan_structure(task, user_prompt, model=model)

    if not plan_steps and plan_structure:
        plan_steps = [s.get("description", "") for s in plan_structure["steps"] if s.get("description")]

    formatted_steps_str = "\n".join(f"{i+1}. {step}" for i, step in enumerate(plan_steps))
    formatted_plan = f"Piano multi-step generato per: '{task}'\n\nPassaggi di esecuzione:\n{formatted_steps_str}"
    formatted_plan += "\n\nNota: Stato 'dry-run' completato. In attesa di conferma per l'esecuzione dei tool in sequenza."

    if is_automation_request:
        direct_answer = llm_plan or "Ho generato la proposta di automazione richiesta."
    else:
        direct_answer = "Ho generato un piano di esecuzione. Scegli se eseguirlo o modificarlo."

    plan = {
        "mode": "plan",
        "tool_needed": False,
        "direct_answer": direct_answer,
        "multi_step": True,
        "plan_steps": plan_steps,
        "plan_structure": plan_structure,
        "is_automation": is_automation_request,
    }

    reasoning = llm_plan_res.get("reasoning_content") if isinstance(llm_plan_res, dict) else None

    if state.get("execute"):
        return execute_plan_node(state)

    return {
        "plan": plan,
        "plan_structure": plan_structure,
        "final_response": plan["direct_answer"],
        "reasoning_content": reasoning
    }
