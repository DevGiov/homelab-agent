"""Provider abstraction per LLM (Fase 1.1).

Interfaccia comune chat/stream per llama.cpp, OpenAI e Ollama.
Tutti gli adapter restituiscono {"content": str, "reasoning_content": str}
e supportano streaming verso una callback di eventi.
"""
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

import httpx

from app.agent.stream_session import current_session_var
from app.core.config import settings
from app.llm.reasoning import Reasoning, resolve
from app.observability.turns import record_llm_call

logger = logging.getLogger("providers")

StreamCallback = Callable[[Dict[str, str]], None]

# Tentativi di connessione: si ritenta solo se la richiesta non ha raggiunto il server
CONNECT_ATTEMPTS = 2


class LLMUnavailableError(RuntimeError):
    """Il server LLM non ha completato la richiesta (timeout, errore HTTP, connessione)."""


def _failed(reason: str) -> Dict[str, Any]:
    return {"content": "", "reasoning_content": "", "metrics": {}, "error": reason}


class LLMProvider(ABC):
    """Interfaccia base per i provider LLM OpenAI-compatible."""

    name: str = "base"
    default_model: str = ""

    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: Optional[float] = None,
        reasoning: Optional[Reasoning] = None,
        stream_callback: Optional[StreamCallback] = None,
        json_mode: bool = False,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Esegue una chat completion. Ritorna {'content', 'reasoning_content', 'metrics'}; se la richiesta fallisce
        il contenuto è vuoto e 'error' ne riporta il motivo. Ogni chiamata finisce nelle metriche di osservabilità.

        json_mode chiede al server un output JSON valido (response_format / format=json); json_schema lo vincola a
        uno schema: il server genera solo un oggetto conforme e si ferma quando lo chiude.

        `reasoning` (vedi app.llm.reasoning) dice se e quanto ragionare e con che campionamento; senza, la richiesta
        non ragiona e usa `temperature`.
        """
        start = time.monotonic()
        if reasoning is None:
            reasoning = resolve(model or self.default_model, "off", temperature=temperature)
        result = self._chat(messages, model=model, max_tokens=max_tokens, reasoning=reasoning,
                            stream_callback=stream_callback, json_mode=json_mode, json_schema=json_schema)
        metrics = result.get("metrics") or {}
        record_llm_call(
            provider=self.name,
            model=model or self.default_model,
            duration_ms=int((time.monotonic() - start) * 1000),
            prompt_tokens=metrics.get("prompt_tokens", 0),
            cached_tokens=metrics.get("cached_tokens", 0),
            completion_tokens=metrics.get("completion_tokens", 0),
            prompt_ms=metrics.get("prompt_ms"),
            completion_ms=metrics.get("completion_ms"),
            error=result.get("error"),
        )
        return result

    @abstractmethod
    def _chat(self, messages: List[Dict[str, str]], *, model: Optional[str], max_tokens: int, reasoning: Reasoning,
              stream_callback: Optional[StreamCallback], json_mode: bool,
              json_schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Chiamata al server, senza metriche: la implementa ogni provider."""
        ...

    @abstractmethod
    def health(self) -> bool:
        """Ping rapido del provider."""
        ...

    @abstractmethod
    def list_models(self) -> List[str]:
        """Lista dei modelli disponibili per questo provider."""
        ...

    def list_models_with_details(self) -> List[Dict[str, Any]]:
        """Lista dettagliata dei modelli con capability (es. vision)."""
        return [{"id": m, "is_vision": is_vision_model(m)} for m in self.list_models()]

    def load_model(self, model: str) -> Dict[str, Any]:
        """Carica un modello in memoria (se supportato dal provider)."""
        return {"status": "unsupported"}

    def ensure_model_loaded(self, model: Optional[str] = None, timeout: float = 180.0) -> bool:
        """Assicura che il modello sia caricato in VRAM prima di procedere."""
        return True


_VISION_MODEL_KEYWORDS = (
    # Hosted / universal
    "gpt-4o", "gpt-4.1", "gpt-4.5", "gpt-4-vision", "claude", "gemini",
    # Open / Local
    "qwen3.6", "qwen2.5-vl", "qwen3-vl", "qwen-vl", "vl", "vision", "multimodal",
    "llava", "bakllava", "moondream", "pixtral", "minicpm",
    "internvl", "cogvlm", "gemma-4", "gemma4", "gemma-3", "gemma3",
    "llama-4", "llama4", "phi-4-multimodal"
)
_VISION_VL_RE = re.compile(r'(?<![a-z])vl(?![a-z])|vlm', re.IGNORECASE)


