"""Ricerca dei modelli dei provider cloud (`POST /v1/providers/{name}/models/discover`) e prova connessione di Bedrock.

Nessuna rete: httpx.Client è sostituito da un MockTransport che risponde come le API di controllo di Bedrock
(ListFoundationModels, ListInferenceProfiles) e come `GET /models` di un servizio OpenAI-compatibile."""
import logging
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.main import api
from app.core.config import settings
from app.llm import costs, provider_config

KEY = "chiave-api-di-test"
AWS_SECRET = "SEGRETO-AWS-DISTINTIVO-91c2"
AWS_ACCESS = "AKIATESTDISTINTIVO"
TOKEN = "TOKEN-DI-SESSIONE-DISTINTIVO"
API_KEY = "bedrock-api-key-DISTINTIVA-5d1"
LEAK = "CORPO-CHE-NON-DEVE-USCIRE"
HOST = "bedrock.eu-west-1.amazonaws.com"
AWS_FIELDS = {"region": "eu-west-1"}
AWS_SECRETS = {"access_key_id": AWS_ACCESS, "secret_access_key": AWS_SECRET}

FOUNDATION = {"modelSummaries": [
    {"modelId": "amazon.nova-lite-v1:0", "modelName": "Nova Lite", "providerName": "Amazon",
     "inputModalities": ["TEXT", "IMAGE"], "outputModalities": ["TEXT"], "inferenceTypesSupported": ["ON_DEMAND"],
     "modelLifecycle": {"status": "ACTIVE"}},
    {"modelId": "meta.llama3-70b-instruct-v1:0", "modelName": "Llama 3 70B", "providerName": "Meta",
     "inputModalities": ["TEXT"], "outputModalities": ["TEXT"], "inferenceTypesSupported": ["ON_DEMAND"],
     "modelLifecycle": {"status": "ACTIVE"}},
    {"modelId": "meta.llama2-13b-chat-v1", "modelName": "Llama 2 13B", "providerName": "Meta",
     "inputModalities": ["TEXT"], "outputModalities": ["TEXT"], "inferenceTypesSupported": ["ON_DEMAND"],
     "modelLifecycle": {"status": "LEGACY"}},
    {"modelId": "cohere.command-r-v1:0:128k", "modelName": "Command R", "providerName": "Cohere",
     "inputModalities": ["TEXT"], "outputModalities": ["TEXT"], "inferenceTypesSupported": ["PROVISIONED"],
     "modelLifecycle": {"status": "ACTIVE"}},
    {"modelId": "anthropic.claude-sonnet-4-v1:0", "modelName": "Claude Sonnet 4", "providerName": "Anthropic",
     "inputModalities": ["TEXT", "IMAGE"], "outputModalities": ["TEXT"], "inferenceTypesSupported": ["INFERENCE_PROFILE"],
     "modelLifecycle": {"status": "ACTIVE"}},
    {"modelId": "amazon.titan-embed-text-v2:0", "modelName": "Titan Embeddings", "providerName": "Amazon",
     "inputModalities": ["TEXT"], "outputModalities": ["EMBEDDING"], "inferenceTypesSupported": ["ON_DEMAND"],
     "modelLifecycle": {"status": "ACTIVE"}},
]}


def _arn(model_id, region=""):
    return {"modelArn": f"arn:aws:bedrock:{region}::foundation-model/{model_id}"}


