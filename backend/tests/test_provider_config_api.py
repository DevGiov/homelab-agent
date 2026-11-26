"""Provider gestiti dalla Web UI (docs/providers/PROVIDERS_DESIGN.md, 5.8.2-5.8.6): unione con il `.env` campo per
campo, livello legato all'indirizzo, conferme, credenziali in sola scrittura, ricostruzione a caldo, audit, confini.

Nessuna rete: gli indirizzi sono `localhost` (la connessione è rifiutata subito) o un httpx.MockTransport."""
import ast
import json
import logging
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.agent import llm_calls
from app.api.deps import verify_api_key
from app.api.main import api
from app.core.config import settings
from app.llm import costs, provider_config, providers
from app.security import audit_log, network, secret_box
from app.security.flows import Label, Tag, provider_destination

KEY = "chiave-api-di-test"
SECRET = "sk-VALORE-DISTINTIVO-7f3a9c"  # una credenziale finta, da non ritrovare mai fuori dal provider
HOME = "http://localhost:9101/v1"
OTHER = "http://localhost:9102/v1"
PRIVATE_TAG = Tag(Label.PRIVATE, False, ("memoria",))


def _wipe():
    with sqlite3.connect(settings.mcp_db_path) as conn:
        conn.execute("DELETE FROM provider_configs")
        conn.execute("DELETE FROM provider_settings")


@pytest.fixture(autouse=True)
def clean_config():
    costs.init_costs_db()  # un altro test può aver tolto mcp.db
    provider_config.init_provider_db()
    _wipe()
    provider_config.load_all()
    yield
    _wipe()
    provider_config.load_all()


@pytest.fixture
def client():
    return TestClient(api)


@pytest.fixture
def keyed(monkeypatch):
    """Con API_SECRET_KEY: le credenziali si possono salvare, e le API vogliono la chiave."""
    monkeypatch.setattr(settings, "api_secret_key", KEY)
    return TestClient(api, headers={"X-API-Key": KEY})


def _create(client, name="casa", kind="openai_compat", **body):
    body.setdefault("fields", {"base_url": HOME, "default_model": "uno"})
    res = client.post("/v1/providers", json={"name": name, "kind": kind, **body})
    assert res.status_code == 201, res.text
    return res.json()


def _detail(res):
    return res.json()["detail"]


def _audit_text() -> str:
    return json.dumps(audit_log.get_recent(limit=500), ensure_ascii=False)


# --- Elenco e forma --------------------------------------------------------------------------------

def test_the_env_providers_are_always_listed_with_their_sources(client):
    data = client.get("/v1/providers").json()
    assert [p["name"] for p in data["providers"]] == ["llamacpp", "ollama", "bedrock"]
    assert (data["default_provider"], data["fallback_provider"], data["can_store_secrets"]) == ("llamacpp", "llamacpp", False)
    llamacpp, ollama, bedrock = data["providers"]
    assert llamacpp["fields"]["base_url"] == {"value": settings.llama_cpp_url, "source": "default"}
    assert llamacpp["fields"]["llama_cpp"] == {"value": True, "source": "default"}
    assert llamacpp["clearance"] == {"saved": "private", "effective": "private", "granted_for": settings.llama_cpp_url,
                                     "reset_by_address_change": False}
    assert (llamacpp["is_default"], llamacpp["is_fallback"], llamacpp["origin"]) == (True, True, "env")
    assert (ollama["configured"], ollama["missing"], ollama["clearance"]["effective"]) == (False, ["base_url"], "public")
    assert (bedrock["configured"], bedrock["missing"], bedrock["cloud"]) == (False, ["region", "models", "api_key"], True)
    assert bedrock["secrets"]["api_key"] == {"set": False, "source": None}


def test_a_new_provider_is_born_public_and_enabled(client):
    view = _create(client)
    assert (view["origin"], view["enabled"], view["configured"], view["clearance"]["effective"]) == ("ui", True, True, "public")
    assert view["fields"]["base_url"] == {"value": HOME, "source": "ui"}
    assert view["fields"]["llama_cpp"] == {"value": False, "source": "default"}
    assert providers.get_provider("casa").base_url == HOME
    assert provider_destination("casa").clearance == Label.PUBLIC


def test_an_unknown_provider_counts_as_public():
    assert provider_destination("mai-visto").clearance == Label.PUBLIC


