import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("router")

LLAMA_CPP_URL = config.LLAMA_CPP_URL.rstrip('/')
DEFAULT_MODEL = config.DEFAULT_MODEL

_capabilities_cache: Dict[str, Any] = {"summary": "", "timestamp": 0}
CAPABILITIES_CACHE_TTL = 180  # 3 minuti di cache TTL per MetaMCP tools


@dataclass
class RouteDecision:
    mode: str  # "chat" | "ask" | "act" | "plan"
    web_search_needed: bool = False
    web_search_query: Optional[str] = None
    reasoning: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "web_search_needed": self.web_search_needed,
            "web_search_query": self.web_search_query,
            "reasoning": self.reasoning,
        }


def get_dynamic_capabilities_summary(force_refresh: bool = False) -> str:
    """
    Restituisce un riassunto compatto delle capabilities del sistema:
    1. Capabilities Native/Interne (sempre presenti: Calendar, Automations, Email, Sandbox)
    2. Capabilities Esterne MCP (scoperte dinamicamente da MetaMCP e cachate con TTL di 3 minuti).
    """
    now = time.time()
    if not force_refresh and _capabilities_cache["summary"] and (now - _capabilities_cache["timestamp"] < CAPABILITIES_CACHE_TTL):
        return _capabilities_cache["summary"]

    internal_capabilities = (
        "1. Internal Native Capabilities (always available):\n"
        "   - Calendar & Events: create, update, delete, search, inspect calendar events, check availability\n"
        "   - Automations & Loops: schedule, inspect, and trigger autonomous homelab workflows\n"
        "   - Email & Briefing: fetch unread emails, generate morning briefings, create email drafts\n"
        "   - Python Sandbox: run arbitrary python code, calculations, and data transformations\n"
    )

    mcp_lines = []
    try:
        from registry.manager import get_registry_manager
        manager = get_registry_manager()
        mcp_tools = manager.get_tools_for_mode(["metamcp"])
        if mcp_tools:
            mcp_lines.append("2. External MCP Tools (dynamically connected to MetaMCP):")
            for t in mcp_tools:
                t_name = str(t.get("name", "")).replace("proxmox-mcp__", "")
                t_desc = str(t.get("description", "")).strip().split("\n")[0][:80]
                if t_name:
                    mcp_lines.append(f"   - {t_name}: {t_desc}")
    except Exception as e:
        logger.warning(f"Errore recupero dinamico tool MetaMCP per il router: {e}")

    if not mcp_lines:
        mcp_lines = [
            "2. External MCP Tools (Proxmox VE & Homelab Infrastructure):\n"
            "   - LXC & VM management: list, inspect status, start, stop, snapshot, rollback, execute shell commands\n"
            "   - Network & Infrastructure: IPAM allocate/release IP, Pi-hole DNS records, Nginx Proxy Manager hosts\n"
        ]

    summary = internal_capabilities + "\n" + "\n".join(mcp_lines)
    _capabilities_cache["summary"] = summary
    _capabilities_cache["timestamp"] = now
    return summary


def is_purely_visual_request(task: str) -> bool:
    """Verifica se una richiesta con immagini è puramente percettiva/descrittiva."""
    if not task or not task.strip():
        return True
    task_lower = task.lower().strip()
    external_keywords = [
        "cerca", "search", "trova", "prezzo", "prezzi", "costo", "costi", "quanto costa",
        "dove comprare", "comprare", "acquistare", "vendita", "negozi", "store",
        "notizie", "news", "recensioni", "review", "scheda tecnica", "specifiche",
        "manuale", "firmware", "driver", "pinout", "compatibile", "compatibilità",
        "disponibilità", "mercato", "aggiornamenti", "online", "internet", "web", "google"
    ]
    if any(kw in task_lower for kw in external_keywords):
        return False

    visual_keywords = [
        "cosa vedi", "descrivi", "cosa c'è", "spiega l'immagine", "guarda questa",
        "analizza l'immagine", "analizza e descrivi", "cosa rappresenta", "leggi il testo",
        "trascrivi", "chi c'è", "che colore", "dov'è", "what do you see", "describe", "describe this image"
    ]
    return any(kw in task_lower for kw in visual_keywords)


