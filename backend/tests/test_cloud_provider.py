"""Provider cloud (AWS Bedrock): autenticazione, payload, registrazione, flusso con i token in cache, errori HTTP,
ripiego sul modello locale per etichetta e tetto di spesa. Nessuna rete: l'endpoint è un httpx.MockTransport."""
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.agent import llm_calls
from app.agent.stream_session import StreamSession, current_session_var
from app.core.config import Settings, settings
from app.llm import costs, provider_config, providers, sigv4
from app.llm.providers import CloudOpenAIProvider, OpenAICompatProvider, register_provider
from app.llm.reasoning import Reasoning, Sampling, resolve
from app.observability import store
from app.security.flows import PUBLIC_TAG, FlowDenied, Label, Tag, provider_destination

NOW = datetime(2026, 11, 15, 10, 30, 0, tzinfo=timezone.utc)
MESSAGES = [{"role": "user", "content": "ciao"}]
PRIVATE_TAG = Tag(Label.PRIVATE, False, ("memoria",))
INTERNAL_TAG = Tag(Label.INTERNAL, False, ("nota",))
BASE_URL = "https://bedrock-runtime.eu-west-1.amazonaws.com/openai/v1"


@pytest.fixture(autouse=True)
def clean_db():
    Path(settings.metrics_db_path).unlink(missing_ok=True)
    store.init_metrics_db()
    costs.init_costs_db()
    for p in costs.list_prices():
        costs.delete_price(p["provider"], p["model"])
    for scope in costs.list_ceilings():
        costs.delete_ceiling(scope)
    yield


def sse(*chunks):
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, content=body.encode(), headers={"content-type": "text/event-stream"})


def delta(text):
    return {"choices": [{"delta": {"content": text}}]}


def usage(prompt, completion, cached=None):
    u = {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}
    if cached is not None:
        u["prompt_tokens_details"] = {"cached_tokens": cached}
    return {"choices": [], "usage": u}


class Endpoint:
    """Il server finto: registra le richieste e risponde con `handler`."""

    def __init__(self, monkeypatch, handler=None):
        self.requests = []
        self.handler = handler or (lambda request: sse(delta("ok"), usage(10, 2)))
        real_client = httpx.Client
        transport = httpx.MockTransport(self._handle)
        monkeypatch.setattr(providers.httpx, "Client", lambda **kw: real_client(transport=transport, **kw))

    def _handle(self, request):
        self.requests.append(request)
        return self.handler(request)

    @property
    def body(self):
        return json.loads(self.requests[-1].content)


def cloud(**kw):
    args = {"api_key": "", "access_key": "", "secret_key": "", "region": "eu-west-1", "clock": lambda: NOW}
    args.update(kw)
    return CloudOpenAIProvider(BASE_URL, ["model-a", "model-b"], "bedrock", **args)


def rows():
    return store.select("SELECT * FROM llm_calls ORDER BY id")


# --- Autenticazione ----------------------------------------------------------------------------------

def test_the_api_key_goes_as_a_bearer_token_and_nothing_is_signed(monkeypatch):
    endpoint = Endpoint(monkeypatch)
    cloud(api_key="chiave-finta").chat(MESSAGES, tag=PUBLIC_TAG, role="answer")
    [request] = endpoint.requests
    assert str(request.url) == f"{BASE_URL}/chat/completions"
    assert request.headers["authorization"] == "Bearer chiave-finta"
    assert request.headers["content-type"] == "application/json"
    assert "x-amz-date" not in request.headers and "x-amz-content-sha256" not in request.headers


def test_aws_credentials_sign_the_request_with_sigv4_for_the_bedrock_service(monkeypatch):
    endpoint = Endpoint(monkeypatch)
    cloud(access_key="AKIDEXAMPLE", secret_key="segreto-finto").chat(MESSAGES, tag=PUBLIC_TAG, role="answer")
    [request] = endpoint.requests
    auth = request.headers["authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20261115/eu-west-1/bedrock/aws4_request, "
                           "SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date, Signature=")
    assert request.headers["x-amz-date"] == "20261115T103000Z"
    assert request.headers["x-amz-content-sha256"] == hashlib.sha256(request.content).hexdigest()
    assert "x-amz-security-token" not in request.headers
    expected = sigv4.sign_request(
        method="POST", url=f"{BASE_URL}/chat/completions", headers={"content-type": "application/json"},
        body=request.content, access_key="AKIDEXAMPLE", secret_key="segreto-finto", region="eu-west-1",
        service="bedrock", timestamp=NOW)
    assert auth == expected["Authorization"]