PROFILES_1 = {"inferenceProfileSummaries": [
    {"inferenceProfileId": "eu.anthropic.claude-sonnet-4-v1:0", "inferenceProfileName": "EU Claude Sonnet 4",
     "status": "ACTIVE", "type": "SYSTEM_DEFINED", "models": [_arn("anthropic.claude-sonnet-4-v1:0", "eu-west-1")]},
    {"inferenceProfileId": "global.anthropic.claude-sonnet-4-v1:0", "inferenceProfileName": "Global Claude Sonnet 4",
     "status": "ACTIVE", "type": "SYSTEM_DEFINED", "models": [_arn("anthropic.claude-sonnet-4-v1:0")]},
    {"inferenceProfileId": "eu.amazon.titan-embed-text-v2:0", "inferenceProfileName": "EU Titan Embeddings",
     "status": "ACTIVE", "type": "SYSTEM_DEFINED", "models": [_arn("amazon.titan-embed-text-v2:0")]},
], "nextToken": "pagina/due+==" }
PROFILES_2 = {"inferenceProfileSummaries": [
    {"inferenceProfileId": "apac.amazon.nova-lite-v1:0", "inferenceProfileName": "APAC Nova Lite", "status": "ACTIVE",
     "type": "SYSTEM_DEFINED", "models": [_arn("amazon.nova-lite-v1:0")]},
    {"inferenceProfileId": "us.meta.llama3-70b-instruct-v1:0", "inferenceProfileName": "US Llama 3 70B",
     "status": "INACTIVE", "type": "SYSTEM_DEFINED", "models": [_arn("meta.llama3-70b-instruct-v1:0")]},
]}