@pytest.mark.parametrize("body, status, code", [
    ({"name": "settings", "kind": "openai_compat"}, 409, "reserved_name"),
    ({"name": "total", "kind": "openai_compat"}, 409, "reserved_name"),
    ({"name": "llamacpp", "kind": "openai_compat"}, 409, "name_taken"),
    ({"name": "Maiuscole", "kind": "openai_compat"}, 422, "invalid"),
    ({"name": "x", "kind": "boh"}, 422, "invalid"),
    ({"name": "x", "kind": "openai_compat", "fields": {"base_url": "ftp://x"}}, 422, "invalid"),
    ({"name": "x", "kind": "openai_compat", "fields": {"colore": "blu"}}, 422, "invalid"),
    # La regione entra nell'indirizzo di Bedrock: niente che possa portarlo altrove
    ({"name": "x", "kind": "bedrock", "fields": {"region": "evil.example.com/x"}}, 422, "invalid"),
])
def test_creation_is_refused_with_a_code(client, body, status, code):
    res = client.post("/v1/providers", json=body)
    assert res.status_code == status and _detail(res)["code"] == code, res.text
    assert isinstance(_detail(res)["message"], str)


def test_the_kind_does_not_change(client):
    _create(client)
    res = client.patch("/v1/providers/casa", json={"kind": "ollama"})
    assert res.status_code == 409 and _detail(res)["code"] == "kind_change"


def test_an_unknown_provider_is_404(client):
    for res in (client.patch("/v1/providers/sparito", json={}), client.delete("/v1/providers/sparito"),
                client.put("/v1/providers/sparito/clearance", json={"level": "public"})):
        assert res.status_code == 404 and _detail(res)["code"] == "not_found"


# --- Il livello segue l'indirizzo ------------------------------------------------------------------

def test_raising_the_clearance_needs_confirm_and_lowering_does_not(client):
    _create(client)
    res = client.put("/v1/providers/casa/clearance", json={"level": "internal"})
    assert res.status_code == 409 and _detail(res)["code"] == "confirm_required"
    assert provider_destination("casa").clearance == Label.PUBLIC
    view = client.put("/v1/providers/casa/clearance", json={"level": "private", "confirm": True}).json()
    assert view["clearance"] == {"saved": "private", "effective": "private", "granted_for": HOME,
                                 "reset_by_address_change": False}
    assert provider_destination("casa").clearance == Label.PRIVATE
    lowered = client.put("/v1/providers/casa/clearance", json={"level": "internal"})
    assert lowered.status_code == 200 and lowered.json()["clearance"]["effective"] == "internal"


def test_a_url_change_makes_the_clearance_public_until_confirmed_for_the_new_address(client):
    _create(client)
    client.put("/v1/providers/casa/clearance", json={"level": "private", "confirm": True})
    moved = client.patch("/v1/providers/casa", json={"fields": {"base_url": OTHER}}).json()
    assert moved["clearance"] == {"saved": "private", "effective": "public", "granted_for": HOME,
                                  "reset_by_address_change": True}
    # Il registro usa già il livello nuovo: i dati privati non vanno al nuovo indirizzo
    assert providers.get_provider("casa").base_url == OTHER
    assert provider_destination("casa").clearance == Label.PUBLIC
    # Tornare all'indirizzo confermato ridà il livello; solo quello
    back = client.patch("/v1/providers/casa", json={"fields": {"base_url": HOME}}).json()
    assert back["clearance"]["effective"] == "private"
    client.patch("/v1/providers/casa", json={"fields": {"base_url": OTHER}})
    client.put("/v1/providers/casa/clearance", json={"level": "private", "confirm": True})
    assert provider_destination("casa").clearance == Label.PRIVATE
    home_again = client.patch("/v1/providers/casa", json={"fields": {"base_url": HOME}}).json()
    assert home_again["clearance"]["granted_for"] == OTHER and home_again["clearance"]["effective"] == "public"