def test_a_session_token_is_sent_and_signed(monkeypatch):
    endpoint = Endpoint(monkeypatch)
    cloud(access_key="AKIDEXAMPLE", secret_key="s", session_token="sessione/finta").chat(
        MESSAGES, tag=PUBLIC_TAG, role="answer")
    [request] = endpoint.requests
    assert request.headers["x-amz-security-token"] == "sessione/finta"
    assert "x-amz-security-token" in request.headers["authorization"]


def test_the_api_key_wins_over_aws_credentials(monkeypatch):
    endpoint = Endpoint(monkeypatch)
    cloud(api_key="chiave-finta", access_key="AKIDEXAMPLE", secret_key="s").chat(MESSAGES, tag=PUBLIC_TAG, role="answer")
    [request] = endpoint.requests
    assert request.headers["authorization"] == "Bearer chiave-finta"
    assert "x-amz-date" not in request.headers


def test_the_signature_follows_the_clock_on_every_attempt(monkeypatch):
    times = iter([NOW, NOW.replace(second=5)])
    calls = []

    def handler(request):
        calls.append(request.headers["x-amz-date"])
        if len(calls) == 1:
            raise httpx.ConnectError("rifiutata", request=request)
        return sse(delta("ok"), usage(1, 1))

    Endpoint(monkeypatch, handler)
    result = cloud(access_key="AKIDEXAMPLE", secret_key="s", clock=lambda: next(times)).chat(
        MESSAGES, tag=PUBLIC_TAG, role="answer")
    assert result["content"] == "ok"
    assert calls == ["20261115T103000Z", "20261115T103005Z"]


# --- Payload -----------------------------------------------------------------------------------------

def test_the_payload_has_no_llamacpp_fields_and_keeps_the_openai_sampling(monkeypatch):
    endpoint = Endpoint(monkeypatch)
    thinking = Reasoning(True, 2048, effort="high", sampling=Sampling(
        temperature=0.6, top_p=0.95, top_k=20, min_p=0.0, presence_penalty=0.5, repeat_penalty=1.0))
    cloud(api_key="k").chat(MESSAGES, tag=PUBLIC_TAG, role="answer", model="model-b", max_tokens=300, reasoning=thinking)
    assert endpoint.body == {
        "model": "model-b", "messages": MESSAGES, "max_tokens": 300, "temperature": 0.6, "top_p": 0.95,
        "presence_penalty": 0.5, "stream": True, "stream_options": {"include_usage": True},
    }


def test_the_llamacpp_payload_still_has_its_extras():
    payload = OpenAICompatProvider("http://localhost:8080/v1", "Qwen3.6-35B")._build_payload(
        MESSAGES, "Qwen3.6-35B", 100, resolve("Qwen3.6-35B", "low"))
    assert payload["return_progress"] is True and "chat_template_kwargs" in payload and "reasoning_budget_tokens" in payload
    assert payload["stream_options"] == {"include_usage": True} and payload["top_k"] == 20


def test_structured_output_asks_for_a_json_schema_or_object(monkeypatch):
    endpoint = Endpoint(monkeypatch)
    provider = cloud(api_key="k")
    provider.chat(MESSAGES, tag=PUBLIC_TAG, role="answer", json_schema={"type": "object"})
    assert endpoint.body["response_format"] == {"type": "json_schema", "json_schema": {"name": "response", "schema": {"type": "object"}}}
    provider.chat(MESSAGES, tag=PUBLIC_TAG, role="answer", json_mode=True)
    assert endpoint.body["response_format"] == {"type": "json_object"}


def test_no_model_is_loaded_and_the_watchdog_is_not_consulted(monkeypatch):
    Endpoint(monkeypatch)
    monkeypatch.setattr(providers, "unavailable_reason", lambda m: "watchdog: niente RAM")
    provider = cloud(api_key="k")
    assert provider.chat(MESSAGES, tag=PUBLIC_TAG, role="answer")["content"] == "ok"
    assert provider.ensure_model_loaded("model-a") is True
    assert provider.load_model("model-a") == {"status": "ok", "detail": "already_loaded"}


