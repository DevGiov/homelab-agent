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
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

import httpx

from app.agent.stream_session import current_session_var
from app.core.config import settings
from app.llm import sigv4
from app.llm.costs import TOTAL_SCOPE
from app.llm.model_availability import availability_fields, unavailable_reason
from app.llm.reasoning import Reasoning, resolve
from app.llm.roles import check_role
from app.observability.turns import record_llm_call
from app.security.flows import FlowDenied, Tag, can_flow, provider_destination

logger = logging.getLogger("providers")

StreamCallback = Callable[[Dict[str, str]], None]

# Tentativi di connessione: si ritenta solo se la richiesta non ha raggiunto il server
CONNECT_ATTEMPTS = 2

# Secondi di attesa della richiesta che avvia un caricamento: un modello già pronto risponde subito
LOAD_REQUEST_WAIT = 2.0

# Stati dei processi di llama-swap tradotti nello stato del modello; gli altri valgono `unloaded`
_MODEL_STATUS_BY_STATE = {"ready": "loaded", "starting": "loading"}


class LLMUnavailableError(RuntimeError):
    """Il server LLM non ha completato la richiesta (timeout, errore HTTP, connessione)."""


def _failed(reason: str) -> Dict[str, Any]:
    return {"content": "", "reasoning_content": "", "metrics": {}, "error": reason}


# Motivo distinto da «HTTP 502»: la chat lo traduce nella frase sulla memoria della GPU
GPU_MEMORY_REASON = "gpu-memory"


def server_root(base_url: str) -> str:
    """URL del server senza il suffisso /v1 dell'API OpenAI."""
    return re.sub(r'/v1/?$', '', base_url.rstrip('/'))


def model_status(state: Optional[str]) -> str:
    return _MODEL_STATUS_BY_STATE.get(state or "", "unloaded")


def model_status_changes(line: str, known: Dict[str, str]) -> List[Dict[str, str]]:
    """Cambi di stato contenuti in una riga di /api/events di llama-swap, come {'model', 'status'}.

    Ogni evento modelStatus elenca tutti i modelli: `known` ricorda l'ultimo stato per riportare solo le differenze.
    """
    if not line.startswith("data:"):
        return []
    try:
        event = json.loads(line[5:])
        if event.get("type") != "modelStatus":
            return []
        models = json.loads(event["data"])
    except (ValueError, KeyError, TypeError, AttributeError):
        return []
    changes = []
    for m in models:
        status = model_status(m.get("state"))
        if status != known.get(m["id"], "unloaded"):
            known[m["id"]] = status
            changes.append({"model": m["id"], "status": status})
    return changes