def route_turn(
    user_input: str,
    previous_mode: Optional[str] = None,
    last_tool_used: Optional[str] = None,
    conversation_context: Optional[str] = None,
    force_mode: Optional[str] = None,
    model: Optional[str] = None,
    has_images: bool = False,
    web_search_override: Optional[Any] = None,
) -> RouteDecision:
    """
    Router unificato, intelligente e dinamico:
    Classifica la modalità operativa (chat, ask, act, plan) e determina la necessità di web prefetch
    sfruttando il modello attivo, il contesto multi-turn e le capabilities scoperte dinamicamente.
    """
    if not user_input or not user_input.strip():
        return RouteDecision(mode="chat", web_search_needed=False, reasoning="Empty user input")

    input_lower = user_input.strip().lower()
    clean_input = input_lower.rstrip("?!.,:; \t").strip()

    # 0. Fast shortcut: se la modalità è forzata manualmente e la ricerca web è disattivata ('off'),
    # non serve chiamare l'LLM: modalità e stato web sono già determinati al 100% dall'utente (0ms latenza).
    if force_mode and force_mode.lower() in ["chat", "ask", "act", "plan"] and (web_search_override is False or web_search_override == "off"):
        logger.info(f"Fast shortcut: force_mode='{force_mode}' with web_search='off'. Returning directly without LLM call.")
        return RouteDecision(
            mode=force_mode.lower(),
            web_search_needed=False,
            web_search_query=None,
            reasoning=f"User manually forced mode='{force_mode}' with web search disabled"
        )

    # 1. Fast shortcut per saluti e convenevoli banali (0ms latenza, salvo web search forzata 'on')
    chat_greetings = [
        "ciao", "salve", "buongiorno", "buonasera", "grazie", "grazie mille", "chi sei",
        "come ti chiami", "come stai", "cosa sai fare", "hello", "hi", "hey",
        "good morning", "good evening", "thanks", "thank you", "who are you", "what is your name", "how are you"
    ]
    if web_search_override is not True and web_search_override != "on":
        if any(clean_input == g or clean_input.startswith(f"{g} ") or clean_input.endswith(f" {g}") for g in chat_greetings):
            mode = "chat"
            if force_mode and force_mode.lower() in ["chat", "ask", "act", "plan"]:
                mode = force_mode.lower()
            logger.info(f"Fast shortcut: greeting classified as mode={mode}, web_search=False for '{user_input}'")
            return RouteDecision(mode=mode, web_search_needed=False, reasoning="Conversational greeting/pleasantry")

    # 2. Fast shortcut per analisi visiva pura senza ricerca esterna
    if web_search_override is not True and web_search_override != "on":
        if has_images and is_purely_visual_request(user_input):
            mode = "chat"
            if force_mode and force_mode.lower() in ["chat", "ask", "act", "plan"]:
                mode = force_mode.lower()
            logger.info(f"Fast shortcut: visual direct request classified as mode={mode}, web_search=False for '{user_input}'")
            return RouteDecision(mode=mode, web_search_needed=False, reasoning="Direct visual perception")

    # 3. Fast shortcut per pianificazioni esplicite
    plan_keywords = [
        "pianifica", "piano per", "crea piano", "prepara sequenza", "workflow", "progetta architettura", "strategia",
        "plan a", "plan for", "create a plan", "architecture plan", "migration plan", "multi-step plan"
    ]
    explicit_plan = any(kw in input_lower for kw in plan_keywords)

    # 4. Fast shortcuts deterministici per comandi container/infrastruttura standard (0ms latenza)
    if any(cmd in input_lower for cmd in [
        "spegni ct", "riavvia ct", "stop ct", "start ct", "reboot lxc", "reboot ct",
        "mostrami i container", "list containers", "lista container", "stato container",
        "exec_lxc_command", "exec hostname", "fai un backup del ct"
    ]) or (re.search(r'\b(ct|container|vmid)\s*\d+\b', input_lower) and any(w in input_lower for w in ["stato", "status", "riavvia", "restart", "reboot", "stop", "spegni", "start", "avvia", "backup"])):
        mode = "act" if not force_mode else force_mode.lower()
        return RouteDecision(mode=mode, web_search_needed=False, reasoning="Deterministic container operation")

    if any(q in input_lower for q in ["dimmi i file in /opt", "what files are in /opt", "nella cartella /opt"]):
        mode = "act" if not force_mode else force_mode.lower()
        return RouteDecision(mode=mode, web_search_needed=False, reasoning="Deterministic filesystem inspection")

    if any(input_lower.startswith(p) for p in [
        "cosa è un container", "what is a container", "differenza tra container e vm", "spiegami come funziona zfs",
        "what is proxmox", "come funziona il protocollo http", "chi ha inventato linux"
    ]):
        mode = "ask" if not force_mode else force_mode.lower()
        return RouteDecision(mode=mode, web_search_needed=False, reasoning="Deterministic conceptual query")

    # 5. Modello attivo & Capabilities dinamiche
    import providers
    capabilities_str = get_dynamic_capabilities_summary()
    effective_model = model or providers.get_active_model_name() or DEFAULT_MODEL

    extra_instructions = []
    if force_mode and force_mode.lower() in ["chat", "ask", "act", "plan"]:
        extra_instructions.append(f"- NOTE: The operational mode is already preset to '{force_mode.lower()}'. Set 'mode': '{force_mode.lower()}'.")
    if web_search_override is True or web_search_override == "on":
        extra_instructions.append("- NOTE: The user explicitly enabled Web Search. You MUST set 'web_search_needed': true and generate a high-quality, concise 'web_search_query' (3-6 words, no filler words) for this request.")
    elif web_search_override is False or web_search_override == "off":
        extra_instructions.append("- NOTE: Web Search is disabled by user. Set 'web_search_needed': false and 'web_search_query': null.")

    user_directives = ("\nUser Directives:\n" + "\n".join(extra_instructions) + "\n") if extra_instructions else ""

    system_prompt = f"""You are the intelligent Router for the Homelab AI Management Assistant.
Your task is to classify the user request into an operational mode and determine if an external web search prefetch is needed.

System Capabilities Available:
{capabilities_str}

Operational Modes:
- 'act': The user wants to perform actions, execute commands, or manage resources using local tools (Proxmox LXC/VMs, local shell commands, DNS, proxy, calendar events, automations, email drafts).
  CRITICAL CONTINUITY POLICY: In an ongoing chat thread where the previous turn was 'act' (or tools were used), follow-up user requests that modify, continue, refine, delete, or refer to that action (e.g. "la descrizione deve contenere...", "ora eliminalo", "cambia la data a domani", "esegui anche su ct 100", "e per la cartella /root?") MUST remain in 'act'.
- 'ask': External research, conceptual/theoretical explanations, technology news, modern AI models, software comparisons, documentation lookup, or questions about the agent itself.
- 'chat': Casual conversation, chit-chat, greetings, or direct image descriptions without tools.
- 'plan': Complex multi-step migrations, high-level architectural redesigns, or designing multi-phase workflows.

Web Search Policy:
- web_search_needed = true PROACTIVELY for questions about technologies, software libraries, AI models, hardware, tools, tutorials, news, benchmarks, comparisons, releases, or external world facts. When in doubt for informational questions, prefer true to ensure the assistant has fresh and accurate web context.
- web_search_needed = false ONLY when:
  1. The request strictly targets local homelab infrastructure and tools (Proxmox LXC/VMs, local containers, local files, local calendar, local automations, local bash) where external web information is irrelevant.
  2. Casual greetings, chit-chat, pleasantries, or questions about the assistant itself.
- web_search_query: If web_search_needed is true, formulate a concise, targeted search query (3-6 words, no filler words). If false, set to null.
{user_directives}
Reply EXCLUSIVELY with a JSON object matching this schema:
{{
  "mode": "chat" | "ask" | "act" | "plan",
  "web_search_needed": true | false,
  "web_search_query": "concise query" | null,
  "reasoning": "brief explanation"
}}"""

    context_parts = []
    if conversation_context:
        context_parts.append(f"Recent Conversation Context:\n{conversation_context[-1200:]}")
    if previous_mode:
        context_parts.append(f"Active Thread Mode: {previous_mode.upper()}")
    if last_tool_used:
        context_parts.append(f"Last Tool Used: {last_tool_used}")
    context_parts.append(f"User Request: '{user_input}'")
    user_prompt = "\n\n".join(context_parts)

    url = f"{LLAMA_CPP_URL}/chat/completions"
    payload = {
        "model": effective_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 120,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_object"}
    }

    try:
        res = requests.post(url, json=payload, timeout=25)
        if res.status_code == 200:
            msg_obj = res.json()["choices"][0]["message"]
            raw_content = (msg_obj.get("content") or "").strip()
            # Pulisci eventuali tag think o markdown
            clean_content = re.sub(r'<think>.*?</think>', '', raw_content, flags=re.DOTALL).strip()
            clean_json = re.sub(r'```(?:json)?', '', clean_content).strip()

            parsed = {}
            try:
                json_match = re.search(r'\{.*\}', clean_json, flags=re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                else:
                    parsed = json.loads(clean_json)
            except Exception:
                mode_match = re.search(r'\b(chat|ask|act|plan)\b', clean_content.lower())
                if mode_match:
                    parsed = {"mode": mode_match.group(1), "web_search_needed": (mode_match.group(1) == "ask")}

            mode = str(parsed.get("mode", "")).lower().strip()
            if mode not in ["chat", "ask", "act", "plan"]:
                mode = "act" if previous_mode == "act" else "chat"

            web_search_needed = bool(parsed.get("web_search_needed", False))
            web_search_query = parsed.get("web_search_query")
            if web_search_query and isinstance(web_search_query, str):
                web_search_query = web_search_query.strip()
                if web_search_query.lower() in ["null", "none", ""]:
                    web_search_query = None

            # Overrides
            if force_mode and force_mode.lower() in ["chat", "ask", "act", "plan"]:
                mode = force_mode.lower()
            if explicit_plan and not force_mode:
                mode = "plan"

            if web_search_override is False or web_search_override == "off":
                web_search_needed = False
            elif web_search_override is True or web_search_override == "on":
                web_search_needed = True
                if not web_search_query:
                    web_search_query = user_input

            decision = RouteDecision(
                mode=mode,
                web_search_needed=web_search_needed,
                web_search_query=web_search_query,
                reasoning=parsed.get("reasoning")
            )
            logger.info(f"Model router decision: mode={decision.mode}, web_search={decision.web_search_needed}, query='{decision.web_search_query}' (reason: {decision.reasoning}) for '{user_input[:50]}'")
            return decision

    except Exception as e:
        logger.warning(f"Chiamata LLM router fallita o timeout ({e}). Applicazione fallback semantico resiliente.")

    # 5. Fallback semantico resiliente (se llama.cpp offline/timeout)
    fallback_mode = "chat"
    if explicit_plan:
        fallback_mode = "plan"
    elif previous_mode == "act":
        fallback_mode = "act"
    elif any(kw in input_lower for kw in ["container", "ct", "lxc", "vm", "proxmox", "evento", "calendario", "automazione"]):
        fallback_mode = "act"
    elif any(kw in input_lower for kw in ["cerca", "search", "cosa è", "chi è", "perché", "confronta", "differenza", "spiegami", "parlami", "raccontami"]):
        fallback_mode = "ask"

    if force_mode and force_mode.lower() in ["chat", "ask", "act", "plan"]:
        fallback_mode = force_mode.lower()

    web_needed = (fallback_mode == "ask") and not any(kw in input_lower for kw in ["container", "ct", "lxc", "vm", "proxmox", "calendario", "evento"])
    if web_search_override is False or web_search_override == "off":
        web_needed = False
    elif web_search_override is True or web_search_override == "on":
        web_needed = True

    return RouteDecision(
        mode=fallback_mode,
        web_search_needed=web_needed,
        web_search_query=user_input if web_needed else None,
        reasoning="Fallback decision due to router timeout/offline"
    )


def classify_mode(
    user_input: str,
    force_mode: Optional[str] = None,
    model: Optional[str] = None,
    has_images: bool = False,
    conversation_context: Optional[str] = None,
    previous_mode: Optional[str] = None,
    last_tool_used: Optional[str] = None,
) -> str:
    """Wrapper di retrocompatibilità che restituisce solo la stringa della modalità."""
    decision = route_turn(
        user_input=user_input,
        previous_mode=previous_mode,
        last_tool_used=last_tool_used,
        conversation_context=conversation_context,
        force_mode=force_mode,
        model=model,
        has_images=has_images
    )
    return decision.mode