class Aws:
    """Un finto Bedrock: registra le richieste e risponde per percorso."""

    def __init__(self, foundation=FOUNDATION, profiles=(PROFILES_1, PROFILES_2), status=200, body=None, error=None):
        self.requests = []
        self.foundation, self.profiles, self.status, self.body, self.error = foundation, list(profiles), status, body, error

    def __call__(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        if self.status != 200:
            return httpx.Response(self.status, json=self.body if self.body is not None else {"message": "no"})
        if request.url.path == "/foundation-models":
            return httpx.Response(200, json=self.foundation)
        assert request.url.path == "/inference-profiles"
        token = request.url.params.get("nextToken")
        return httpx.Response(200, json=self.profiles[1] if token else self.profiles[0])


def _wipe():
    with sqlite3.connect(settings.mcp_db_path) as conn:
        conn.execute("DELETE FROM provider_configs")
        conn.execute("DELETE FROM provider_settings")


@pytest.fixture(autouse=True)
def clean_config():
    costs.init_costs_db()
    provider_config.init_provider_db()
    _wipe()
    provider_config.load_all()
    yield
    _wipe()
    provider_config.load_all()


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setattr(settings, "api_secret_key", KEY)
    return TestClient(api, headers={"X-API-Key": KEY})


@pytest.fixture
def aws(monkeypatch):
    def install(handler):
        real_client = httpx.Client
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(provider_config.httpx, "Client", lambda **kw: real_client(transport=transport, **kw))
        return handler
    return install


def _create_bedrock(client, secrets=None, models=None, name="nuvola"):
    fields = dict(AWS_FIELDS)
    if models is not None:
        fields["models"] = models
    res = client.post("/v1/providers", json={"name": name, "kind": "bedrock", "fields": fields,
                                             "secrets": secrets or AWS_SECRETS})
    assert res.status_code == 201, res.text


def _discover(client, name="nuvola", **body):
    return client.post(f"/v1/providers/{name}/models/discover", json=body or None)


# --- Bedrock: richieste ------------------------------------------------------------------------------

def test_aws_credentials_sign_both_control_plane_calls(keyed, aws):
    fake = aws(Aws())
    _create_bedrock(keyed, secrets={**AWS_SECRETS, "session_token": TOKEN})
    res = _discover(keyed)
    assert res.status_code == 200 and res.json()["error"] is None
    assert [(r.method, r.url.host, r.url.path) for r in fake.requests] == [
        ("GET", HOST, "/foundation-models"), ("GET", HOST, "/inference-profiles"), ("GET", HOST, "/inference-profiles")]
    first, second = fake.requests[0], fake.requests[1]
    assert first.url.params["byOutputModality"] == "TEXT"
    assert second.url.params["typeEquals"] == "SYSTEM_DEFINED" and second.url.params["maxResults"] == "1000"
    assert fake.requests[2].url.params["nextToken"] == "pagina/due+=="
    for request in fake.requests:
        auth = request.headers["authorization"]
        assert auth.startswith("AWS4-HMAC-SHA256 Credential=" + AWS_ACCESS + "/")
        assert "/eu-west-1/bedrock/aws4_request" in auth and "x-amz-date" in request.headers
        assert request.headers["x-amz-security-token"] == TOKEN
        assert "x-amz-security-token" in auth
    assert AWS_SECRET not in res.text and TOKEN not in res.text and AWS_ACCESS not in res.text


def test_the_api_key_goes_as_bearer_and_wins_over_aws_credentials(keyed, aws):
    fake = aws(Aws())
    _create_bedrock(keyed, secrets={**AWS_SECRETS, "api_key": API_KEY})
    assert _discover(keyed).json()["error"] is None
    for request in fake.requests:
        assert request.headers["authorization"] == f"Bearer {API_KEY}"
        assert "x-amz-date" not in request.headers


# --- Bedrock: filtri e forma -------------------------------------------------------------------------

def test_discovery_keeps_usable_models_and_text_profiles_with_their_scope(keyed, aws):
    aws(Aws())
    _create_bedrock(keyed)
    models = _discover(keyed).json()["models"]
    by_id = {m["id"]: m for m in models}
    assert set(by_id) == {
        "amazon.nova-lite-v1:0", "meta.llama3-70b-instruct-v1:0",   # attivi e on demand
        "eu.anthropic.claude-sonnet-4-v1:0", "global.anthropic.claude-sonnet-4-v1:0", "apac.amazon.nova-lite-v1:0"}
    # Scartati: LEGACY, solo PROVISIONED, solo profilo (come modello), embedding (anche come profilo), profilo inattivo
    assert by_id["amazon.nova-lite-v1:0"] == {
        "id": "amazon.nova-lite-v1:0", "name": "Nova Lite", "vendor": "Amazon", "kind": "model", "scope": "region",
        "vision": True, "configured": False}
    assert by_id["meta.llama3-70b-instruct-v1:0"]["vision"] is False
    assert (by_id["eu.anthropic.claude-sonnet-4-v1:0"]["kind"], by_id["eu.anthropic.claude-sonnet-4-v1:0"]["scope"]) \
        == ("profile", "geo")
    assert by_id["global.anthropic.claude-sonnet-4-v1:0"]["scope"] == "global"
    assert by_id["apac.amazon.nova-lite-v1:0"]["scope"] == "geo" and by_id["apac.amazon.nova-lite-v1:0"]["vision"] is True
    assert by_id["eu.anthropic.claude-sonnet-4-v1:0"]["vendor"] == "Anthropic"
    assert by_id["eu.anthropic.claude-sonnet-4-v1:0"]["vision"] is True


def test_profiles_of_every_page_are_collected(keyed, aws):
    fake = aws(Aws())
    _create_bedrock(keyed)
    ids = {m["id"] for m in _discover(keyed).json()["models"]}
    assert "apac.amazon.nova-lite-v1:0" in ids and "global.anthropic.claude-sonnet-4-v1:0" in ids
    assert len([r for r in fake.requests if r.url.path == "/inference-profiles"]) == 2


def test_configured_models_come_first_then_vendor_and_name(keyed, aws):
    aws(Aws())
    _create_bedrock(keyed, models=["meta.llama3-70b-instruct-v1:0", "x.non-elencato"])
    models = _discover(keyed).json()["models"]
    assert [m["configured"] for m in models] == [True, False, False, False, False]
    assert models[0]["id"] == "meta.llama3-70b-instruct-v1:0"
    rest = [(m["vendor"], m["name"]) for m in models[1:]]
    assert rest == sorted(rest)


def test_discovery_works_with_a_draft_and_without_saved_models(keyed, aws):
    fake = aws(Aws())
    # Un provider Bedrock senza modelli e senza credenziali: la UI lo prova sulla bozza
    res = keyed.post("/v1/providers", json={"name": "bozza", "kind": "bedrock", "fields": {"region": "us-east-1"}})
    assert res.status_code == 201
    saved = _discover(keyed, "bozza")
    assert saved.status_code == 200 and saved.json()["models"] == [] and "credenziali" in saved.json()["error"]
    assert fake.requests == []
    res = _discover(keyed, "bozza", fields={"region": "eu-west-1", "models": ["amazon.nova-lite-v1:0"]},
                    secrets=AWS_SECRETS)
    body = res.json()
    assert res.status_code == 200 and body["error"] is None
    assert body["models"][0]["id"] == "amazon.nova-lite-v1:0" and body["models"][0]["configured"] is True
    assert fake.requests[0].url.host == HOST
    # Nulla è stato salvato
    assert keyed.get("/v1/providers/bozza").json()["fields"]["region"]["value"] == "us-east-1"


# --- Errori ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("status, expected", [
    (403, "bedrock:ListFoundationModels"), (401, "credenziali non valide"), (429, "limite di richieste")])