def test_models_come_from_the_configuration_without_asking_the_server(monkeypatch):
    endpoint = Endpoint(monkeypatch, lambda request: httpx.Response(404))
    provider = cloud(api_key="k")
    assert provider.list_models() == ["model-a", "model-b"]
    assert [m["id"] for m in provider.list_models_with_details()] == ["model-a", "model-b"]
    assert provider.default_model == "model-a" and provider.effective_model() == "model-a"
    assert provider.effective_model("model-b") == "model-b"
    assert provider.health() is True
    assert endpoint.requests == []


def test_a_cloud_model_is_remote_never_loaded_in_vram(monkeypatch):
    Endpoint(monkeypatch)
    details = cloud(api_key="k").list_models_with_details()
    assert {(m["status"], m["is_loaded"], m["is_loading"]) for m in details} == {("remote", False, False)}


def test_a_cloud_provider_without_models_is_refused():
    with pytest.raises(ValueError):
        CloudOpenAIProvider(BASE_URL, [], "bedrock")


# --- Registrazione -----------------------------------------------------------------------------------

def bedrock_provider():
    """Il provider `bedrock` costruito dalla configurazione, o None se non si può costruire."""
    provider_config.load_all()
    return providers._PROVIDERS.get("bedrock")


def configure(monkeypatch, **values):
    base = {"bedrock_api_key": "", "aws_access_key_id": "", "aws_secret_access_key": "", "aws_session_token": "",
            "aws_region": "", "bedrock_models": ""}
    for name, value in {**base, **values}.items():
        monkeypatch.setattr(settings, name, value)


def test_bedrock_with_an_api_key_region_and_models_is_registered(monkeypatch):
    configure(monkeypatch, bedrock_api_key="k", aws_region="us-west-2", bedrock_models=" m-1 , m-2,,")
    provider = bedrock_provider()
    assert provider.name == "bedrock" and provider.models == ["m-1", "m-2"]
    assert provider.base_url == "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1"
    assert (provider.api_key, provider.region, provider.service) == ("k", "us-west-2", "bedrock")


def test_bedrock_with_aws_credentials_is_registered_and_signs(monkeypatch):
    configure(monkeypatch, aws_access_key_id="AK", aws_secret_access_key="SK", aws_session_token="ST",
              aws_region="eu-west-1", bedrock_models="m")
    provider = bedrock_provider()
    assert (provider.api_key, provider.access_key, provider.secret_key, provider.session_token) == ("", "AK", "SK", "ST")


@pytest.mark.parametrize("values", [
    {},                                                                                   # niente
    {"bedrock_api_key": "k", "bedrock_models": "m"},                                       # manca la regione
    {"bedrock_api_key": "k", "aws_region": "r"},                                           # mancano i modelli
    {"bedrock_api_key": "k", "aws_region": "  ", "bedrock_models": "m"},                   # regione vuota
    {"aws_region": "r", "bedrock_models": "m"},                                            # mancano le credenziali
    {"aws_access_key_id": "AK", "aws_region": "r", "bedrock_models": "m"},                 # manca il segreto
    {"aws_secret_access_key": "SK", "aws_region": "r", "bedrock_models": "m"},             # manca la chiave di accesso
    {"bedrock_api_key": "  ", "aws_region": "r", "bedrock_models": "m"},                   # chiave solo spazi
    {"bedrock_api_key": "k", "aws_region": "r", "bedrock_models": " , ,"},                 # modelli solo separatori
])
def test_bedrock_is_absent_when_the_configuration_is_incomplete(monkeypatch, values):
    configure(monkeypatch, **values)
    assert bedrock_provider() is None
    assert "bedrock" not in providers.registered_provider_names()
    assert "llamacpp" in providers.registered_provider_names()
    with pytest.raises(providers.ProviderUnavailableError):
        providers.get_provider("bedrock")


def test_default_registration_adds_bedrock_when_configured(monkeypatch):
    configure(monkeypatch, bedrock_api_key="k", aws_region="eu-west-1", bedrock_models="m")
    provider_config.load_all()
    assert providers.get_provider("bedrock").name == "bedrock"


def test_no_provider_can_be_named_total(monkeypatch):
    monkeypatch.setattr(providers, "_PROVIDERS", {})
    with pytest.raises(ValueError, match="total"):
        register_provider(OpenAICompatProvider("http://localhost:8080/v1", "m", name="total"))
    assert providers.registered_provider_names() == []
    register_provider(OpenAICompatProvider("http://localhost:8080/v1", "m", name="altro"))
    assert providers.registered_provider_names() == ["altro"]