def test_the_env_clearance_is_valid_only_for_the_env_address(client, monkeypatch):
    monkeypatch.setattr(settings, "ollama_url", "http://localhost:11434")
    provider_config.load_all()
    assert provider_destination("ollama").clearance == Label.PRIVATE  # OLLAMA_CLEARANCE per OLLAMA_URL
    view = client.patch("/v1/providers/ollama", json={"fields": {"base_url": "http://localhost:11435"}}).json()
    assert view["clearance"]["effective"] == "public" and view["clearance"]["reset_by_address_change"] is True
    assert provider_destination("ollama").clearance == Label.PUBLIC


def test_the_fallback_cannot_change_address_without_confirm(client):
    res = client.patch("/v1/providers/llamacpp", json={"fields": {"base_url": OTHER}})
    assert res.status_code == 409 and _detail(res)["code"] == "confirm_required"
    assert providers.get_provider("llamacpp").base_url == settings.llama_cpp_url.rstrip("/")
    view = client.patch("/v1/providers/llamacpp", json={"fields": {"base_url": OTHER}, "confirm": True}).json()
    assert view["clearance"] == {"saved": "private", "effective": "private", "granted_for": OTHER,
                                 "reset_by_address_change": False}
    assert "provider_update" in _audit_text() and OTHER in _audit_text()


def test_a_cloud_kind_gets_private_only_from_the_ui_with_confirm(client, monkeypatch):
    monkeypatch.setattr(settings, "bedrock_api_key", "k")
    monkeypatch.setattr(settings, "aws_region", "eu-west-1")
    monkeypatch.setattr(settings, "bedrock_models", "m")
    for raw, expected in (("private", Label.PUBLIC), ("secret", Label.PUBLIC), ("internal", Label.INTERNAL)):
        # Anche se il valore arrivasse senza passare dal validatore di Settings
        monkeypatch.setattr(settings, "bedrock_clearance", raw)
        provider_config.load_all()
        assert provider_destination("bedrock").clearance == expected, raw
    res = client.put("/v1/providers/bedrock/clearance", json={"level": "private"})
    assert res.status_code == 409 and _detail(res)["code"] == "confirm_required"
    view = client.put("/v1/providers/bedrock/clearance", json={"level": "private", "confirm": True}).json()
    assert view["clearance"]["effective"] == "private" and view["clearance"]["granted_for"] == "eu-west-1"
    assert provider_destination("bedrock").clearance == Label.PRIVATE
    # La regione è l'indirizzo di Bedrock: cambiarla riporta a public
    moved = client.patch("/v1/providers/bedrock", json={"fields": {"region": "us-east-1"}}).json()
    assert moved["clearance"]["effective"] == "public"


# --- Campo per campo con il .env -------------------------------------------------------------------

def test_each_field_falls_back_to_the_env_and_null_resets_it(client, monkeypatch):
    monkeypatch.setattr(settings, "ollama_url", "http://localhost:11434")
    monkeypatch.setattr(settings, "default_model", "dal-env")
    provider_config.load_all()
    view = client.patch("/v1/providers/ollama", json={"fields": {"default_model": "dalla-ui"}}).json()
    assert view["fields"]["default_model"] == {"value": "dalla-ui", "source": "ui"}
    assert view["fields"]["base_url"] == {"value": "http://localhost:11434", "source": "env"}
    assert providers.get_provider("ollama").default_model == "dalla-ui"
    view = client.patch("/v1/providers/ollama", json={"fields": {"default_model": None}}).json()
    assert view["fields"]["default_model"] == {"value": "dal-env", "source": "env"}
    assert providers.get_provider("ollama").default_model == "dal-env"


def test_reset_removes_every_ui_change_of_an_env_provider(client, monkeypatch):
    monkeypatch.setattr(settings, "ollama_url", "http://localhost:11434")
    provider_config.load_all()
    client.patch("/v1/providers/ollama", json={"fields": {"base_url": "http://localhost:11435"}, "enabled": False,
                                               "display_name": "Altro"})
    assert "ollama" not in providers.registered_provider_names()
    view = client.post("/v1/providers/ollama/reset").json()
    assert (view["display_name"], view["enabled"], view["fields"]["base_url"]["source"]) == ("Ollama", True, "env")
    assert view["clearance"]["effective"] == "private"
    assert providers.get_provider("ollama").base_url == "http://localhost:11434"
    _create(client)
    res = client.post("/v1/providers/casa/reset")
    assert res.status_code == 409 and _detail(res)["code"] == "not_env_provider"


# --- Eliminare, disattivare, predefinito e ripiego ------------------------------------------------