def test_aws_errors_become_a_short_reason_without_the_body(keyed, aws, caplog, status, expected):
    aws(Aws(status=status, body={"message": "Utente non autorizzato", "internal": LEAK}))
    _create_bedrock(keyed)
    caplog.set_level(logging.DEBUG)
    res = _discover(keyed)
    assert res.status_code == 200
    body = res.json()
    assert body["models"] == [] and expected in body["error"] and f"HTTP {status}" in body["error"]
    assert "Utente non autorizzato" in body["error"]
    assert LEAK not in res.text and LEAK not in caplog.text
    assert AWS_SECRET not in res.text and AWS_SECRET not in caplog.text


def test_a_long_aws_message_is_cut_to_200_characters(keyed, aws):
    aws(Aws(status=403, body={"message": "x" * 500}))
    _create_bedrock(keyed)
    error = _discover(keyed).json()["error"]
    assert "x" * 200 in error and "x" * 201 not in error


def test_an_api_key_that_cannot_list_models_says_so(keyed, aws):
    aws(Aws(status=403, body={"message": LEAK}))
    _create_bedrock(keyed, secrets={"api_key": API_KEY})
    res = _discover(keyed)
    assert res.json() == {"models": [], "error": "la chiave API non permette di elencare i modelli: usa le credenziali "
                                                 "AWS o scrivi i modelli a mano"}
    assert API_KEY not in res.text


def test_timeout_and_connection_failures_are_reasons_not_errors(keyed, aws):
    _create_bedrock(keyed)
    aws(Aws(error=httpx.ReadTimeout("lento")))
    assert _discover(keyed).json() == {"models": [], "error": "timeout"}
    aws(Aws(error=httpx.ConnectError(f"rifiutata {AWS_SECRET}")))
    res = _discover(keyed)
    assert res.json() == {"models": [], "error": "connessione fallita"} and AWS_SECRET not in res.text


def test_a_bad_json_answer_is_a_reason(keyed, aws):
    aws(lambda request: httpx.Response(200, content=b"<html>" + LEAK.encode()))
    _create_bedrock(keyed)
    res = _discover(keyed)
    assert res.json() == {"models": [], "error": "risposta non valida"} and LEAK not in res.text


# --- openai_cloud, altri tipi, autenticazione ---------------------------------------------------------

def test_openai_cloud_lists_models_with_its_bearer_key(keyed, aws):
    seen = []

    def handler(request):
        seen.append((request.url.host, request.url.path, request.headers.get("authorization")))
        return httpx.Response(200, json={"data": [{"id": "gpt-x"}, {"id": "vision-vl-1", "owned_by": "acme"}]})

    aws(handler)
    res = keyed.post("/v1/providers", json={"name": "nuvola", "kind": "openai_cloud", "secrets": {"api_key": API_KEY},
                                            "fields": {"base_url": "https://api.example.com/v1", "models": ["gpt-x"]}})
    assert res.status_code == 201
    body = _discover(keyed).json()
    assert seen == [("api.example.com", "/v1/models", f"Bearer {API_KEY}")]
    assert body["error"] is None
    assert body["models"] == [
        {"id": "gpt-x", "name": "gpt-x", "vendor": None, "kind": "model", "scope": None, "vision": False, "configured": True},
        {"id": "vision-vl-1", "name": "vision-vl-1", "vendor": "acme", "kind": "model", "scope": None, "vision": True,
         "configured": False}]