class LLMProvider(ABC):
    """Interfaccia base per i provider LLM OpenAI-compatible."""

    name: str = "base"
    # DEFAULT_MODEL: il modello delle richieste che non ne indicano uno. Vuoto = lo sceglie `effective_model`
    default_model: str = ""
    # False per i provider che non traducono il ragionamento (nessun profilo nei loro modelli): le fasi lo chiedono spento
    reasoning_controls: bool = True

    def effective_model(self, model: Optional[str] = None) -> str:
        """Il modello di una richiesta: quello chiesto, altrimenti DEFAULT_MODEL, altrimenti uno di quelli che il
        server offre (`_server_model`). Stringa vuota se non se ne conosce nessuno: la richiesta parte comunque ed è
        il server a dire perché fallisce."""
        return model or self.default_model or self._server_model()

    def _server_model(self) -> str:
        """Un modello scelto tra quelli del server, per chi non ha configurato DEFAULT_MODEL."""
        return ""

    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        tag: Tag,
        role: str,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: Optional[float] = None,
        reasoning: Optional[Reasoning] = None,
        stream_callback: Optional[StreamCallback] = None,
        json_mode: bool = False,
        json_schema: Optional[Dict[str, Any]] = None,
        fallback: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Esegue una chat completion. Ritorna {'content', 'reasoning_content', 'metrics'}; se la richiesta fallisce
        il contenuto è vuoto e 'error' ne riporta il motivo. Ogni chiamata finisce nelle metriche di osservabilità.

        json_mode chiede al server un output JSON valido (response_format / format=json); json_schema lo vincola a
        uno schema: il server genera solo un oggetto conforme e si ferma quando lo chiude.

        `reasoning` (vedi app.llm.reasoning) dice se e quanto ragionare e con che campionamento; senza, la richiesta
        non ragiona e usa `temperature`.

        `tag` (obbligatorio): la sensibilità del prompt (app.security.flows). Ogni chiamata dichiara cosa sta inviando;
        se il provider non può riceverlo la richiesta non parte (FlowDenied). Con i provider locali capita solo con un
        segreto: le scelte vere si fanno prima, scegliendo il provider.

        `role` (obbligatorio): a quale scopo serve la chiamata (app.llm.roles); un ruolo sconosciuto è un ValueError.
        Finisce nelle metriche.

        `fallback`: il motivo per cui questo provider non è quello che l'utente aveva scelto (`label`, `budget`),
        se la chiamata è un ripiego (app.agent.llm_calls.choose_provider). Finisce nelle metriche.
        """
        check_role(role)
        destination = provider_destination(self.name)
        decision = can_flow(tag, destination)
        if not decision.allowed:
            logger.warning(f"Chiamata a {destination.id} negata: {decision.reason}")
            raise FlowDenied(decision)
        start = time.monotonic()
        model = self.effective_model(model)
        if reasoning is None:
            reasoning = resolve(model, "off", temperature=temperature)
        result = self._chat(messages, model=model, max_tokens=max_tokens, reasoning=reasoning,
                            stream_callback=stream_callback, json_mode=json_mode, json_schema=json_schema)
        metrics = result.get("metrics") or {}
        record_llm_call(
            provider=self.name,
            model=model,
            duration_ms=int((time.monotonic() - start) * 1000),
            prompt_tokens=metrics.get("prompt_tokens", 0),
            cached_tokens=metrics.get("cached_tokens", 0),
            completion_tokens=metrics.get("completion_tokens", 0),
            prompt_ms=metrics.get("prompt_ms"),
            completion_ms=metrics.get("completion_ms"),
            error=result.get("error"),
            label=tag.label.key,
            destination=destination.id,
            role=role,
            fallback=fallback,
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

    def _common_payload(self, messages, model, max_tokens, sampling: Dict[str, Any], json_mode=False, json_schema=None) -> dict:
        """La parte della richiesta che ogni endpoint OpenAI-compatible capisce."""
        payload = {
            "model": model or self.default_model,
            "messages": messages,
            "max_tokens": max_tokens,
            **sampling,
        }
        if json_schema:
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "response", "schema": json_schema}}
        elif json_mode:
            payload["response_format"] = {"type": "json_object"}
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        return payload

    def _build_payload(self, messages, model, max_tokens, reasoning: Reasoning, json_mode=False, json_schema=None) -> dict:
        # Ragionamento e avanzamento del prompt sono estensioni di llama.cpp
        payload = self._common_payload(messages, model, max_tokens, reasoning.sampling.params(), json_mode, json_schema)
        payload.update(reasoning.payload())
        payload["return_progress"] = True
        return payload

    def _chat_url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _request_kwargs(self, payload: dict) -> Dict[str, Any]:
        """Corpo e header della richiesta, ricalcolati a ogni tentativo (un'autenticazione firmata ha un'ora)."""
        return {"json": payload}

    def _http_error_reason(self, status: int, body: str) -> str:
        return f"HTTP {status}"

    def _prepare(self, model: str) -> Optional[str]:
        """Prima della richiesta: il motivo per cui il modello non si può usare, altrimenti lo carica (None = si parte).

        llama-swap risponderebbe con un 404 generico: qui il motivo arriva fino all'utente."""
        reason = unavailable_reason(model)
        if reason:
            return reason
        self.ensure_model_loaded(model)
        return None

    def load_model(self, model: str) -> Dict[str, Any]:
        """Avvia il caricamento su llama-swap: una richiesta a /upstream carica il modello e resta aperta finché è pronto.

        Non serve attenderla: chiusa la connessione il caricamento prosegue. Solo se la GPU sta servendo un altro
        modello la richiesta è ancora in coda e decade con la connessione; la chat successiva si accoda comunque.
        """
        reason = unavailable_reason(model)
        if reason:
            return {"status": "error", "code": 409, "detail": reason}
        url = f"{server_root(self.base_url)}/upstream/{quote(model, safe='')}/health"
        try:
            with httpx.Client(timeout=httpx.Timeout(LOAD_REQUEST_WAIT, connect=5.0)) as client:
                res = client.get(url)
            if res.status_code == 200:
                return {"status": "ok", "detail": "already_loaded"}
            return {"status": "error", "code": res.status_code, "detail": res.text}
        except httpx.ReadTimeout:
            return {"status": "ok", "detail": "loading"}
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
        reason = self._prepare(effective_model)
        if reason:
            return _failed(reason)
        payload = self._build_payload(messages, model, max_tokens, reasoning, json_mode=json_mode,
                                      json_schema=json_schema)

        sess = current_session_var.get()
        if sess and sess.is_stopped():
            return {"content": "", "reasoning_content": "", "metrics": {}}

        start_t = time.time()
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    with client.stream("POST", self._chat_url(), **self._request_kwargs(payload)) as res:
                        if res.status_code != 200:
                            res.read()
                            logger.warning(f"[{self.name}] LLM status {res.status_code}: {res.text[:300]}")
                            return _failed(self._http_error_reason(res.status_code, res.text))
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
        elif raw_usage:
            # Gli altri server (OpenAI, cloud) li riportano nel campo `usage`; `prompt_tokens` li comprende già
            cached = ((raw_usage.get("prompt_tokens_details") or {}).get("cached_tokens"))
            if isinstance(cached, int) and not isinstance(cached, bool) and cached > 0:
                metrics["cached_tokens"] = cached
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

    def _server_model(self) -> str:
        """Il modello già caricato, altrimenti il primo utilizzabile della lista: non richiede un nome nel codice."""
        models = [m for m in self._fetch_models() if m.get("available", True)]
        chosen = (next((m for m in models if m["is_loaded"]), None)
                  or next((m for m in models if m["is_loading"]), None)
                  or (models[0] if models else None))
        return chosen["id"] if chosen else ""

    def _fetch_models(self) -> List[Dict[str, Any]]:
        """Modelli di llama-swap, lista vuota se il server non risponde. Lo stato viene da /running: /models dice
        `loaded` già durante il caricamento."""
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(f"{self.base_url}/models")
                running = client.get(f"{server_root(self.base_url)}/running")
            if res.status_code == 200:
                states = {}
                if running.status_code == 200:
                    states = {r["model"]: r.get("state") for r in running.json().get("running", [])}

                details = []
                for m in res.json().get("data", []):
                    m_id = m.get("id")
                    if not m_id:
                        continue
                    input_mods = (m.get("architecture") or {}).get("input_modalities") or []
                    is_vis = is_vision_model(m_id) or "image" in input_mods
                    status_val = model_status(states.get(m_id))
                    details.append({
                        "id": m_id,
                        "is_vision": is_vis,
                        "input_modalities": input_mods or (["text", "image"] if is_vis else ["text"]),
                        "status": status_val,
                        "is_loaded": (status_val == "loaded"),
                        "is_loading": (status_val == "loading"),
                        **availability_fields(m_id),
                    })
                return details
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to list models with details: {e}")
        return []

    def list_models_with_details(self) -> List[Dict[str, Any]]:
        """Modelli del server; se non risponde, una sola voce con il modello predefinito."""
        details = self._fetch_models()
        if details:
            return details
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


