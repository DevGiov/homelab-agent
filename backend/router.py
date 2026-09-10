import logging
import re
from typing import Optional

import requests

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("router")

LLAMA_CPP_URL = config.LLAMA_CPP_URL.rstrip('/')
DEFAULT_MODEL = config.DEFAULT_MODEL

def classify_mode(
    user_input: str,
    force_mode: Optional[str] = None,
    model: Optional[str] = None,
    has_images: bool = False,
    conversation_context: Optional[str] = None
) -> str:
    """
    Classifies the user input into one of 4 operational modes based on intent and complexity:
    - chat: natural conversation, greetings, open-ended chit-chat, and direct visual perception (0 tool overhead)
    - ask: information-seeking, external web research, theoretical/conceptual queries, docs lookup
    - act: agentic operational tasks on Proxmox/LXC/VM/host, inspecting live status, executing commands, mutating resources
    - plan: strategic planning of complex multi-step workflows, migrations, or architecture design
    """
    if force_mode:
        forced = force_mode.lower().strip()
        if forced in ["chat", "ask", "act", "plan"]:
            logger.info(f"Mode forced via request/CLI: {forced}")
            return forced

    if not user_input or not user_input.strip():
        return "chat"

    input_lower = user_input.strip().lower()

    # Direct visual analysis request with images attached
    if has_images and any(kw in input_lower for kw in [
        "cosa vedi", "descrivi", "analizza l'immagine", "cosa c'è", "spiega l'immagine", "guarda questa",
        "what do you see", "describe this image", "describe the image", "analyze this image"
    ]):
        logger.info(f"Visual direct request with image classified as mode=chat for input='{user_input}'")
        return "chat"

    # 1. Multi-step planning intent
    plan_keywords = [
        "pianifica", "piano per", "crea piano", "prepara sequenza", "workflow", "migra", "progetta architettura", "strategia",
        "plan a", "plan for", "create a plan", "architecture plan", "migration plan", "multi-step plan"
    ]
    if any(kw in input_lower for kw in plan_keywords):
        logger.info(f"Rule router classified mode=plan for input='{user_input}'")
        return "plan"

    # 2. Confirmations & operational follow-ups (e.g. 'Procedi con base', 'Go ahead', 'Confermo')
    confirmation_triggers = [
        "procedi", "confermo", "vai", "esegui", "fallo", "prosegui", "ok procedi", "si procedi", "sì procedi", "clona quello", "crea quello", "applica",
        "proceed", "confirm", "go ahead", "yes proceed", "execute it", "do it", "apply that"
    ]
    if any(kw in input_lower for kw in confirmation_triggers):
        if conversation_context and any(term in conversation_context.lower() for term in ["container", "template", "vmid", "proxmox", "tool", "servizio", "service", "lxc", "deploy"]):
            logger.info(f"Rule router classified mode=act for confirmation/follow-up with context for input='{user_input}'")
            return "act"
        if any(kw in input_lower for kw in ["procedi con", "esegui", "fallo", "clona", "applica", "proceed with", "execute", "apply"]):
            logger.info(f"Rule router classified mode=act for action imperative input='{user_input}'")
            return "act"

    # 3. Purely conceptual / educational queries (ASK, NOT ACT even if mentioning container/lxc/docker/proxmox)
    # e.g. "cosa è un container lxc", "what is proxmox", "differenza tra docker e lxc", "how does a container work"
    is_conceptual_question = (
        input_lower.startswith(("cosa è", "cos'è", "cosa sono", "qual è la differenza", "quali sono le differenze", "come funziona", "spiegami come", "spiegami cosa", "perché si usa", "perché usare"))
        or input_lower.startswith(("what is", "what are", "what's", "difference between", "how does", "how do", "explain how", "explain what", "why use", "why is"))
    )
    has_specific_target_instance = bool(re.search(r'\b(ct|container|vmid|vm)\s*\d+\b|\b\d{3}\b', input_lower))
    has_directory_inspection = any(p in input_lower for p in ["/opt", "/etc", "/var", "/tmp", "/home", "/root", "cartella", "directory", "cartelle", "directories", "folder"])
    has_command_execution = any(c in input_lower for c in ["esegui", "run", "exec", "execute", "comando", "command", "ls", "cat", "ps", "kill", "reboot", "restart"])

    if is_conceptual_question and not has_specific_target_instance and not has_directory_inspection and not has_command_execution:
        logger.info(f"Rule router classified mode=ask for conceptual query input='{user_input}'")
        return "ask"

    # 4. Tool discovery queries
    if any(kw in input_lower for kw in [
        "quali tool", "elenco tool", "cosa puoi fare", "che strumenti hai",
        "what tools", "list tools", "what can you do", "which tools"
    ]):
        logger.info(f"Rule router classified mode=ask for tool discovery input='{user_input}'")
        return "ask"

    # 5. Infrastructure & operational actions on Proxmox/Homelab/MCP (ACT)
    # Action verbs (IT & EN)
    action_verbs = [
        "avvia", "ferma", "riavvia", "arresta", "elimina", "cancella", "crea", "clona",
        "applica", "snapshot", "rollback", "esegui", "lancia", "modifica", "configura",
        "spegni", "accendi", "stoppa", "killa", "uccidi", "termina", "ripristina", "installa",
        "aggiorna", "scarica", "fai un backup", "fai backup", "fai", "pinga", "ping", "leggi", "mostra", "dimmi", "dammi", "prendi",
        "run", "exec", "execute", "start", "stop", "restart", "reboot", "shutdown", "poweroff",
        "kill", "create", "clone", "delete", "destroy", "remove", "restore", "install",
        "update", "upgrade", "download", "backup", "check", "inspect", "show", "tell me", "tell",
        "list", "get", "find", "give", "give me"
    ]
    # Infrastructure and local entities
    infra_entities = [
        "container", "containers", "lxc", "ct", "vm", "vms", "vmid", "proxmox", "pve",
        "immich", "pihole", "dns", "npm", "ipam", "template", "templates", "storage", "nodo",
        "node", "host", "macchina", "macchine", "nginx", "servizio", "servizi", "service", "services",
        "daemon", "zfs", "disco", "disk", "ram", "memory", "memoria", "cpu", "ip"
    ]
    # Filesystem and command inspection keywords
    filesystem_inspection = [
        "ls", "cat", "dir", "cartella", "directory", "folder", "file", "files",
        "/opt", "/etc", "/var", "/tmp", "/home", "/root", "processi", "processes", "ps", "top",
        "systemctl", "journalctl", "docker ps", "docker", "pveversion", "nvidia-smi", "df", "free", "uptime"
    ]
    inspection_phrases = [
        "cosa c'è", "cosa c'e", "quali file", "elenca", "elencami", "lista", "listami", "mostrami", "fammi vedere",
        "dammi le specifiche", "dammi informazioni", "dammi info", "informazioni su", "informazioni sul", "info su", "info sul",
        "stato del", "stato container", "info container", "specifiche", "dettagli su", "dettagli del",
        "what is in", "what files", "list files", "show me", "give me the specs", "give me info", "information about", "info about", "container status", "status of"
    ]

    has_action_verb = any(verb in input_lower for verb in action_verbs)
    has_infra_entity = any(entity in input_lower for entity in infra_entities)
    has_fs_inspection = any(fs in input_lower for fs in filesystem_inspection)
    has_insp_phrase = any(phrase in input_lower for phrase in inspection_phrases)

    # If the user asks to run or inspect something on infrastructure, filesystem, or specific container
    if (
        (has_action_verb and (has_infra_entity or has_fs_inspection or has_specific_target_instance))
        or (has_insp_phrase and (has_infra_entity or has_fs_inspection or has_specific_target_instance))
        or (has_specific_target_instance and (has_action_verb or has_fs_inspection or has_insp_phrase))
        or (any(cmd in input_lower for cmd in ["reboot host", "restart nginx", "kill process", "docker ps", "docker compose", "pveversion", "nvidia-smi"]))
        or (has_fs_inspection and has_action_verb)
    ):
        logger.info(f"Rule router classified mode=act for homelab operation/query input='{user_input}'")
        return "act"

    # 6. General Web Research & External Info (ASK)
    web_research_keywords = [
        "cerca sul web", "cerca online", "cerca su google", "cerca", "search web", "search online", "google",
        "prezzo", "prezzi", "price", "prices", "costo", "cost", "quanto costa", "how much",
        "recensioni", "reviews", "ultime notizie", "latest news", "news", "notizie",
        "documentazione", "documentation", "manuale d'uso", "manual", "datasheet",
        "chi ha vinto", "who won", "qual è la capitale", "what is the capital", "meteo", "weather"
    ]
    if any(kw in input_lower for kw in web_research_keywords):
        logger.info(f"Rule router classified mode=ask for web research input='{user_input}'")
        return "ask"

    # 7. Pure Chit-chat & Greetings (CHAT)
    chat_greetings = [
        "ciao", "salve", "buongiorno", "buonasera", "grazie", "chi sei", "come ti chiami", "come stai", "cosa sai fare",
        "hello", "hi", "hey", "good morning", "good evening", "thanks", "thank you", "who are you", "what is your name", "how are you"
    ]
    if any(kw == input_lower or input_lower.startswith(f"{kw} ") or input_lower.endswith(f" {kw}") for kw in chat_greetings):
        logger.info(f"Rule router classified mode=chat for conversational input='{user_input}'")
        return "chat"

    # 8. Neural Classification via LLM (English prompt, reasoning-safe parsing)
    prompt = f"""Analyze the following user request and classify it into EXACTLY ONE of these 4 operational modes:
- chat: Casual conversation, greetings, pleasantries, philosophical/identity questions, or direct visual description of an image without tools.
- ask: External web search queries, general research, pricing/news lookup, theoretical/conceptual questions, or documentation reading.
- act: Interacting with local infrastructure (Proxmox, LXC containers, VMs, Docker, host commands, filesystem inspection, DNS, proxy, network, checking status or executing commands).
- plan: Strategic planning of complex multi-step migrations, architectural redesigns, or multi-phase workflows.

Request: "{user_input}"

Reply with ONLY the single mode word (chat, ask, act, or plan):"""

    url = f"{LLAMA_CPP_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": model or DEFAULT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 32,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    try:
        res = requests.post(url, json=payload, timeout=3)
        if res.status_code == 200:
            msg_obj = res.json()["choices"][0]["message"]
            raw_content = (msg_obj.get("content") or "").strip()
            # Clean think tags if model returned reasoning in content
            clean_content = re.sub(r'<think>.*?</think>', '', raw_content, flags=re.DOTALL).strip().lower()

            # Inspect clean_content FIRST to avoid reasoning leak
            match = re.search(r'\b(chat|ask|act|plan)\b', clean_content)
            if match:
                mode = match.group(1)
                logger.info(f"Neural router classified mode={mode} for input='{user_input}'")
                return mode
    except Exception as e:
        logger.warning(f"Neural router call skipped or timed out ({e}). Using rule-based fallback.")

    # 9. Smart Fallback based on semantic features
    if has_action_verb or has_infra_entity or has_fs_inspection:
        fallback = "act"
    elif any(kw in input_lower for kw in ["qual", "cosa", "come", "dove", "quando", "perché", "what", "how", "where", "when", "why", "explain", "spiega"]):
        fallback = "ask"
    elif any(kw in input_lower for kw in chat_greetings):
        fallback = "chat"
    else:
        fallback = "chat"

    logger.info(f"Rule router fallback classified mode={fallback} for input='{user_input}'")
    return fallback