def test_the_cloud_settings_are_off_by_default_and_secrets_are_not_in_the_repr():
    for name in ("bedrock_api_key", "aws_access_key_id", "aws_secret_access_key", "aws_session_token", "aws_region",
                 "bedrock_models"):
        assert Settings.model_fields[name].default == "", name
    assert Settings.model_fields["bedrock_clearance"].default == "public"
    shown = repr(Settings(BEDROCK_API_KEY="chiave-segreta", AWS_SECRET_ACCESS_KEY="segreto-aws"))
    assert "chiave-segreta" not in shown and "segreto-aws" not in shown


@pytest.mark.parametrize("raw, expected", [("public", "public"), ("internal", "internal"), (" Internal ", "internal"),
                                           ("PUBLIC", "public")])
def test_allowed_clearances_are_kept(raw, expected):
    assert Settings(BEDROCK_CLEARANCE=raw).bedrock_clearance == expected


@pytest.mark.parametrize("raw", ["private", "secret", "Private", "tutto", ""])
def test_private_and_unknown_clearances_are_refused_with_a_logged_error(raw, caplog):
    with caplog.at_level(logging.ERROR, logger="config"):
        assert Settings(BEDROCK_CLEARANCE=raw).bedrock_clearance == "public"
    assert "BEDROCK_CLEARANCE" in caplog.text and "public" in caplog.text


def test_the_destination_of_bedrock_reads_its_clearance_and_never_exceeds_internal(monkeypatch):
    configure(monkeypatch, bedrock_api_key="k", aws_region="eu-west-1", bedrock_models="m")
    for value, expected in [("public", Label.PUBLIC), ("internal", Label.INTERNAL), ("private", Label.PUBLIC),
                            ("secret", Label.PUBLIC), ("boh", Label.PUBLIC)]:
        monkeypatch.setattr(settings, "bedrock_clearance", value)
        provider_config.load_all()
        dest = provider_destination("bedrock")
        assert (dest.id, dest.kind, dest.clearance) == ("provider:bedrock", "model", expected), value
    # I provider locali non cambiano
    assert provider_destination("llamacpp").clearance == Label(Label.parse(settings.llama_cpp_clearance))


def test_chat_denies_what_the_destination_cannot_receive_as_the_last_guard(monkeypatch):
    endpoint = Endpoint(monkeypatch)
    monkeypatch.setattr(settings, "bedrock_clearance", "public")
    with pytest.raises(FlowDenied):
        cloud(api_key="k").chat(MESSAGES, tag=INTERNAL_TAG, role="answer")
    assert endpoint.requests == [] and rows() == []


# --- Flusso e token ----------------------------------------------------------------------------------

def test_the_stream_is_parsed_with_usage_and_the_cached_tokens(monkeypatch):
    Endpoint(monkeypatch, lambda r: sse(delta("Ciao "), delta("mondo"), usage(1200, 40, cached=900)))
    seen = []
    result = cloud(api_key="k").chat(MESSAGES, tag=PUBLIC_TAG, role="answer", stream_callback=seen.append)
    assert result["content"] == "Ciao mondo"
    assert [e["delta"] for e in seen if e["type"] == "content"] == ["Ciao ", "mondo"]
    m = result["metrics"]
    assert (m["prompt_tokens"], m["completion_tokens"], m["cached_tokens"]) == (1200, 40, 900)
    [row] = rows()
    assert (row["provider"], row["model"], row["role"], row["prompt_tokens"], row["cached_tokens"],
            row["completion_tokens"]) == ("bedrock", "model-a", "answer", 1200, 900, 40)
    assert row["destination"] == "provider:bedrock" and row["error"] is None and row["fallback"] is None


@pytest.mark.parametrize("final", [usage(50, 5), usage(50, 5, cached=0), {"choices": [], "usage": {
    "prompt_tokens": 50, "completion_tokens": 5, "prompt_tokens_details": None}}])
def test_without_cached_tokens_in_the_usage_none_are_reported(monkeypatch, final):
    Endpoint(monkeypatch, lambda r: sse(delta("x"), final))
    metrics = cloud(api_key="k").chat(MESSAGES, tag=PUBLIC_TAG, role="answer")["metrics"]
    assert metrics["prompt_tokens"] == 50 and "cached_tokens" not in metrics
    assert rows()[0]["cached_tokens"] == 0