class CloudOpenAIProvider(OpenAICompatProvider):
    """Endpoint OpenAI-compatible di un servizio cloud (primo: AWS Bedrock, `bedrock-runtime`).

    Rispetto al server locale: si autentica con una chiave `Authorization: Bearer` oppure firma la richiesta con
    SigV4 (la chiave, se c'è, ha la precedenza); non manda i campi di llama.cpp (`return_progress`,
    `chat_template_kwargs`, `reasoning_budget_tokens`) né i parametri di campionamento fuori dallo standard OpenAI; non
    carica modelli e non consulta il watchdog; i modelli vengono dalla configurazione, perché l'endpoint non ha
    `GET /models`; il ragionamento resta spento (nessun modello cloud ha ancora un profilo in app.llm.reasoning).
    Gli errori HTTP diventano un risultato fallito con il motivo, senza ritentare: un nuovo tentativo di una richiesta
    arrivata al server potrebbe essere pagato due volte.
    """

    reasoning_controls = False
    # Campionamento accettato da un endpoint OpenAI: top_k, min_p e repeat_penalty sono estensioni di llama.cpp
    _SAMPLING_PARAMS = ("temperature", "top_p", "presence_penalty")
    _HTTP_HINTS = {
        401: "chiave o credenziali non valide",
        403: "accesso negato (permessi o modello non abilitato)",
        429: "limite di richieste o quota raggiunto",
    }

    def __init__(self, base_url: str, models: List[str], name: str, *, api_key: str = "", access_key: str = "",
                 secret_key: str = "", session_token: str = "", region: str = "", service: str = "bedrock",
                 timeout: float = 120.0, clock=None):
        if not models:
            raise ValueError(f"Provider '{name}': nessun modello configurato.")
        super().__init__(base_url, models[0], name=name, timeout=timeout)
        self.models = list(models)
        self.api_key = api_key
        self.access_key = access_key
        self.secret_key = secret_key
        self.session_token = session_token
        self.region = region
        self.service = service
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _build_payload(self, messages, model, max_tokens, reasoning: Reasoning, json_mode=False, json_schema=None) -> dict:
        sampling = {k: v for k, v in reasoning.sampling.params().items() if k in self._SAMPLING_PARAMS}
        return self._common_payload(messages, model, max_tokens, sampling, json_mode, json_schema)

    def _request_kwargs(self, payload: dict) -> Dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        else:
            headers.update(sigv4.sign_request(
                method="POST", url=self._chat_url(), headers=headers, body=body, access_key=self.access_key,
                secret_key=self.secret_key, session_token=self.session_token or None, region=self.region,
                service=self.service, timestamp=self._clock()))
        return {"content": body, "headers": headers}

    def _http_error_reason(self, status: int, body: str) -> str:
        reason = f"HTTP {status}"
        if status in self._HTTP_HINTS:
            reason += f": {self._HTTP_HINTS[status]}"
        elif status >= 500:
            reason += ": errore del servizio"
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        # Bedrock: {"message": ...}; formato OpenAI: {"error": {"message": ...}}
        error = data.get("error") if isinstance(data, dict) else None
        message = error.get("message") if isinstance(error, dict) else (data.get("message") if isinstance(data, dict) else None)
        return f"{reason} ({str(message)[:200]})" if message else reason

    def _prepare(self, model: str) -> Optional[str]:
        return None

    def _server_model(self) -> str:
        return self.models[0]

    def health(self) -> bool:
        # Nessun endpoint da interrogare gratis (`GET /models` risponde 404): configurato vale come raggiungibile
        return True

    def load_model(self, model: str) -> Dict[str, Any]:
        return {"status": "ok", "detail": "already_loaded"}

    def ensure_model_loaded(self, model: Optional[str] = None, timeout: float = 180.0) -> bool:
        return True

    def list_models_with_details(self) -> List[Dict[str, Any]]:
        return [{
            "id": m,
            "is_vision": is_vision_model(m),
            "input_modalities": ["text", "image"] if is_vision_model(m) else ["text"],
            "status": "loaded",
            "is_loaded": True,
            "is_loading": False,
        } for m in self.models]

    def list_models(self) -> List[str]:
        return list(self.models)


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

    def _server_model(self) -> str:
        return next(iter(self.list_models()), "")


