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
    Classifica l'input dell'utente in una delle 4 modalità operative in base a intento e complessità:
    - chat: conversazione naturale, saluti, domande aperte e percezione visiva diretta (0 tool overhead)
    - ask: compiti leggeri/analitici di ricerca (ricerca web preventiva, tool web_search, script/calcoli shell, inspect_image)
    - act: task agentici operativi su qualsiasi server MCP connesso, consultazione stati, modifica stato, esecuzione comandi
    - plan: pianificazione strategica di workflow multi-step complessi
    """
    if force_mode:
        forced = force_mode.lower().strip()
        if forced in ["chat", "ask", "act", "plan"]:
            logger.info(f"Mode forced via request/CLI: {forced}")
            return forced

    if not user_input or not user_input.strip():
        return "chat"

    input_lower = user_input.strip().lower()

    # Se ci sono immagini allegate e l'utente chiede una descrizione o analisi visiva diretta
    if has_images and any(kw in input_lower for kw in ["cosa vedi", "descrivi", "analizza l'immagine", "cosa c'è", "spiega l'immagine", "guarda questa"]):
        logger.info(f"Visual direct request with image classified as mode=chat for input='{user_input}'")
        return "chat"

    # 1. Regole prioritarie per intenzione esplicita di pianificazione multi-step
    if any(kw in input_lower for kw in ["pianifica", "piano per", "crea piano", "prepara sequenza", "workflow", "migra", "progetta architettura"]):
        logger.info(f"Rule router classified mode=plan for input='{user_input}'")
        return "plan"

    # 2. Riconoscimento conferme e follow-up operativi (es. 'Procedi con base', 'Sì procedi', 'Confermo', 'Vai')
    confirmation_triggers = ["procedi", "confermo", "vai", "esegui", "fallo", "prosegui", "ok procedi", "si procedi", "sì procedi", "clona quello", "crea quello"]
    if any(kw in input_lower for kw in confirmation_triggers):
        if conversation_context and any(term in conversation_context.lower() for term in ["container", "template", "vmid", "proxmox", "tool", "servizio", "lxc", "deploy"]):
            logger.info(f"Rule router classified mode=act for confirmation/follow-up with context for input='{user_input}'")
            return "act"
        # Anche senza contesto esplicito, 'procedi con...' o 'esegui...' indica azione
        if any(kw in input_lower for kw in ["procedi con", "esegui", "fallo", "clona", "applica"]):
            logger.info(f"Rule router classified mode=act for action imperative input='{user_input}'")
            return "act"

    # 3. Regole prioritarie per azioni e consultazioni operative su Homelab/Proxmox/MCP
    infra_terms = ["container", "lxc", "vmid", "proxmox", "immich", "pihole", "dns", "npm", "ipam", "template", "storage", "snapshot", "rollback", "nodo"]
    action_terms = [
        "avvia", "ferma", "riavvia", "arresta", "elimina", "cancella", "crea", "clona",
        "applica", "snapshot", "rollback", "esegui comando", "modifica", "configura",
        "informazioni sul container", "info container", "stato del container", "stato container",
        "lista container", "elenco container", "mostrami i container", "ispeziona", "log del container"
    ]

    has_infra = any(term in input_lower for term in infra_terms)
    has_action = any(term in input_lower for term in action_terms)

    if has_action or (has_infra and any(verb in input_lower for verb in ["dammi", "mostra", "controlla", "stato", "info", "quali", "come sta", "trova", "vedi", "dimmi", "risorse"])):
        logger.info(f"Rule router classified mode=act for homelab operation/query input='{user_input}'")
        return "act"

    # 4. Regole prioritarie per domande informative o discovery tool
    if any(kw in input_lower for kw in ["quali tool", "elenco tool", "cosa puoi fare", "che strumenti hai"]):
        logger.info(f"Rule router classified mode=ask for input='{user_input}'")
        return "ask"

    # 5. Classificazione neurale tramite LLM (senza riferimenti hardcodati a singoli vendor/tool)
    prompt = f"""Analizza la seguente richiesta dell'utente e rispondi ESATTAMENTE con UNA SOLA PAROLA scelta tra:
- chat (per saluti, convenevoli, conversazione generale o descrizione diretta di un'immagine)
- ask (per ricerche web informative esterne, domande teoriche o calcoli/script analitici)
- act (per interagire con l'infrastruttura Proxmox/LXC/VM, consultare stati/info attive o modificare risorse tramite tool MCP)
- plan (per pianificare architetture complesse o sequenze di operazioni multi-step)

Richiesta: "{user_input}"

Risposta (solo chat, ask, act o plan):"""

    url = f"{LLAMA_CPP_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": model or DEFAULT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 64,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            msg_obj = res.json()["choices"][0]["message"]
            raw_content = msg_obj.get("content") or ""
            reasoning = msg_obj.get("reasoning_content") or msg_obj.get("thinking") or msg_obj.get("reasoning") or ""

            full_text = f"{reasoning} {raw_content}".strip().lower()
            match = re.search(r'\b(chat|ask|act|plan)\b', full_text)
            if match:
                mode = match.group(1)
                logger.info(f"Neural router classified mode={mode} for input='{user_input}'")
                return mode
    except Exception as e:
        logger.warning(f"Neural router call skipped ({e}). Using rule-based fallback.")

    # 6. Fallback euristico generale basato sulla natura della richiesta
    if any(kw in input_lower for kw in ["ciao", "salut", "chi sei", "buongiorno", "buonasera", "grazie"]):
        fallback = "chat"
    elif any(kw in input_lower for kw in ["avvia", "ferma", "riavvia", "crea", "clona", "elimina", "exec", "stato", "lista", "container", "lxc", "proxmox"]):
        fallback = "act"
    elif any(kw in input_lower for kw in ["qual", "cosa", "come", "dove", "quando", "perché", "calcola", "cerca", "trova", "analizza", "spieg"]):
        fallback = "ask"
    else:
        fallback = "chat"

    logger.info(f"Rule router fallback classified mode={fallback} for input='{user_input}'")
    return fallback