def test_cached_tokens_are_read_for_every_openai_compatible_server(monkeypatch):
    Endpoint(monkeypatch, lambda r: sse(delta("x"), usage(100, 5, cached=60)))
    provider = OpenAICompatProvider("http://localhost:8080/v1", "def", name="altro-openai")
    monkeypatch.setattr(provider, "_prepare", lambda m: None)
    assert provider.chat(MESSAGES, tag=PUBLIC_TAG, role="answer")["metrics"]["cached_tokens"] == 60


def test_llamacpp_timings_still_decide_prompt_and_cached_tokens(monkeypatch):
    timings = {"prompt_n": 30, "cache_n": 70, "prompt_ms": 12.5, "predicted_n": 8, "predicted_ms": 80.0,
               "predicted_per_second": 100.0}
    # Anche se l'ultimo chunk porta un `usage` con altri numeri, valgono i timings come prima
    Endpoint(monkeypatch, lambda r: sse(delta("x"), {"choices": [], "timings": timings,
                                                      "usage": {"prompt_tokens": 5, "completion_tokens": 1,
                                                                "prompt_tokens_details": {"cached_tokens": 3}}}))
    provider = OpenAICompatProvider("http://localhost:8080/v1", "def", name="llamacpp")
    monkeypatch.setattr(provider, "_prepare", lambda m: None)
    m = provider.chat(MESSAGES, tag=PUBLIC_TAG, role="answer")["metrics"]
    assert (m["prompt_tokens"], m["completion_tokens"], m["cached_tokens"]) == (100, 8, 70)
    assert (m["prompt_ms"], m["completion_ms"]) == (12, 80)


def test_the_cost_of_a_priced_cloud_model_is_recorded_with_the_cached_price(monkeypatch):
    costs.set_price("bedrock", "model-a", 3, 0.3, 15)
    Endpoint(monkeypatch, lambda r: sse(delta("x"), usage(1000, 200, cached=600)))
    cloud(api_key="k").chat(MESSAGES, tag=PUBLIC_TAG, role="plan")
    [row] = rows()
    assert row["cost_usd"] == pytest.approx((400 * 3 + 600 * 0.3 + 200 * 15) / 1e6)
    assert costs.month_spend()["bedrock"] == pytest.approx(row["cost_usd"])


def test_a_model_without_a_price_costs_zero(monkeypatch):
    Endpoint(monkeypatch, lambda r: sse(delta("x"), usage(1000, 200, cached=600)))
    cloud(api_key="k").chat(MESSAGES, tag=PUBLIC_TAG, role="plan", model="model-b")
    assert rows()[0]["cost_usd"] == 0


# --- Errori HTTP -------------------------------------------------------------------------------------

@pytest.mark.parametrize("status, hint", [(401, "non valide"), (403, "negato"), (429, "limite"), (500, "servizio"),
                                          (503, "servizio")])
def test_http_errors_are_a_failed_result_with_a_reason_and_no_retry(monkeypatch, status, hint):
    endpoint = Endpoint(monkeypatch, lambda r: httpx.Response(status, json={"message": "The security token is bad"}))
    result = cloud(api_key="k").chat(MESSAGES, tag=PUBLIC_TAG, role="answer")
    assert result["content"] == "" and result["error"].startswith(f"HTTP {status}")
    assert hint in result["error"] and "The security token is bad" in result["error"]
    assert len(endpoint.requests) == 1  # nessun retry: potrebbe raddoppiare il conto
    [row] = rows()
    assert row["error"] == result["error"] and row["provider"] == "bedrock"


def test_a_502_with_an_image_is_not_a_gpu_memory_failure_on_the_cloud(monkeypatch):
    # La frase sulla VRAM vale per il server locale: una GPU nostra non c'entra con un 502 di Bedrock
    Endpoint(monkeypatch, lambda r: httpx.Response(502, json={"message": "Bad gateway"}))
    image = {"role": "user", "content": [{"type": "text", "text": "descrivi"},
                                         {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}}]}
    result = cloud(api_key="k").chat([image], tag=PUBLIC_TAG, role="answer")
    assert result["error"].startswith("HTTP 502") and result["error"] != providers.GPU_MEMORY_REASON


def test_the_error_message_of_the_openai_format_is_used_and_a_non_json_body_is_ignored(monkeypatch):
    endpoint = Endpoint(monkeypatch)
    provider = cloud(api_key="k")
    for response, expected in [
        (httpx.Response(400, json={"error": {"message": "modello sconosciuto"}}), "HTTP 400 (modello sconosciuto)"),
        (httpx.Response(502, text="<html>bad gateway</html>"), "HTTP 502: errore del servizio"),
        (httpx.Response(418, text="[1]"), "HTTP 418"),
    ]:
        endpoint.handler = lambda r, response=response: response
        assert provider.chat(MESSAGES, tag=PUBLIC_TAG, role="answer")["error"] == expected