# --- Registry dei provider configurabili ---

_PROVIDERS: Dict[str, LLMProvider] = {}
_ACTIVE_PROVIDER_NAME: str = "llamacpp"


def register_provider(provider: LLMProvider) -> None:
    """Aggiunge un provider. `total` è lo scope del tetto di spesa complessivo (app.llm.costs): nessun provider può
    chiamarsi così, o il suo tetto e quello totale sarebbero la stessa riga."""
    if provider.name == TOTAL_SCOPE:
        raise ValueError(f"'{TOTAL_SCOPE}' è riservato al tetto di spesa complessivo: nome di provider non ammesso.")
    _PROVIDERS[provider.name] = provider


def bedrock_provider() -> Optional[CloudOpenAIProvider]:
    """Il provider AWS Bedrock se la configurazione basta: una chiave API oppure le credenziali AWS (chiave di accesso
    e segreto), e la regione, e almeno un modello. Altrimenti None e nulla cambia."""
    has_credentials = bool(settings.bedrock_api_key.strip()
                           or (settings.aws_access_key_id.strip() and settings.aws_secret_access_key.strip()))
    region = settings.aws_region.strip()
    models = settings.bedrock_model_list
    if not (has_credentials and region and models):
        return None
    return CloudOpenAIProvider(
        f"https://bedrock-runtime.{region}.amazonaws.com/openai/v1", models, "bedrock",
        api_key=settings.bedrock_api_key.strip(), access_key=settings.aws_access_key_id.strip(),
        secret_key=settings.aws_secret_access_key.strip(), session_token=settings.aws_session_token.strip(),
        region=region, service="bedrock")


def _register_default_providers():
    register_provider(OpenAICompatProvider(settings.llama_cpp_url, settings.default_model, name="llamacpp"))
    if settings.ollama_url:
        register_provider(OllamaProvider(settings.ollama_url, settings.default_model))
    bedrock = bedrock_provider()
    if bedrock:
        register_provider(bedrock)


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
    return get_provider().effective_model()


# Scelta del modello che significa "quello caricato sul server quando la richiesta parte"
LOADED_MODEL = "loaded"


def loaded_model() -> Optional[str]:
    """Il modello caricato sul provider attivo, o None se nessuno lo è (o il provider non lo dice)."""
    try:
        details = get_provider().list_models_with_details()
    except Exception as e:
        logger.warning(f"Modello caricato non determinabile: {e}")
        return None
    return next((d["id"] for d in details if d.get("is_loaded")), None)


def resolve_model(model: Optional[str]) -> Optional[str]:
    """Modello da usare per una richiesta: `loaded` diventa il modello caricato, oppure None (il default del provider)
    se nessuno è caricato; un nome o None restano invariati."""
    if model == LOADED_MODEL:
        return loaded_model()
    return model


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


def registered_provider_names() -> List[str]:
    return list(_PROVIDERS)


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

