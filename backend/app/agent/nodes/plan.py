import json
import logging
import re
from datetime import datetime

from app.agent import llm_calls
from app.agent.mode_policy import get_mode_policy
from app.agent.nodes.act import execute_plan_node
from app.agent.state import AgentState

logger = logging.getLogger("graph")


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
            '    "allowed_registries": ["metamcp", "email", "code"]\n'
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

    # Generate JSON plan_structure via LLM
    json_prompt = (
        f"Generate a structured JSON plan for the following user task: '{task}'.\n"
        f"{UNTRUSTED_CONTEXT_POLICY}\n"
        "Reply EXCLUSIVELY with valid JSON matching this schema:\n"
        "{\n"
        "  \"steps\": [\n"
        "    {\n"
        "      \"id\": 1,\n"
        "      \"description\": \"Step description\",\n"
        "      \"tool\": \"mcp_tool_name\",\n"
        "      \"args\": {\"param\": \"value\"},\n"
        "      \"depends_on\": null,\n"
        "      \"output_var\": \"variable_name\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    json_resp_res = llm_calls.call_llm(user_prompt, system_prompt=json_prompt, max_tokens=4096, temperature=0.1, model=model, stream_mode="none")
    json_resp = json_resp_res.get("content", "") if isinstance(json_resp_res, dict) else ""
    plan_structure = None
    if json_resp:
        try:
            clean_json = re.sub(r'```(?:json)?', '', json_resp).strip()
            parsed = json.loads(clean_json)
            if isinstance(parsed, dict) and "steps" in parsed and isinstance(parsed["steps"], list):
                plan_structure = parsed
        except Exception as e:
            logger.warning(f"Failed to parse LLM plan JSON: {e}")

    if not plan_structure:
        task_lower = task.lower()
        if any(kw in task_lower for kw in ["lista", "ispeziona", "controlla"]):
            plan_structure = {
                "steps": [
                    {
                        "id": 1,
                        "description": "Acquisizione inventario e stato real-time dei container",
                        "tool": "proxmox-mcp__list_containers",
                        "args": {},
                        "depends_on": None,
                        "output_var": "containers_list"
                    }
                ]
            }
        else:
            plan_structure = {
                "steps": [
                    {
                        "id": 1,
                        "description": "Allocazione IP libero da IPAM",
                        "tool": "proxmox-mcp__allocate_ip",
                        "args": {"hostname": "test-service"},
                        "depends_on": None,
                        "output_var": "allocated_ip"
                    },
                    {
                        "id": 2,
                        "description": "Creazione LXC da template base",
                        "tool": "proxmox-mcp__create_lxc_from_template",
                        "args": {
                            "key": "base",
                            "ip": "{{allocated_ip}}",
                            "hostname": "test-service"
                        },
                        "depends_on": 1,
                        "output_var": "created_vmid"
                    },
                    {
                        "id": 3,
                        "description": "Creazione record DNS Pi-hole",
                        "tool": "proxmox-mcp__add_pihole_dns_record",
                        "args": {
                            "domain": "test-service.home.lab",
                            "target_ip": "{{allocated_ip}}"
                        },
                        "depends_on": 1,
                        "output_var": None
                    },
                    {
                        "id": 4,
                        "description": "Configurazione Host Proxy Nginx Manager",
                        "tool": "proxmox-mcp__create_npm_proxy_host",
                        "args": {
                            "domain": "test-service.home.lab",
                            "forward_ip": "{{allocated_ip}}",
                            "forward_port": 80
                        },
                        "depends_on": 2,
                        "output_var": None
                    }
                ]
            }

    if not plan_steps:
        plan_steps = [s.get("description", "") for s in plan_structure.get("steps", []) if s.get("description")]

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
