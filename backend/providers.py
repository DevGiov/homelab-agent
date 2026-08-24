"""Provider abstraction per LLM (Fase 1.1).

Interfaccia comune chat/stream per llama.cpp, OpenAI e Ollama.
Tutti gli adapter restituiscono {"content": str, "reasoning_content": str}
e supportano streaming verso una callback di eventi.
"""
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional

import httpx

import config

logger = logging.getLogger("providers")

StreamCallback = Callable[[Dict[str, str]], None]


class LLMProvider(ABC):
    """Interfaccia base per i provider LLM OpenAI-compatible."""

    name: str = "base"
    default_model: str = ""

    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        reasoning_budget: int = -1,
        stream_callback: Optional[StreamCallback] = None,
    ) -> Dict[str, str]:
        """Esegue una chat completion. Ritorna {'content', 'reasoning_content'}."""
        ...

    @abstractmethod
    def health(self) -> bool:
        """Ping rapido del provider."""
        ...

    @abstractmethod
    def list_models(self) -> List[str]:
        """Lista dei modelli disponibili per questo provider."""
        ...


def _supports_reasoning(model_name: str) -> bool:
    lowered = (model_name or "").lower()
    return any(x in lowered for x in ["qwen", "deepseek", "r1", "o1", "o3", "mistral", "think", "reason"])


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

    def _build_payload(self, messages, model, max_tokens, temperature, reasoning_budget, stream) -> dict:
        effective_model = model or self.default_model
        enable_thinking = (reasoning_budget != 0) and _supports_reasoning(effective_model)
        payload = {
            "model": effective_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if enable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": True}
            if reasoning_budget > 0:
                payload["reasoning_budget_tokens"] = reasoning_budget
        if stream:
            payload["stream"] = True
        return payload

    def chat(self, messages, *, model=None, max_tokens=4096, temperature=0.3,
             reasoning_budget=-1, stream_callback=None) -> Dict[str, str]:
        url = f"{self.base_url}/chat/completions"
        payload = self._build_payload(messages, model, max_tokens, temperature, reasoning_budget, stream=bool(stream_callback))

        max_retries = 2
        for attempt in range(1, max_retries + 1):
            try:
                if stream_callback:
                    with httpx.Client(timeout=self.timeout) as client:
                        with client.stream("POST", url, json=payload) as res:
                            if res.status_code != 200:
                                logger.warning(f"[{self.name}] LLM status {res.status_code}")
                                break
                            content_acc, reasoning_acc = "", ""
                            for line in res.iter_lines():
                                if not line.startswith("data: ") or line == "data: [DONE]":
                                    continue
                                try:
                                    chunk = json.loads(line[6:])
                                    delta = chunk["choices"][0].get("delta", {})
                                    r_part = delta.get("reasoning_content")
                                    if r_part:
                                        reasoning_acc += r_part
                                        stream_callback({"type": "reasoning", "delta": r_part})
                                    c_part = delta.get("content")
                                    if c_part:
                                        content_acc += c_part
                                        stream_callback({"type": "content", "delta": c_part})
                                except Exception as e:
                                    logger.warning(f"[{self.name}] SSE parse error: {e}")
                            return {"content": content_acc.strip(), "reasoning_content": reasoning_acc.strip()}
                else:
                    with httpx.Client(timeout=self.timeout) as client:
                        res = client.post(url, json=payload)
                    if res.status_code == 200:
                        msg_obj = res.json()["choices"][0]["message"]
                        content = msg_obj.get("content") or ""
                        reasoning = msg_obj.get("reasoning_content") or msg_obj.get("thinking") or msg_obj.get("reasoning") or ""
                        if not reasoning:
                            content, extracted = _extract_think_blocks(content)
                            reasoning = extracted
                        return {"content": content.strip(), "reasoning_content": reasoning.strip()}
                    logger.warning(f"[{self.name}] LLM status {res.status_code}: {res.text[:300]}")
                    break
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                logger.warning(f"[{self.name}] LLM attempt {attempt}/{max_retries} failed: {e}")
            except Exception as e:
                logger.warning(f"[{self.name}] LLM call failed unexpectedly: {e}")
                break
        return {"content": "", "reasoning_content": ""}

    def health(self) -> bool:
        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.get(f"{self.base_url}/models")
            return res.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(f"{self.base_url}/models")
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict):
                    if "data" in data and isinstance(data["data"], list):
                        ids = [str(m["id"]) for m in data["data"] if isinstance(m, dict) and "id" in m]
                        if ids:
                            return ids
                    if "models" in data and isinstance(data["models"], list):
                        ids = [str(m.get("id") or m.get("name")) for m in data["models"] if isinstance(m, dict)]
                        if ids:
                            return ids
                elif isinstance(data, list):
                    ids = [str(m.get("id") or m.get("name", m)) for m in data if isinstance(m, (dict, str))]
                    if ids:
                        return ids
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to list models: {e}")
        return [self.default_model] if self.default_model else []


class OllamaProvider(LLMProvider):
    """Adapter per Ollama via API nativa (/api/chat)."""

    def __init__(self, base_url: str, default_model: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.name = "ollama"
        self.timeout = timeout

    def chat(self, messages, *, model=None, max_tokens=4096, temperature=0.3,
             reasoning_budget=-1, stream_callback=None) -> Dict[str, str]:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "stream": bool(stream_callback),
            "options": {"num_predict": max_tokens, "temperature": temperature},
        }
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
        config.LLAMA_CPP_URL, config.DEFAULT_MODEL, name="llamacpp"
    )
    ollama_url = getattr(config, "OLLAMA_URL", "")
    if ollama_url:
        _PROVIDERS["ollama"] = OllamaProvider(
            ollama_url, getattr(config, "OLLAMA_MODEL", config.DEFAULT_MODEL)
        )


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


def list_providers() -> Dict[str, bool]:
    """Stato health di tutti i provider registrati (retrocompatibilità)."""
    return {name: p.health() for name, p in _PROVIDERS.items()}

