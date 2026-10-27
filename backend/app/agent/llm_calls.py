"""Chiamate LLM del grafo: streaming verso la sessione SSE corrente e output strutturato validato."""
import contextvars
import json
import logging
import re
from typing import Any, List, Optional

from app.agent.stream_session import current_session_var
from app.core import image_utils
from app.core.config import settings
from app.core.text_utils import strip_thinking
from app.llm.providers import get_provider, is_vision_model

logger = logging.getLogger("graph")

stream_queue = contextvars.ContextVar("stream_queue", default=None)
stream_reasoning_phase_count = contextvars.ContextVar("stream_reasoning_phase_count", default=0)


def call_llm(
    prompt: str,
    system_prompt: str = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    reasoning_budget: int = -1,
    model: Optional[str] = None,
    stream_mode: str = "all",  # "all" | "reasoning_only" | "content_only" | "none"
    reasoning_phase: Optional[str] = None,
    images: Optional[List[str]] = None,
) -> dict:
    messages = []

    # Capability detection based on effective model
    provider = get_provider()
    effective_model = model or getattr(provider, "default_model", "") or settings.default_model
    model_name_lower = effective_model.lower()
    supports_reasoning = any(x in model_name_lower for x in ["qwen", "deepseek", "r1", "o1", "o3", "mistral", "think", "reason"])

    enable_thinking = (reasoning_budget != 0) and supports_reasoning
    if enable_thinking:
        thinking_instruction = (
            "IMPORTANTE: Il sistema di inferenza gestisce automaticamente il tuo processo di ragionamento tramite il meccanismo nativo di thinking. "
            "NON includere processi di pensiero, analisi intermedie, note di self-correction o passi di ragionamento nel testo della tua risposta. "
            "La tua risposta deve contenere SOLO il contenuto finale destinato all'utente."
        )
        if system_prompt:
            system_prompt = f"{system_prompt}\n\n{thinking_instruction}"
        else:
            system_prompt = thinking_instruction

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Multimodal image handling
    if images and len(images) > 0:
        if is_vision_model(effective_model):
            user_content_parts = [{"type": "text", "text": prompt}]
            for img in images:
                try:
                    normalized_img = image_utils.normalize_image_data_url(img)
                except Exception as e:
                    logger.warning(f"Normalizzazione immagine fallita: {e}")
                    normalized_img = img
                user_content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": normalized_img}
                })
            messages.append({"role": "user", "content": user_content_parts})
        else:
            fallback_text = (
                f"{prompt}\n\n"
                f"[NOTA DI SISTEMA: L'utente ha allegato {len(images)} immagine/i, ma il modello attualmente selezionato "
                f"('{effective_model}') non supporta la visione multimodale. Informa gentilmente l'utente di selezionare un "
                f"modello Vision come Qwen3.6-35B per visualizzare ed analizzare le immagini.]"
            )
            messages.append({"role": "user", "content": fallback_text})
    else:
        messages.append({"role": "user", "content": prompt})

    q = stream_queue.get()
    stream_callback = None
    if q and stream_mode != "none":
        phase_header_sent = False

        def _cb(ev: dict):
            nonlocal phase_header_sent
            ev_type = ev.get("type")
            if ev_type == "reasoning":
                if stream_mode in ("all", "reasoning_only"):
                    if reasoning_phase and not phase_header_sent:
                        phase_header_sent = True
                        count = stream_reasoning_phase_count.get()
                        stream_reasoning_phase_count.set(count + 1)
                        header = (
                            f"\n\n---\n\n#### 💡 {reasoning_phase}\n\n"
                            if count > 0
                            else f"#### 🔍 {reasoning_phase}\n\n"
                        )
                        q.put({"type": "reasoning", "delta": header})
                    q.put(ev)
            elif ev_type == "content":
                if stream_mode in ("all", "content_only"):
                    q.put(ev)
            elif ev_type == "metrics":
                if stream_mode != "none":
                    q.put(ev)

        stream_callback = _cb

    sess = current_session_var.get()
    if sess and sess.is_stopped():
        return {"content": "", "reasoning_content": "", "metrics": {}}

    # Fase 1.1: delega al provider abstraction
    return provider.chat(
        messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        reasoning_budget=reasoning_budget,
        stream_callback=stream_callback,
    )