def test_an_env_provider_cannot_be_deleted(client):
    res = client.delete("/v1/providers/ollama")
    assert res.status_code == 409 and _detail(res)["code"] == "env_provider"


def test_deleting_a_ui_provider_removes_its_prices_and_ceiling(client):
    _create(client)
    costs.set_price("casa", "uno", 1, 0, 2)
    costs.set_ceiling("casa", 5)
    assert client.delete("/v1/providers/casa").json() == {"name": "casa", "deleted": True}
    assert costs.get_price("casa", "uno") is None and "casa" not in costs.list_ceilings()
    assert "casa" not in providers.registered_provider_names()
    assert [p["name"] for p in client.get("/v1/providers").json()["providers"]] == ["llamacpp", "ollama", "bedrock"]


def _private_backup(client):
    _create(client, "riserva", fields={"base_url": OTHER})
    client.put("/v1/providers/riserva/clearance", json={"level": "private", "confirm": True})


def test_the_fallback_cannot_be_disabled_or_deleted(client):
    res = client.patch("/v1/providers/llamacpp", json={"enabled": False})
    assert res.status_code == 409 and _detail(res)["code"] == "fallback_provider"
    assert "llamacpp" in providers.registered_provider_names()
    _private_backup(client)
    assert client.put("/v1/providers/settings", json={"fallback_provider": "riserva"}).json() == {
        "default_provider": "llamacpp", "fallback_provider": "riserva"}
    assert providers.fallback_provider_name() == "riserva"
    for res in (client.delete("/v1/providers/riserva"), client.patch("/v1/providers/riserva", json={"enabled": False}),
                client.put("/v1/providers/riserva/clearance", json={"level": "internal"})):
        assert res.status_code == 409 and _detail(res)["code"] == "fallback_provider", res.text
    assert "riserva" in providers.registered_provider_names()
    # Ora che il ripiego è un altro, llamacpp si può disattivare? No: è ancora il predefinito
    res = client.patch("/v1/providers/llamacpp", json={"enabled": False})
    assert res.status_code == 409 and _detail(res)["code"] == "default_provider"


def test_the_fallback_must_be_private_and_usable(client):
    _create(client)
    res = client.put("/v1/providers/settings", json={"fallback_provider": "casa"})
    assert res.status_code == 409 and _detail(res)["code"] == "fallback_provider"
    res = client.put("/v1/providers/settings", json={"default_provider": "ollama"})
    assert res.status_code == 409 and _detail(res)["code"] == "provider_disabled"
    assert client.put("/v1/providers/settings", json={"fallback_provider": "nessuno"}).status_code == 404


def test_the_fallback_setting_is_where_choose_provider_goes(client):
    _create(client, "nuvola", fields={"base_url": HOME})
    _private_backup(client)
    client.put("/v1/providers/settings", json={"fallback_provider": "riserva"})
    choice = llm_calls.choose_provider(None, PRIVATE_TAG, providers.get_provider("nuvola"))
    assert (choice.provider.name, choice.fallback, choice.origin) == ("riserva", "label", "nuvola")
    # Persiste: un nuovo caricamento (un riavvio) lo ritrova
    providers.set_provider_settings("llamacpp", "llamacpp")
    provider_config.load_all()
    assert providers.fallback_provider_name() == "riserva"


def test_a_disabled_provider_leaves_the_registry_and_the_catalog_and_chat_gets_409(client):
    _create(client)
    assert "casa" in [p["name"] for p in client.get("/v1/models").json()["providers"]]
    client.patch("/v1/providers/casa", json={"enabled": False})
    assert "casa" not in [p["name"] for p in client.get("/v1/models").json()["providers"]]
    res = client.post("/v1/chat", json={"input": "ciao", "provider": "casa"})
    assert res.status_code == 409
    assert _detail(res) == {"code": "provider_disabled", "message": "Il provider 'casa' è disattivato: scegli un altro modello"}


# --- Ricostruzione a caldo -------------------------------------------------------------------------

