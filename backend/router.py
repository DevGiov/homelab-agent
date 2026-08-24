import logging
import re

import requests

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("router")

LLAMA_CPP_URL = config.LLAMA_CPP_URL.rstrip('/')
DEFAULT_MODEL = config.DEFAULT_MODEL

def classify_mode(user_input: str, force_mode: str = None, model: str = None) -> str:
    """
    Classifies user input into one of 4 modes: 'chat', 'ask', 'act', 'plan'.
    Supports force_mode override, neural classification, and robust rule-matching fallback.
    """
    if force_mode:
        forced = force_mode.lower().strip()
        if forced in ["chat", "ask", "act", "plan"]:
            logger.info(f"Mode forced via request/CLI: {forced}")
            return forced

    if not user_input or not user_input.strip():
        return "chat"

    input_lower = user_input.strip().lower()

    # Priority rule matching for unambiguous user intents
    if any(kw in input_lower for kw in ["crea", "migra", "prepara", "sequenza", "nuovo servizio", "deploy", "setup", "installa", "provision"]):
        logger.info(f"Rule router classified mode=plan for input='{user_input}'")
        return "plan"

    if any(kw in input_lower for kw in ["lista container", "container attivi", "elenco container", "stato container", "avvia", "ferma", "riavvia", "exec", "logs", "snapshot"]):
        logger.info(f"Rule router classified mode=act for input='{user_input}'")
        return "act"

    if any(kw in input_lower for kw in ["tool", "strument", "accesso", "cosa puoi fare"]) and ("qual" in input_lower or "quali" in input_lower or "cosa" in input_lower or "lista" in input_lower):
        logger.info(f"Rule router classified mode=ask for input='{user_input}'")
        return "ask"

    # Neural classification via Llama.cpp
    prompt = f"""Analizza il seguente input dell'utente e rispondi ESATTAMENTE con UNA SOLA PAROLA scelta tra:
- chat (per saluti o conversazione generale)
- ask (per domande informative sui tool disponibili o memoria)
- act (per eseguire un'azione o consultare lo stato di container/template/DNS)
- plan (per pianificare la creazione o migrazione di servizi multi-step)

Input: "{user_input}"

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

            # Use raw_content if it has the answer, otherwise fallback to parsing reasoning just in case
            full_text = f"{reasoning} {raw_content}".strip().lower()
            match = re.search(r'\b(chat|ask|act|plan)\b', full_text)
            if match:
                mode = match.group(1)
                logger.info(f"Neural router classified mode={mode} for input='{user_input}'")
                return mode
    except Exception as e:
        logger.warning(f"Neural router call skipped ({e}). Using rule-based fallback.")

    # General fallback
    if any(kw in input_lower for kw in ["ciao", "salut", "chi sei", "buongiorno", "buonasera", "barzelletta"]):
        fallback = "chat"
    elif any(kw in input_lower for kw in ["lista", "stato", "avvia", "ferma", "riavvia", "get", "status", "container"]):
        fallback = "act"
    elif any(kw in input_lower for kw in ["qual", "cosa", "preferenza", "ricord", "ultima volta", "storico"]):
        fallback = "ask"
    else:
        fallback = "chat"

    logger.info(f"Rule router fallback classified mode={fallback} for input='{user_input}'")
    return fallback