def is_vision_model(model_name: Optional[str]) -> bool:
    """Rileva se il modello specificato supporta input multimodale / immagini."""
    if not model_name:
        return False
    m = model_name.lower()
    if any(kw in m for kw in _VISION_MODEL_KEYWORDS):
        return True
    return bool(_VISION_VL_RE.search(m))


def _extract_think_blocks(content: str) -> tuple[str, str]:
    """Estrae blocchi <think>...</think> dal content (fallback Ollama/llama.cpp)."""
    if not content:
        return "", ""
    match = re.search(r"<think>(.*?)(?:</think>|$)", content, flags=re.DOTALL | re.IGNORECASE)
    if match:
        reasoning = match.group(1).strip()
        content = re.sub(r"<think>.*?(?:</think>|$)", "", content, flags=re.DOTALL | re.IGNORECASE).strip()
        return content, reasoning
    return content, ""


class OpenAICompatProvider(LLMProvider):
    """Adapter generico per endpoint OpenAI-compatible (llama.cpp server, vLLM, LM Studio)."""

    def __init__(self, base_url: str, default_model: str, name: str = "openai-compat", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.name = name
        self.timeout = timeout

    def _build_payload(self, messages, model, max_tokens, reasoning: Reasoning, json_mode=False, json_schema=None) -> dict:
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "max_tokens": max_tokens,
            **reasoning.sampling.params(),
            **reasoning.payload(),
        }
        if json_schema:
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "response", "schema": json_schema}}
        elif json_mode:
            payload["response_format"] = {"type": "json_object"}
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        payload["return_progress"] = True
        return payload

    def load_model(self, model: str) -> Dict[str, Any]:
        """Invia richiesta di caricamento del modello al server llama.cpp."""
        root_url = re.sub(r'/v1/?$', '', self.base_url)
        url = f"{root_url}/models/load"
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(url, json={"model": model})
                if res.status_code == 200:
                    return {"status": "ok", "detail": res.json()}
                elif res.status_code == 400 and "already running" in res.text:
                    return {"status": "ok", "detail": "already_loaded"}
                else:
                    return {"status": "error", "code": res.status_code, "detail": res.text}
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to load model {model}: {e}")
            return {"status": "error", "detail": str(e)}

    def ensure_model_loaded(self, model: Optional[str] = None, timeout: float = 180.0) -> bool:
        """Assicura che il modello sia caricato in VRAM prima di procedere con l'inferenza."""
        effective_model = model or self.default_model
        if not effective_model:
            return True

        try:
            details = self.list_models_with_details()
            for d in details:
                if d.get("id") == effective_model and d.get("is_loaded"):
                    return True
        except Exception:
            pass

        logger.info(f"[{self.name}] Modello '{effective_model}' non caricato in VRAM. Richiesta di load in corso...")
        load_res = self.load_model(effective_model)
        if load_res.get("detail") == "already_loaded":
            return True
        if load_res.get("status") != "ok":
            # Server irraggiungibile, load non supportato o modello sconosciuto: attendere non serve
            logger.warning(f"[{self.name}] Load del modello '{effective_model}' non avviato: {load_res.get('detail')}")
            return False

        start_wait = time.time()
        while time.time() - start_wait < timeout:
            sess = current_session_var.get()
            if sess and sess.is_stopped():
                return False
            time.sleep(1.0)
            try:
                details = self.list_models_with_details()
                for d in details:
                    if d.get("id") == effective_model and d.get("is_loaded"):
                        logger.info(f"[{self.name}] Modello '{effective_model}' caricato in {round(time.time() - start_wait, 1)}s")
                        return True
            except Exception:
                pass

        logger.warning(f"[{self.name}] Timeout attesa caricamento modello '{effective_model}'")
        return False

    def _chat(self, messages, *, model=None, max_tokens=4096, reasoning: Reasoning,
              stream_callback=None, json_mode=False, json_schema=None) -> Dict[str, Any]:
        """Chat completion sempre in streaming, con l'avanzamento dell'elaborazione del prompt.

        llama.cpp invia un chunk per ogni batch del prompt: un prompt lungo non fa scattare il timeout di lettura,
        e se il client si disconnette il server lo vede al batch successivo e libera lo slot.
        """
        effective_model = model or self.default_model
        self.ensure_model_loaded(effective_model)
        payload = self._build_payload(messages, model, max_tokens, reasoning, json_mode=json_mode,
                                      json_schema=json_schema)

        sess = current_session_var.get()
        if sess and sess.is_stopped():
            return {"content": "", "reasoning_content": "", "metrics": {}}

        start_t = time.time()
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    with client.stream("POST", f"{self.base_url}/chat/completions", json=payload) as res:
                        if res.status_code != 200:
                            res.read()
                            logger.warning(f"[{self.name}] LLM status {res.status_code}: {res.text[:300]}")
                            return _failed(f"HTTP {res.status_code}")
                        return self._consume_stream(res, stream_callback, sess, start_t)
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                # La richiesta non è arrivata al server: ritentare non duplica lavoro
                logger.warning(f"[{self.name}] connessione LLM fallita ({attempt}/{CONNECT_ATTEMPTS}): {e}")
            except httpx.TimeoutException as e:
                # Il server ha la richiesta ma non risponde: un retry si accoderebbe dietro quella abbandonata
                logger.warning(f"[{self.name}] timeout LLM, nessun retry: {e!r}")
                return _failed("timeout")
            except Exception as e:
                logger.warning(f"[{self.name}] LLM call failed unexpectedly: {e}")
                return _failed(str(e))
        return _failed("connessione fallita")

    def _consume_stream(self, res, stream_callback: Optional[StreamCallback], sess, start_t: float) -> Dict[str, Any]:
        content_acc, reasoning_acc = "", ""
        raw_usage = None
        timings = None
        first_token_time = None
        for line in res.iter_lines():
            if sess:
                if sess.is_stopped():
                    logger.info(f"[{self.name}] LLM stream interrotto da session stop")
                    break
                sess.pause_event.wait(timeout=300)
                if sess.is_stopped():
                    break
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            try:
                chunk = json.loads(line[6:])
                if chunk.get("usage"):
                    raw_usage = chunk["usage"]
                if chunk.get("timings"):
                    timings = chunk["timings"]
                choices = chunk.get("choices")
                if choices:
                    delta = choices[0].get("delta", {})
                    r_part = delta.get("reasoning_content")
                    if r_part:
                        if first_token_time is None:
                            first_token_time = time.time()
                        reasoning_acc += r_part
                        if stream_callback:
                            stream_callback({"type": "reasoning", "delta": r_part})
                    c_part = delta.get("content")
                    if c_part:
                        if first_token_time is None:
                            first_token_time = time.time()
                        content_acc += c_part
                        if stream_callback:
                            stream_callback({"type": "content", "delta": c_part})
            except Exception as e:
                logger.warning(f"[{self.name}] SSE parse error: {e}")

        if not reasoning_acc:
            content_acc, reasoning_acc = _extract_think_blocks(content_acc)

        duration_s = round(time.time() - start_t, 2)
        if timings and timings.get("predicted_per_second"):
            tok_per_s = round(float(timings["predicted_per_second"]), 1)
            c_tok = timings.get("predicted_n", 0)
            p_tok = timings.get("prompt_n", 0) + timings.get("cache_n", 0)
            tot_tok = p_tok + c_tok
            logger.info(f"[{self.name}] prompt {timings.get('prompt_n', 0)} token elaborati + {timings.get('cache_n', 0)} "
                        f"dalla cache ({round(timings.get('prompt_ms', 0) / 1000, 1)} s), {c_tok} generati in {duration_s} s")
        else:
            if raw_usage:
                p_tok = raw_usage.get("prompt_tokens", 0)
                c_tok = raw_usage.get("completion_tokens", 0)
                tot_tok = raw_usage.get("total_tokens", p_tok + c_tok)
            else:
                c_tok = max(1, len(content_acc + reasoning_acc) // 4) if (content_acc or reasoning_acc) else 0
                p_tok = 0
                tot_tok = c_tok
            gen_duration = (time.time() - first_token_time) if first_token_time else duration_s
            tok_per_s = round(c_tok / max(gen_duration, 0.001), 1)

        metrics = {
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
            "total_tokens": tot_tok,
            "duration_s": duration_s,
            "tok_per_s": tok_per_s,
        }
        if timings:
            # Token del prompt riusati dalla cache e tempo di elaborazione dei soli token nuovi
            metrics["cached_tokens"] = timings.get("cache_n", 0)
            metrics["prompt_ms"] = int(timings.get("prompt_ms", 0))
            metrics["completion_ms"] = int(timings.get("predicted_ms", 0))
        # Con la callback le metriche passano dalla StreamSession, che le accumula e le inoltra ai subscriber
        if stream_callback:
            stream_callback({"type": "metrics", "metrics": metrics})
        elif sess:
            sess.record_metrics(metrics)
        return {"content": content_acc.strip(), "reasoning_content": reasoning_acc.strip(), "metrics": metrics}

    def health(self) -> bool:
        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.get(f"{self.base_url}/models")
            return res.status_code == 200
        except Exception:
            return False

    def list_models_with_details(self) -> List[Dict[str, Any]]:
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(f"{self.base_url}/models")
            if res.status_code == 200:
                data = res.json()
                raw_list = []
                if isinstance(data, dict):
                    if "data" in data and isinstance(data["data"], list):
                        raw_list = data["data"]
                    elif "models" in data and isinstance(data["models"], list):
                        raw_list = data["models"]
                elif isinstance(data, list):
                    raw_list = data

                details = []
                for m in raw_list:
                    if isinstance(m, dict):
                        m_id = str(m.get("id") or m.get("name", ""))
                        if not m_id:
                            continue
                        status_obj = m.get("status") if isinstance(m.get("status"), dict) else {}
                        status_val = str(status_obj.get("value", "unloaded"))
                        status_args = status_obj.get("args", []) if isinstance(status_obj.get("args"), list) else []
                        arch = m.get("architecture") if isinstance(m.get("architecture"), dict) else {}
                        input_mods = arch.get("input_modalities") if isinstance(arch.get("input_modalities"), list) else []
                        has_img_mod = ("image" in input_mods) or ("--mmproj" in status_args)
                        is_vis = is_vision_model(m_id) or has_img_mod
                        details.append({
                            "id": m_id,
                            "is_vision": is_vis,
                            "input_modalities": input_mods or (["text", "image"] if is_vis else ["text"]),
                            "status": status_val,
                            "is_loaded": (status_val == "loaded"),
                            "is_loading": (status_val == "loading"),
                        })
                    elif isinstance(m, str) and m:
                        details.append({
                            "id": m,
                            "is_vision": is_vision_model(m),
                            "input_modalities": ["text", "image"] if is_vision_model(m) else ["text"],
                            "status": "unknown",
                            "is_loaded": False,
                            "is_loading": False,
                        })
                if details:
                    return details
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to list models with details: {e}")

        fallback_id = self.default_model or "default"
        return [{
            "id": fallback_id,
            "is_vision": is_vision_model(fallback_id),
            "input_modalities": ["text", "image"] if is_vision_model(fallback_id) else ["text"],
            "status": "loaded",
            "is_loaded": True,
            "is_loading": False,
        }]

    def list_models(self) -> List[str]:
        return [m["id"] for m in self.list_models_with_details()]


class OllamaProvider(LLMProvider):
    """Adapter per Ollama via API nativa (/api/chat)."""

    def __init__(self, base_url: str, default_model: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.name = "ollama"
        self.timeout = timeout

    def _chat(self, messages, *, model=None, max_tokens=4096, reasoning: Reasoning,
              stream_callback=None, json_mode=False, json_schema=None) -> Dict[str, Any]:
        url = f"{self.base_url}/api/chat"
        # Convert multimodal OpenAI blocks to Ollama format if necessary
        ollama_messages = []
        for msg in messages:
            c = msg.get("content")
            if isinstance(c, list):
                text_parts = []
                img_parts = []
                for b in c:
                    if b.get("type") == "text":
                        text_parts.append(b.get("text", ""))
                    elif b.get("type") == "image_url":
                        u = b.get("image_url", {}).get("url", "")
                        if "," in u and "base64," in u:
                            img_parts.append(u.split("base64,", 1)[1])
                new_m = dict(msg)
                new_m["content"] = "\n".join(text_parts)
                if img_parts:
                    new_m["images"] = img_parts
                ollama_messages.append(new_m)
            else:
                ollama_messages.append(msg)

        payload = {
            "model": model or self.default_model,
            "messages": ollama_messages,
            "stream": bool(stream_callback),
            "options": {"num_predict": max_tokens, **reasoning.sampling.params()},
        }
        if reasoning.send_controls:
            payload["think"] = reasoning.enabled
        if json_schema:
            payload["format"] = json_schema
        elif json_mode:
            payload["format"] = "json"
        try:
            if stream_callback:
                content_acc, reasoning_acc = "", ""
                with httpx.Client(timeout=self.timeout) as client:
                    with client.stream("POST", url, json=payload) as res:
                        for line in res.iter_lines():
                            if not line:
                                continue
                            data = json.loads(line)
                            msg = data.get("message", {})
                            r_part = msg.get("thinking")
                            if r_part:
                                reasoning_acc += r_part
                                stream_callback({"type": "reasoning", "delta": r_part})
                            c_part = msg.get("content")
                            if c_part:
                                content_acc += c_part
                                stream_callback({"type": "content", "delta": c_part})
                            if data.get("done"):
                                break
                return {"content": content_acc.strip(), "reasoning_content": reasoning_acc.strip()}
            else:
                with httpx.Client(timeout=self.timeout) as client:
                    res = client.post(url, json=payload)
                if res.status_code == 200:
                    msg = res.json().get("message", {})
                    content = msg.get("content") or ""
                    reasoning = msg.get("thinking") or ""
                    if not reasoning:
                        content, extracted = _extract_think_blocks(content)
                        reasoning = extracted
                    return {"content": content.strip(), "reasoning_content": reasoning.strip()}
                logger.warning(f"[ollama] status {res.status_code}: {res.text[:300]}")
        except Exception as e:
            logger.warning(f"[ollama] call failed: {e}")
        return {"content": "", "reasoning_content": ""}

    def health(self) -> bool:
        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.get(f"{self.base_url}/api/tags")
            return res.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(f"{self.base_url}/api/tags")
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict) and "models" in data:
                    names = [str(m["name"]) for m in data["models"] if isinstance(m, dict) and "name" in m]
                    if names:
                        return names
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to list models: {e}")
        return [self.default_model] if self.default_model else []


# --- Registry dei provider configurabili ---

_PROVIDERS: Dict[str, LLMProvider] = {}
_ACTIVE_PROVIDER_NAME: str = "llamacpp"


def _register_default_providers():
    _PROVIDERS["llamacpp"] = OpenAICompatProvider(
        settings.llama_cpp_url, settings.default_model, name="llamacpp"
    )
    if settings.ollama_url:
        _PROVIDERS["ollama"] = OllamaProvider(settings.ollama_url, settings.default_model)


_register_default_providers()


def get_provider(name: Optional[str] = None) -> LLMProvider:
    """Restituisce il provider richiesto o quello attivo/default."""
    if name and name in _PROVIDERS:
        return _PROVIDERS[name]
    if _ACTIVE_PROVIDER_NAME in _PROVIDERS:
        return _PROVIDERS[_ACTIVE_PROVIDER_NAME]
    return _PROVIDERS.get("llamacpp") or next(iter(_PROVIDERS.values()))


def get_active_provider_name() -> str:
    return _ACTIVE_PROVIDER_NAME


def get_active_model_name() -> str:
    provider = get_provider()
    return provider.default_model


def set_active_provider(provider_name: str, model_name: Optional[str] = None) -> Dict[str, Any]:
    global _ACTIVE_PROVIDER_NAME
    if provider_name not in _PROVIDERS:
        raise ValueError(f"Provider '{provider_name}' non registrato. Disponibili: {list(_PROVIDERS.keys())}")
    _ACTIVE_PROVIDER_NAME = provider_name
    if model_name:
        _PROVIDERS[provider_name].default_model = model_name
    return {
        "active_provider": _ACTIVE_PROVIDER_NAME,
        "active_model": _PROVIDERS[_ACTIVE_PROVIDER_NAME].default_model
    }


def list_providers_info() -> List[Dict[str, Any]]:
    """Restituisce informazioni su tutti i provider registrati."""
    info = []
    for name, p in _PROVIDERS.items():
        info.append({
            "name": name,
            "is_default": name == _ACTIVE_PROVIDER_NAME,
            "healthy": p.health(),
            "default_model": p.default_model
        })
    return info


def list_provider_models(provider_name: str) -> List[str]:
    """Elenca i modelli disponibili per un dato provider."""
    if provider_name not in _PROVIDERS:
        raise ValueError(f"Provider '{provider_name}' non registrato")
    return _PROVIDERS[provider_name].list_models()


def list_provider_models_with_details(provider_name: str) -> List[Dict[str, Any]]:
    """Elenca i modelli con dettagli (is_vision, input_modalities) per un dato provider."""
    if provider_name not in _PROVIDERS:
        raise ValueError(f"Provider '{provider_name}' non registrato")
    return _PROVIDERS[provider_name].list_models_with_details()


def list_providers() -> Dict[str, bool]:
    """Stato health di tutti i provider registrati (retrocompatibilità)."""
    return {name: p.health() for name, p in _PROVIDERS.items()}


def load_provider_model(provider_name: str, model_name: str) -> Dict[str, Any]:
    """Carica un modello specifico per il dato provider."""
    if provider_name not in _PROVIDERS:
        raise ValueError(f"Provider '{provider_name}' non registrato")
    return _PROVIDERS[provider_name].load_model(model_name)