def call_llm_structured(
    prompt: str,
    system_prompt: str,
    schema_cls: Any,
    max_tokens: int = 4096,
    temperature: float = 0.10,
    max_retries: int = 3,
    reasoning_budget: int = -1,
    model: Optional[str] = None,
    reasoning_phase: Optional[str] = "Analisi e Selezione Tool",
    images: Optional[List[str]] = None,
) -> Optional[Any]:
    """
    Chiama l'LLM richiedendo output conforme allo schema Pydantic.
    Effettua parsing + validazione con retry mirato ed iniezione dell'errore.
    Isola lo stream del content JSON per non farlo comparire nella chat principale.
    Include il supporto a immagini multimodali (es. per selezione tool basata su immagini).
    """
    json_schema = schema_cls.model_json_schema()
    schema_prompt = (
        f"{system_prompt}\n\n"
        f"Rispondi ESCLUSIVAMENTE con un'istanza JSON valida conforme alla struttura richiesta da questo schema.\n"
        f"NON restituire la definizione del JSON Schema o metadati come 'type': 'object', ma popola i campi concreti dell'oggetto.\n"
        f"JSON Schema di riferimento:\n"
        f"{json.dumps(json_schema, ensure_ascii=False)}\n\n"
        f"Non aggiungere testo fuori dal JSON."
    )

    # Limita il reasoning budget per la selezione tool per evitare loop di pensiero prolungati
    effective_reasoning_budget = reasoning_budget
    if getattr(schema_cls, "__name__", "") == "ToolSelection":
        if reasoning_budget <= 0 or reasoning_budget > 1024:
            effective_reasoning_budget = 1024

    last_error = None
    effective_max_tokens = max_tokens
    MAX_TOKENS_CAP = 16384
    for attempt in range(1, max_retries + 1):
        current_prompt = prompt
        if last_error:
            current_prompt = (
                f"{prompt}\n\n"
                f"ATTENZIONE: il tentativo precedente ha fallito la validazione con questo errore:\n"
                f"{last_error}\n"
                f"Correggi e rispondi di nuovo SOLO con il JSON valido."
            )

        raw_res = call_llm(
            current_prompt,
            system_prompt=schema_prompt,
            max_tokens=effective_max_tokens,
            temperature=temperature,
            reasoning_budget=effective_reasoning_budget,
            model=model,
            stream_mode="reasoning_only",
            reasoning_phase=reasoning_phase,
            images=images,
        )
        if not raw_res:
            last_error = "Nessuna risposta dal modello LLM"
            continue

        raw = raw_res.get("content", "") if isinstance(raw_res, dict) else ""
        if not raw:
            # Contenuto vuoto = quasi sempre il reasoning che ha esaurito il budget token
            # prima di emettere il JSON (finish_reason=length). Raddoppia max_tokens.
            last_error = f"Risposta testuale vuota (probabile troncamento con max_tokens={effective_max_tokens}): riduci il reasoning ed emetti subito il JSON."
            effective_max_tokens = min(effective_max_tokens * 2, MAX_TOKENS_CAP)
            logger.warning(f"Tentativo {attempt}/{max_retries}: contenuto vuoto, escalation max_tokens a {effective_max_tokens}")
            continue

        clean = strip_thinking(raw.strip())
        clean = strip_thinking(clean)
        clean = re.sub(r'^```(?:json)?', '', clean)
        clean = re.sub(r'```$', '', clean).strip()

        try:
            json_match = re.search(r'\{.*\}', clean, flags=re.DOTALL)
            parsed = json.loads(json_match.group(0)) if json_match else json.loads(clean)
            validated = schema_cls.model_validate(parsed)
            if hasattr(validated, "raw_thinking"):
                validated.raw_thinking = raw_res.get("reasoning_content", "") if isinstance(raw_res, dict) else ""
            logger.info(f"Structured output valido al tentativo {attempt}: {validated.model_dump()}")
            return validated
        except Exception as e:
            last_error = str(e)
            logger.warning(f"Tentativo {attempt}/{max_retries} fallito nella validazione structured output: {e}")

    logger.error(f"Structured output fallito dopo {max_retries} tentativi. Ultimo errore: {last_error}")
    return None


def agent_loop_llm_fns(budget: int, model: Optional[str], state_images: Optional[List[str]]) -> dict:
    """Callable LLM per run_agent_loop: risposta in streaming e selezione tool strutturata."""
    def call_llm_fn(p, system_prompt=None, reasoning_budget=budget, model=model, reasoning_phase=None):
        return call_llm(p, system_prompt=system_prompt, max_tokens=4096, reasoning_budget=reasoning_budget, model=model, stream_mode="all", reasoning_phase=reasoning_phase, images=state_images)

    def call_llm_structured_fn(prompt, system_prompt, schema_cls, max_tokens=4096, temperature=0.0, max_retries=2, reasoning_budget=budget, model=model, reasoning_phase="Analisi e Selezione Tool", images=None):
        return call_llm_structured(prompt, system_prompt, schema_cls, max_tokens, temperature, max_retries, reasoning_budget=reasoning_budget, model=model, reasoning_phase=reasoning_phase, images=images if images is not None else state_images)

    return {"call_llm_fn": call_llm_fn, "call_llm_structured_fn": call_llm_structured_fn}