def test_a_live_rebuild_takes_effect_without_a_restart(client):
    _create(client)
    old = providers.get_provider("casa")
    client.patch("/v1/providers/casa", json={"fields": {"default_model": "due", "base_url": OTHER}})
    new = providers.get_provider("casa")
    assert new is not old and (new.default_model, new.base_url) == ("due", OTHER)
    # Chi aveva già l'oggetto vecchio finisce la sua chiamata con quello
    assert (old.default_model, old.base_url) == ("uno", HOME)
    with providers.use_provider("casa"):
        assert llm_calls.choose_provider(None, Tag()).provider is new


# --- Credenziali -----------------------------------------------------------------------------------

def test_saving_a_secret_without_api_secret_key_is_409_and_stores_nothing(client):
    res = client.post("/v1/providers", json={"name": "nuvola", "kind": "openai_cloud",
                                             "fields": {"base_url": "https://api.example.com/v1", "models": ["m"]},
                                             "secrets": {"api_key": SECRET}})
    assert res.status_code == 409 and _detail(res)["code"] == "no_secret_key"
    assert not provider_config.exists("nuvola")
    _create(client)
    res = client.patch("/v1/providers/casa", json={"secrets": {"api_key": SECRET}, "fields": {"default_model": "due"}})
    assert res.status_code == 409 and _detail(res)["code"] == "no_secret_key"
    with sqlite3.connect(settings.mcp_db_path) as conn:
        row = conn.execute("SELECT fields_json, encrypted_secrets FROM provider_configs WHERE name = 'casa'").fetchone()
    assert json.loads(row[0])["default_model"] == "uno" and row[1] is None
    assert SECRET not in res.text and SECRET not in _audit_text()


def test_a_secret_value_never_leaves_the_provider(keyed, caplog):
    seen_auth = []

    def handler(request):
        if request.url.host == "api.example.com":
            seen_auth.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"data": [{"id": "m"}, {"id": "n"}]})

    real_client = httpx.Client
    transport = httpx.MockTransport(handler)
    caplog.set_level(logging.DEBUG)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(provider_config.httpx, "Client", lambda **kw: real_client(transport=transport, **kw))
        responses = [
            keyed.post("/v1/providers", json={"name": "nuvola", "kind": "openai_cloud", "secrets": {"api_key": SECRET},
                                              "fields": {"base_url": "https://api.example.com/v1", "models": ["m"]}}),
            keyed.patch("/v1/providers/nuvola", json={"secrets": {"api_key": SECRET + "-2"}}),
            keyed.get("/v1/providers"), keyed.get("/v1/providers/nuvola"), keyed.get("/v1/models"),
            keyed.post("/v1/providers/nuvola/test"),
            keyed.post("/v1/providers/nuvola/test", json={"secrets": {"api_key": SECRET + "-3"}}),
            keyed.put("/v1/providers/nuvola/clearance", json={"level": "internal", "confirm": True}),
            keyed.patch("/v1/providers/nuvola", json={"secrets": {"api_key": 5}}),  # 422: il messaggio non ripete
        ]
    assert [r.status_code for r in responses] == [201, 200, 200, 200, 200, 200, 200, 200, 422]
    nuvola = responses[3].json()
    assert nuvola["secrets"] == {"api_key": {"set": True, "source": "ui"}} and nuvola["configured"] is True
    assert responses[5].json() == {"ok": True, "latency_ms": responses[5].json()["latency_ms"], "models_count": 2,
                                   "error": None}
    # La credenziale è stata usata davvero, verso il servizio: lì e solo lì
    assert seen_auth == [f"Bearer {SECRET}-2", f"Bearer {SECRET}-3"]
    assert providers.get_provider("nuvola").api_key == SECRET + "-2"
    for res in responses:
        assert SECRET not in res.text
    assert SECRET not in _audit_text() and "provider_create" in _audit_text()
    assert SECRET not in caplog.text
    with sqlite3.connect(settings.mcp_db_path) as conn:
        raw = json.dumps(conn.execute("SELECT * FROM provider_configs").fetchall())
    assert SECRET not in raw  # cifrata a riposo