def test_openai_cloud_error_is_a_reason(keyed, aws):
    aws(lambda request: httpx.Response(401, json={"error": {"message": "chiave"}, "x": LEAK}))
    keyed.post("/v1/providers", json={"name": "nuvola", "kind": "openai_cloud", "secrets": {"api_key": API_KEY},
                                      "fields": {"base_url": "https://api.example.com/v1", "models": ["m"]}})
    res = _discover(keyed)
    assert res.status_code == 200 and "HTTP 401" in res.json()["error"] and LEAK not in res.text


def test_other_kinds_are_422_with_the_usual_error_shape(keyed):
    keyed.post("/v1/providers", json={"name": "casa", "kind": "ollama", "fields": {"base_url": "http://localhost:9101"}})
    res = _discover(keyed, "casa")
    assert res.status_code == 422 and res.json()["detail"]["code"] == "invalid"
    assert _discover(keyed, "llamacpp").status_code == 422
    assert _discover(keyed, "non-esiste").status_code == 404


def test_discovery_requires_the_api_key(monkeypatch):
    monkeypatch.setattr(settings, "api_secret_key", KEY)
    anonymous = TestClient(api)
    assert anonymous.post("/v1/providers/bedrock/models/discover").status_code == 401


# --- La prova connessione di Bedrock -----------------------------------------------------------------

def test_the_bedrock_test_signs_a_list_call_and_counts_configured_models(keyed, aws):
    fake = aws(Aws())
    _create_bedrock(keyed, models=["a", "b", "c"])
    res = keyed.post("/v1/providers/nuvola/test")
    assert res.status_code == 200
    assert {k: v for k, v in res.json().items() if k != "latency_ms"} == {"ok": True, "models_count": 3, "error": None}
    assert [(r.url.host, r.url.path) for r in fake.requests] == [(HOST, "/foundation-models")]
    assert fake.requests[0].headers["authorization"].startswith("AWS4-HMAC-SHA256")


def test_the_bedrock_test_proves_the_credentials(keyed, aws):
    aws(Aws(status=403, body={"message": "negato", "internal": LEAK}))
    _create_bedrock(keyed, models=["a"])
    res = keyed.post("/v1/providers/nuvola/test")
    body = res.json()
    assert body["ok"] is False and "HTTP 403" in body["error"] and body["models_count"] == 1
    assert LEAK not in res.text


def test_an_api_key_refused_on_the_control_plane_falls_back_to_reachability(keyed, aws):
    seen = []

    def handler(request):
        seen.append((request.url.host, request.headers.get("authorization")))
        return httpx.Response(403 if request.url.host == HOST else 404, json={"message": LEAK})

    aws(handler)
    _create_bedrock(keyed, secrets={"api_key": API_KEY}, models=["a"])
    res = keyed.post("/v1/providers/nuvola/test")
    assert res.json()["ok"] is True and res.json()["error"] is None and res.json()["models_count"] == 1
    assert [host for host, _ in seen] == [HOST, "bedrock-runtime.eu-west-1.amazonaws.com"]
    assert seen[0][1] == f"Bearer {API_KEY}"
    assert LEAK not in res.text


def test_the_bedrock_test_reports_a_timeout(keyed, aws):
    aws(Aws(error=httpx.ReadTimeout("lento")))
    _create_bedrock(keyed, models=["a"])
    assert keyed.post("/v1/providers/nuvola/test").json()["error"] == "timeout"