def test_the_error_reason_never_contains_the_credentials(monkeypatch):
    Endpoint(monkeypatch, lambda r: httpx.Response(403, json={"message": "denied"}))
    error = cloud(api_key="chiave-segreta", access_key="AKIDEXAMPLE", secret_key="segreto-aws").chat(
        MESSAGES, tag=PUBLIC_TAG, role="answer")["error"]
    assert "chiave-segreta" not in error and "segreto-aws" not in error


def test_a_connection_error_before_the_request_is_retried_once_then_fails(monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("rifiutata", request=request)

    endpoint = Endpoint(monkeypatch, refuse)
    result = cloud(api_key="k").chat(MESSAGES, tag=PUBLIC_TAG, role="answer")
    assert result["error"] == "connessione fallita" and len(endpoint.requests) == providers.CONNECT_ATTEMPTS


def test_a_timeout_is_not_retried(monkeypatch):
    def slow(request):
        raise httpx.ReadTimeout("lento", request=request)

    endpoint = Endpoint(monkeypatch, slow)
    assert cloud(api_key="k").chat(MESSAGES, tag=PUBLIC_TAG, role="answer")["error"] == "timeout"
    assert len(endpoint.requests) == 1


# --- Scelta del provider per chiamata ----------------------------------------------------------------

class Stub:
    """Sostituisce `_chat` di un provider: registra con che modello e payload è stato chiamato."""

    def __init__(self, provider, text):
        self.calls = []
        self.text = text

        def _chat(messages, *, model, max_tokens, reasoning, **kw):
            self.calls.append({"model": model, "max_tokens": max_tokens, "messages": messages, "reasoning": reasoning})
            return {"content": self.text, "reasoning_content": "", "metrics": {"prompt_tokens": 10, "completion_tokens": 2}}

        provider._chat = _chat


@pytest.fixture
def two_providers(monkeypatch):
    """Provider attivo `bedrock` (finto) e `llamacpp` (finto) nel registro."""
    local = OpenAICompatProvider("http://localhost:8080/v1", "modello-locale", name="llamacpp")
    remote = cloud(api_key="k")
    local.clearance, remote.clearance = Label.PRIVATE, Label.PUBLIC
    monkeypatch.setattr(providers, "_PROVIDERS", {"llamacpp": local, "bedrock": remote})
    # Il provider del turno: bedrock (il predefinito e il ripiego restano llamacpp)
    token = providers.turn_provider_var.set("bedrock")
    yield type("P", (), {"local": local, "remote": remote, "local_calls": Stub(local, "locale"),
                          "remote_calls": Stub(remote, "cloud")})
    providers.turn_provider_var.reset(token)


def with_session():
    sess = StreamSession("thread-fallback")
    token = current_session_var.set(sess)
    return sess, sess.subscribe(), token


def drain(sub):
    events = []
    while not sub.empty():
        events.append(sub.get_nowait())
    return events


def test_a_public_call_goes_to_the_active_cloud_provider(two_providers):
    result = llm_calls.call_llm("ciao", tag=PUBLIC_TAG, role="answer")
    assert result["content"] == "cloud" and two_providers.local_calls.calls == []
    [row] = rows()
    assert (row["provider"], row["model"], row["fallback"]) == ("bedrock", "model-a", None)


def test_data_the_cloud_cannot_receive_goes_to_the_local_model_with_reason_label(two_providers):
    sess, sub, token = with_session()
    try:
        result = llm_calls.call_llm("segreto di casa", tag=PRIVATE_TAG, role="answer", model="model-b")
    finally:
        current_session_var.reset(token)
    assert result["content"] == "locale" and two_providers.remote_calls.calls == []
    # Il modello scelto per il cloud non esiste in locale: vale il predefinito del provider locale
    assert two_providers.local_calls.calls[0]["model"] == "modello-locale"
    [row] = rows()
    assert (row["provider"], row["model"], row["fallback"], row["label"], row["destination"]) == (
        "llamacpp", "modello-locale", "label", "private", "provider:llamacpp")
    assert drain(sub) == [{"type": "provider_fallback", "from": "bedrock", "to": "llamacpp", "reason": "label"}]


def test_internal_data_flows_to_the_cloud_only_with_clearance_internal(two_providers, monkeypatch):
    assert llm_calls.call_llm("x", tag=INTERNAL_TAG, role="answer")["content"] == "locale"
    two_providers.remote.clearance = Label.INTERNAL
    assert llm_calls.call_llm("x", tag=INTERNAL_TAG, role="answer")["content"] == "cloud"
    assert [r["fallback"] for r in rows()] == ["label", None]


def _spend(provider, usd):
    store.insert_llm_call({"turn_key": "t", "provider": provider, "model": "m", "duration_ms": 1, "cost_usd": usd})


def test_a_reached_provider_ceiling_sends_the_call_to_the_local_model_with_reason_budget(two_providers):
    costs.set_ceiling("bedrock", 5)
    _spend("bedrock", 5.0)
    sess, sub, token = with_session()
    try:
        result = llm_calls.call_llm("ciao", tag=PUBLIC_TAG, role="plan")
    finally:
        current_session_var.reset(token)
    assert result["content"] == "locale"
    last = rows()[-1]
    assert (last["provider"], last["fallback"], last["role"]) == ("llamacpp", "budget", "plan")
    assert drain(sub) == [{"type": "provider_fallback", "from": "bedrock", "to": "llamacpp", "reason": "budget"}]


def test_the_total_ceiling_also_counts(two_providers):
    costs.set_ceiling("total", 3)
    _spend("altro-cloud", 3.5)
    assert llm_calls.call_llm("ciao", tag=PUBLIC_TAG, role="answer")["content"] == "locale"
    assert rows()[-1]["fallback"] == "budget"


def test_a_ceiling_not_reached_changes_nothing(two_providers):
    costs.set_ceiling("bedrock", 5)
    _spend("bedrock", 4.99)
    assert llm_calls.call_llm("ciao", tag=PUBLIC_TAG, role="answer")["content"] == "cloud"
    assert rows()[-1]["fallback"] is None


def test_the_label_wins_over_the_ceiling_as_a_reason(two_providers):
    costs.set_ceiling("bedrock", 1)
    _spend("bedrock", 9)
    llm_calls.call_llm("x", tag=PRIVATE_TAG, role="answer")
    assert rows()[-1]["fallback"] == "label"


def test_a_ceiling_that_cannot_be_checked_keeps_the_call_local(two_providers, monkeypatch):
    def broken(provider):
        raise RuntimeError("db rotto")

    monkeypatch.setattr(costs, "ceiling_reached", broken)
    assert llm_calls.call_llm("ciao", tag=PUBLIC_TAG, role="answer")["content"] == "locale"
    assert rows()[-1]["fallback"] == "budget"


def test_with_the_local_provider_active_nothing_changes(two_providers, monkeypatch):
    providers.turn_provider_var.set("llamacpp")
    costs.set_ceiling("llamacpp", 1)
    _spend("llamacpp", 9)
    sess, sub, token = with_session()
    try:
        result = llm_calls.call_llm("x", tag=PRIVATE_TAG, role="answer", model="scelto")
    finally:
        current_session_var.reset(token)
    assert result["content"] == "locale" and two_providers.local_calls.calls[0]["model"] == "scelto"
    assert rows()[-1]["fallback"] is None and drain(sub) == []


def test_a_secret_still_stops_at_the_last_guard_after_the_fallback(two_providers):
    with pytest.raises(FlowDenied):
        llm_calls.call_llm("x", tag=Tag(Label.SECRET, False, ("chiave",)), role="answer")
    assert two_providers.local_calls.calls == [] and two_providers.remote_calls.calls == []


def test_no_event_without_a_session_and_none_for_a_plain_call(two_providers):
    assert llm_calls.call_llm("x", tag=PRIVATE_TAG, role="answer")["content"] == "locale"
    sess, sub, token = with_session()
    try:
        llm_calls.call_llm("x", tag=PUBLIC_TAG, role="answer")
    finally:
        current_session_var.reset(token)
    assert drain(sub) == []


def test_structured_calls_fall_back_too(two_providers):
    from pydantic import BaseModel

    class Answer(BaseModel):
        value: int

    two_providers.local.__dict__.pop("_chat")
    two_providers.local._chat = lambda *a, **k: {"content": '{"value": 3}', "reasoning_content": "", "metrics": {}}
    got = llm_calls.call_llm_structured("x", "sistema", Answer, tag=PRIVATE_TAG, role="select_tool")
    assert got.value == 3 and rows()[-1]["fallback"] == "label" and rows()[-1]["provider"] == "llamacpp"


def test_a_cloud_call_asks_for_no_reasoning_even_when_the_phase_wants_it(two_providers):
    llm_calls.call_llm("ciao", system_prompt="Sei X.", tag=PUBLIC_TAG, role="plan", thinking="high", thinking_budget=4000,
                       max_tokens=500)
    [call] = two_providers.remote_calls.calls
    assert call["reasoning"].enabled is False and call["max_tokens"] == 500
    assert call["messages"][0]["content"] == "Sei X."  # senza l'istruzione sul pensiero nativo


def test_a_local_call_still_reasons_when_the_phase_wants_it(two_providers, monkeypatch):
    providers.turn_provider_var.set("llamacpp")
    two_providers.local.default_model = "Qwen3.6-35B"
    llm_calls.call_llm("ciao", tag=PUBLIC_TAG, role="plan", thinking="high", max_tokens=500)
    [call] = two_providers.local_calls.calls
    assert call["reasoning"].enabled is True and call["max_tokens"] == 500 + call["reasoning"].budget


def test_old_metrics_databases_get_the_fallback_column():
    import sqlite3

    Path(settings.metrics_db_path).unlink()
    conn = sqlite3.connect(settings.metrics_db_path)
    conn.execute("CREATE TABLE llm_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, turn_key TEXT, provider TEXT,"
                 " model TEXT, prompt_tokens INTEGER NOT NULL DEFAULT 0, cached_tokens INTEGER NOT NULL DEFAULT 0,"
                 " completion_tokens INTEGER NOT NULL DEFAULT 0, prompt_ms INTEGER, completion_ms INTEGER,"
                 " duration_ms INTEGER NOT NULL, error TEXT)")
    conn.commit()
    conn.close()
    store.init_metrics_db()
    store.insert_llm_call({"provider": "p", "duration_ms": 1, "fallback": "label"})
    assert rows()[0]["fallback"] == "label"


# --- Le chiamate dirette al provider passano dalla stessa scelta ---------------------------------------

def test_the_router_falls_back_like_every_other_call(two_providers):
    from app.agent import mode_router
    mode_router._ask_router_model("sys", "user", None, PRIVATE_TAG)
    mode_router._ask_router_model("sys", "user", None, PUBLIC_TAG)
    assert len(two_providers.local_calls.calls) == 1 and len(two_providers.remote_calls.calls) == 1
    assert [r["fallback"] for r in rows()] == ["label", None]
    assert [r["role"] for r in rows()] == ["route", "route"]


def test_the_title_falls_back_like_every_other_call(two_providers, monkeypatch):
    from app.memory import thread_store
    monkeypatch.setattr(thread_store, "set_thread_title", lambda *a, **k: None)
    thread_store.generate_and_save_title("t-1", "una richiesta", tag=PRIVATE_TAG)
    assert len(two_providers.local_calls.calls) == 1 and two_providers.remote_calls.calls == []
    assert rows()[-1]["fallback"] == "label" and rows()[-1]["provider"] == "llamacpp"


def test_the_spending_ceiling_stops_the_title_too(two_providers, monkeypatch):
    from app.memory import thread_store
    monkeypatch.setattr(thread_store, "set_thread_title", lambda *a, **k: None)
    monkeypatch.setattr(costs, "ceiling_reached", lambda name: "total")
    thread_store.generate_and_save_title("t-1", "una richiesta", tag=PUBLIC_TAG)
    assert len(two_providers.local_calls.calls) == 1 and rows()[-1]["fallback"] == "budget"


def test_the_image_inspection_falls_back_like_every_other_call(two_providers):
    import io

    from PIL import Image

    from app.registry.vision import VisionRegistry
    from app.security import flows
    Path(settings.uploads_dir).mkdir(parents=True, exist_ok=True)
    image = Path(settings.uploads_dir) / "test-ripiego-rosso.png"
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, format="PNG")
    image.write_bytes(buf.getvalue())
    try:
        res = flows.run_with_call_tag(PRIVATE_TAG, VisionRegistry().execute_tool, "inspect_image",
                                      {"image_path_or_url": image.name, "prompt": "cosa c'è?"})
    finally:
        image.unlink(missing_ok=True)
    assert res.get("success"), res
    assert len(two_providers.local_calls.calls) == 1 and two_providers.remote_calls.calls == []
    assert rows()[-1]["fallback"] == "label" and rows()[-1]["role"] == "vision"