def test_null_clears_a_ui_secret_and_the_env_one_shows_through(keyed, monkeypatch):
    monkeypatch.setattr(settings, "bedrock_api_key", "dal-env")
    monkeypatch.setattr(settings, "aws_region", "eu-west-1")
    monkeypatch.setattr(settings, "bedrock_models", "m")
    provider_config.load_all()
    assert keyed.get("/v1/providers/bedrock").json()["secrets"]["api_key"] == {"set": True, "source": "env"}
    view = keyed.patch("/v1/providers/bedrock", json={"secrets": {"api_key": SECRET}}).json()
    assert view["secrets"]["api_key"] == {"set": True, "source": "ui"}
    assert providers.get_provider("bedrock").api_key == SECRET
    view = keyed.patch("/v1/providers/bedrock", json={"secrets": {"api_key": None}}).json()
    assert view["secrets"]["api_key"] == {"set": True, "source": "env"}
    assert providers.get_provider("bedrock").api_key == "dal-env"


def test_an_unreadable_secret_keeps_the_provider_out_until_entered_again(keyed, monkeypatch):
    keyed.post("/v1/providers", json={"name": "nuvola", "kind": "openai_cloud", "secrets": {"api_key": SECRET},
                                      "fields": {"base_url": "https://api.example.com/v1", "models": ["m"]}})
    monkeypatch.setattr(settings, "api_secret_key", "un'altra-chiave")
    provider_config.load_all()
    client = TestClient(api, headers={"X-API-Key": "un'altra-chiave"})
    view = client.get("/v1/providers/nuvola").json()
    assert view["secrets_unreadable"] is True and view["secrets"]["api_key"] == {"set": True, "source": "ui"}
    assert "credenziale illeggibile" in view["error"] and view["healthy"] is None
    assert "nuvola" not in providers.registered_provider_names()
    res = client.post("/v1/chat", json={"input": "ciao", "provider": "nuvola"})
    assert res.status_code == 409 and "credenziale illeggibile" in _detail(res)["message"]
    view = client.patch("/v1/providers/nuvola", json={"secrets": {"api_key": "nuova"}}).json()
    assert view["secrets_unreadable"] is False and providers.get_provider("nuvola").api_key == "nuova"


def test_secret_box_refuses_to_seal_without_a_key(monkeypatch):
    monkeypatch.setattr(settings, "api_secret_key", "")
    with pytest.raises(ValueError):
        secret_box.seal({"api_key": SECRET})


# --- Audit ---------------------------------------------------------------------------------------

def test_every_change_goes_to_the_audit_log_with_the_field_names(client):
    start = max([e["id"] for e in audit_log.get_recent(limit=1)] or [0])
    _create(client)
    client.patch("/v1/providers/casa", json={"fields": {"default_model": "due"}, "display_name": "Casa"})
    client.put("/v1/providers/casa/clearance", json={"level": "internal", "confirm": True})
    _private_backup(client)
    client.put("/v1/providers/settings", json={"fallback_provider": "riserva"})
    client.put("/v1/providers/settings", json={"fallback_provider": "llamacpp"})
    client.delete("/v1/providers/riserva")
    entries = [e for e in audit_log.get_recent(limit=50) if e["registry"] == "providers" and e["id"] > start]
    actions = [e["tool_name"] for e in reversed(entries)]
    assert actions == ["provider_create", "provider_update", "provider_clearance", "provider_create",
                       "provider_clearance", "provider_settings", "provider_settings", "provider_delete"]
    update = json.loads(next(e for e in entries if e["tool_name"] == "provider_update")["arguments_json"])
    assert update["provider"] == "casa" and update["by"] == "user"
    assert update["fields"] == {"default_model": "due"} and update["display_name"] == "Casa"
    clearance = json.loads(next(e for e in entries if e["tool_name"] == "provider_clearance")["arguments_json"])
    # L'ultima: riserva, da public a private con la conferma, per il suo indirizzo
    assert {k: clearance[k] for k in ("provider", "from", "to", "granted_for", "confirm")} == {
        "provider": "riserva", "from": "public", "to": "private", "granted_for": OTHER.lower(), "confirm": True}


# --- Catalogo e prova connessione ----------------------------------------------------------------

def test_the_catalog_lists_usable_providers_with_their_models(client):
    _create(client)
    data = client.get("/v1/models").json()
    names = [p["name"] for p in data["providers"]]
    assert names == ["llamacpp", "casa"]
    casa = data["providers"][1]
    assert {k: casa[k] for k in ("display_name", "kind", "cloud", "clearance", "healthy")} == {
        "display_name": "casa", "kind": "openai_compat", "cloud": False, "clearance": "public", "healthy": False}
    assert casa["models"][0]["id"] == "uno" and "is_vision" in casa["models"][0]
    assert data["default"]["provider"] == "llamacpp"


def test_the_connection_test_reports_only_status_time_and_count(client):
    _create(client)
    result = client.post("/v1/providers/casa/test").json()
    assert set(result) == {"ok", "latency_ms", "models_count", "error"}
    assert result["ok"] is False and result["error"] in ("connessione fallita", "timeout")
    # Con un campo non salvato: la configurazione salvata non cambia
    client.post("/v1/providers/casa/test", json={"fields": {"base_url": OTHER}})
    assert providers.get_provider("casa").base_url == HOME


# --- Percorsi e confini ----------------------------------------------------------------------------

def test_fixed_routes_are_not_shadowed_by_the_provider_routes(client):
    assert set(client.get("/v1/providers/costs").json()) == {"prices", "ceilings", "spend", "reached"}
    assert client.put("/v1/providers/settings", json={}).json() == {"default_provider": "llamacpp",
                                                                    "fallback_provider": "llamacpp"}
    assert client.put("/v1/providers/ceilings/total", json={"monthly_usd": 3}).json() == {"scope": "total", "monthly_usd": 3}
    assert client.put("/v1/providers/ceilings/llamacpp", json={"monthly_usd": 2}).json()["scope"] == "llamacpp"
    assert client.delete("/v1/providers/ceilings/total").json() == {"scope": "total", "deleted": True}
    assert client.delete("/v1/providers/ceilings/llamacpp").json()["deleted"] is True
    assert client.get("/v1/providers/llamacpp/models").json()["provider"] == "llamacpp"
    assert client.get("/v1/providers/llamacpp").json()["name"] == "llamacpp"


PROVIDER_ROUTES = ("/v1/providers", "/v1/models")


def test_every_provider_route_requires_the_api_key(monkeypatch):
    from app.api.routes import providers as provider_routes
    routes = [r for r in provider_routes.router.routes if isinstance(r, APIRoute) and r.path.startswith(PROVIDER_ROUTES)
              and r.path != "/v1/models/events"]
    assert len(routes) >= 17
    for route in routes:
        deps = [d.call for d in route.dependant.dependencies]
        assert verify_api_key in deps, route.path
    monkeypatch.setattr(settings, "api_secret_key", KEY)
    anonymous = TestClient(api)
    for method, path in (("get", "/v1/providers"), ("post", "/v1/providers"), ("patch", "/v1/providers/llamacpp"),
                         ("put", "/v1/providers/llamacpp/clearance"), ("put", "/v1/providers/settings"),
                         ("get", "/v1/models"), ("delete", "/v1/providers/x")):
        assert getattr(anonymous, method)(path).status_code == 401, path


AGENT_PACKAGES = ("agent", "registry", "mcp", "automations", "channels", "integrations", "memory", "calendar", "evals")
ADMIN_CALLS = {"create", "patch", "delete", "reset", "set_clearance", "update_settings", "test_connection",
               "set_provider_settings", "replace_provider", "forget_provider", "register_provider"}


def test_no_agent_tool_can_reach_the_provider_settings():
    """Nessun modulo che l'agente esegue (tool, loop, automazioni, canali) importa la configurazione dei provider o
    chiama le funzioni che la cambiano; e le API stesse non sono un indirizzo che un tool di rete può raggiungere."""
    app_dir = Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for package in AGENT_PACKAGES:
        for path in (app_dir / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) else [])
                    if any(n and "provider_config" in n for n in names):
                        offenders.append(f"{path.name}: import")
                if isinstance(node, ast.Attribute) and node.attr in ADMIN_CALLS and isinstance(node.value, ast.Name) \
                        and node.value.id in ("providers", "provider_config"):
                    offenders.append(f"{path.name}: {node.attr}")
    assert offenders == []
    # Il backend stesso (le sue API su localhost) non è un host che http_get o un altro tool di rete raggiunge
    for url in ("http://localhost:8090/v1/providers", "http://127.0.0.1:8090/v1/providers/settings"):
        with pytest.raises(network.NetworkBlocked):
            network.check_url(url)
    # E nessun tool del catalogo porta il nome di queste API
    from app.security.flows import _TOOL_FLOWS
    assert not [t for t in _TOOL_FLOWS if "provider" in t]
