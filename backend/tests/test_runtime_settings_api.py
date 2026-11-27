"""Impostazioni modificabili dalla Web UI, fase R1 (docs/settings/RUNTIME_SETTINGS_DESIGN.md, 3-5): canali e Telegram.

Unione con il `.env` campo per campo, ripristino, token in sola scrittura e cifrato, conferme, validazione, riavvio a
caldo del canale, "Prova il bot", autenticazione. Nessuna rete: la Bot API è un httpx.MockTransport (`FakeBotApi`),
che accetta più token (uno per bot) e ne registra ogni chiamata."""
import json
import logging
import sqlite3
import threading
import time

import httpx
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api import agent_runner
from app.api.deps import verify_api_key
from app.api.main import api
from app.channels import hub as hub_module
from app.channels import telegram
from app.channels.base import Capabilities, Channel, InboundMessage
from app.channels.hub import ChannelHub
from app.core import runtime_settings
from app.core.config import settings
from app.security import audit_log
from app.security.flows import Label

KEY = "chiave-api-di-test"
# Token inventati, con la forma di quelli veri: da non ritrovare mai fuori dal trasporto verso la Bot API
TOKEN = "123456789:AAH-invented_token-for-the-tests-only"
TOKEN2 = "987654321:BBH-another_invented-token-for-tests"
ENV_TOKEN = "555555555:CCH-token-written-in-the-env-file"
TOKENS = (TOKEN, TOKEN2, ENV_TOKEN)
LINK = "https://agent.example.test"
CHANNEL_ATTRS = ("web_ui_url", "channel_reply_timeout_seconds", "telegram_bot_token", "telegram_allowed_users",
                 "telegram_clearance")


class FakeBotApi:
    """La Bot API finta: `getUpdates` risponde subito senza update, `getMe` dà il nome del bot di quel token (401 per
    i token in `rejected`). Registra (token, metodo) di ogni chiamata."""

    def __init__(self):
        self.calls = []
        self.rejected = set()
        self.lock = threading.Lock()

    def handler(self, request: httpx.Request) -> httpx.Response:
        _, bot, method = request.url.path.split("/", 2)
        assert bot.startswith("bot"), request.url.path
        token = bot[3:]
        with self.lock:
            self.calls.append((token, method))
        if token in self.rejected:
            return httpx.Response(401, json={"ok": False, "error_code": 401, "description": f"Unauthorized {token}"})
        if method == "getUpdates":
            time.sleep(0.02)
            return httpx.Response(200, json={"ok": True, "result": []})
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"id": 1, "is_bot": True,
                                                                     "username": f"bot_{token.split(':')[0]}"}})
        return httpx.Response(200, json={"ok": True, "result": True})

    def polled_with(self, token: str) -> bool:
        with self.lock:
            return (token, "getUpdates") in self.calls

    def count(self, token: str, method: str) -> int:
        with self.lock:
            return self.calls.count((token, method))


def _wipe():
    with sqlite3.connect(settings.mcp_db_path) as conn:
        conn.execute("DELETE FROM runtime_settings")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """Un `.env` vuoto per i canali (nessun valore dichiarato), un hub già partito e la Bot API finta."""
    runtime_settings.init_db()
    _wipe()
    saved_set = settings.__pydantic_fields_set__
    object.__setattr__(settings, "__pydantic_fields_set__", set(saved_set) - set(CHANNEL_ATTRS))
    for attr in CHANNEL_ATTRS:
        monkeypatch.setattr(settings, attr, type(settings).model_fields[attr].default)
        settings.__pydantic_fields_set__.discard(attr)
    monkeypatch.setattr(settings, "api_secret_key", "")
    fake = FakeBotApi()
    monkeypatch.setattr(telegram, "_bot_transport", lambda: httpx.MockTransport(fake.handler))
    hub = ChannelHub()
    hub.start()
    monkeypatch.setattr(hub_module, "_hub", hub)

    class Env:
        api = fake

        def env_set(self, attr, value):
            monkeypatch.setattr(settings, attr, value)
            settings.__pydantic_fields_set__.add(attr)

        @property
        def channel(self):
            return hub.get("telegram")

    e = Env()
    e.hub = hub
    yield e
    hub.stop()
    _wipe()
    object.__setattr__(settings, "__pydantic_fields_set__", saved_set)


@pytest.fixture
def client():
    return TestClient(api)


@pytest.fixture
def keyed(monkeypatch):
    """Con API_SECRET_KEY: il token si può salvare, e le API vogliono la chiave."""
    monkeypatch.setattr(settings, "api_secret_key", KEY)
    return TestClient(api, headers={"X-API-Key": KEY})


def _detail(res):
    return res.json()["detail"]


def _patch(client, **body):
    return client.patch("/v1/settings/channels", json=body)


def _tg(fields=None, secrets=None):
    part = {}
    if fields is not None:
        part["fields"] = fields
    if secrets is not None:
        part["secrets"] = secrets
    return part


def _start_bot(keyed, token=TOKEN, users=(12,)):
    res = _patch(keyed, telegram=_tg({"allowed_users": list(users)}, {"bot_token": token}), confirm=True)
    assert res.status_code == 200, res.text
    return res.json()


def _audit_entries(start):
    return [e for e in audit_log.get_recent(limit=200) if e["registry"] == "settings" and e["id"] > start]


def _audit_start():
    return max([e["id"] for e in audit_log.get_recent(limit=1)] or [0])


def _db_dump() -> str:
    with sqlite3.connect(settings.mcp_db_path) as conn:
        return json.dumps(conn.execute("SELECT * FROM runtime_settings").fetchall())


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --- Forma e origini -------------------------------------------------------------------------------

def test_the_shape_with_nothing_set_is_all_defaults(client):
    assert client.get("/v1/settings/channels").json() == {
        "web_ui_url": {"value": "", "source": "default"},
        "reply_timeout_seconds": {"value": 300, "source": "default"},
        "telegram": {
            "enabled": {"value": False, "source": "default"},
            "allowed_users": {"value": [], "source": "default"},
            "clearance": {"value": "internal", "source": "default"},
            "secrets": {"bot_token": {"set": False, "source": None}},
            "status": {"running": False, "last_error": None, "ignored": {}},
        },
        "can_store_secrets": False,
    }


def test_the_env_values_are_the_base_with_their_source(client, env):
    env.env_set("web_ui_url", LINK)
    env.env_set("channel_reply_timeout_seconds", 120)
    env.env_set("telegram_bot_token", ENV_TOKEN)
    env.env_set("telegram_allowed_users", " 34, 12 ,12")
    env.env_set("telegram_clearance", "public")
    data = client.get("/v1/settings/channels").json()
    assert data["web_ui_url"] == {"value": LINK, "source": "env"}
    assert data["reply_timeout_seconds"] == {"value": 120, "source": "env"}
    telegram_part = data["telegram"]
    assert telegram_part["enabled"] == {"value": True, "source": "default"}  # vero se c'è il token
    assert telegram_part["allowed_users"] == {"value": [12, 34], "source": "env"}
    assert telegram_part["clearance"] == {"value": "public", "source": "env"}
    assert telegram_part["secrets"] == {"bot_token": {"set": True, "source": "env"}}
    assert ENV_TOKEN not in json.dumps(data)


def test_the_env_clearance_keeps_its_rule(env):
    # Anche se il valore arrivasse senza passare dal validatore di Settings: public o internal, il resto vale public
    for raw, expected in (("private", "public"), ("secret", "public"), (" Internal ", "internal"), ("public", "public")):
        env.env_set("telegram_clearance", raw)
        assert runtime_settings.get("telegram", "clearance") == expected, raw


def test_invalid_env_users_stop_the_channel_and_the_status_says_why(client, env):
    env.env_set("telegram_bot_token", ENV_TOKEN)
    env.env_set("telegram_allowed_users", "12,abc")
    assert telegram.apply_settings() is None and env.channel is None
    part = client.get("/v1/settings/channels").json()["telegram"]
    assert part["allowed_users"] == {"value": [], "source": "env"}
    assert part["status"]["running"] is False and "TELEGRAM_ALLOWED_USERS" in part["status"]["last_error"]


# --- Campo per campo con il .env, null, ripristino -------------------------------------------------

def test_each_field_falls_back_to_the_env_and_null_resets_it(client, env):
    env.env_set("web_ui_url", LINK)
    env.env_set("channel_reply_timeout_seconds", 120)
    view = _patch(client, fields={"web_ui_url": "https://altro.example.test/"}).json()
    assert view["web_ui_url"] == {"value": "https://altro.example.test", "source": "ui"}
    assert view["reply_timeout_seconds"] == {"value": 120, "source": "env"}
    view = _patch(client, fields={"reply_timeout_seconds": 600}).json()
    assert view["reply_timeout_seconds"] == {"value": 600, "source": "ui"}
    assert view["web_ui_url"]["source"] == "ui"  # una modifica non tocca gli altri campi
    view = _patch(client, fields={"web_ui_url": None}).json()
    assert view["web_ui_url"] == {"value": LINK, "source": "env"}
    assert view["reply_timeout_seconds"] == {"value": 600, "source": "ui"}
    # Vuoto dalla UI è un valore (nessun link), diverso da null (torna al .env)
    view = _patch(client, fields={"web_ui_url": ""}).json()
    assert view["web_ui_url"] == {"value": "", "source": "ui"}


def test_the_hub_reads_the_effective_link_and_timeout(client, env, monkeypatch):
    env.env_set("web_ui_url", LINK)
    assert env.hub.thread_link("t1") == f"{LINK}/c/t1"
    _patch(client, fields={"web_ui_url": "https://altro.example.test", "reply_timeout_seconds": 45})
    assert env.hub.thread_link("t1") == "https://altro.example.test/c/t1"
    _patch(client, fields={"web_ui_url": ""})
    assert env.hub.thread_link("t1") is None

    waited = []
    monkeypatch.setattr(hub_module, "_wait", lambda sess, timeout: waited.append(timeout) or ("timeout", None))
    monkeypatch.setattr(agent_runner, "start_turn", lambda *a, **k: object())
    monkeypatch.setattr(agent_runner, "thread_has_active_turn", lambda thread_id: False)
    channel = RecordingChannel("fake")
    env.hub.register(channel)
    env.hub.handle_inbound(InboundMessage("fake", "c1", "u1", "ciao"))
    assert waited == [45]
    assert channel.texts() == ["La risposta richiede più tempo: la troverai nell'app. (nessun link configurato)"]


def test_reset_removes_every_ui_value_of_the_section_and_its_parts(keyed, env):
    env.env_set("web_ui_url", LINK)
    env.env_set("telegram_clearance", "public")
    _start_bot(keyed)
    _patch(keyed, fields={"web_ui_url": "https://altro.example.test", "reply_timeout_seconds": 60},
           telegram=_tg({"clearance": "internal"}), confirm=True)
    assert env.channel.running
    start = _audit_start()
    view = keyed.post("/v1/settings/channels/reset").json()
    assert view["web_ui_url"] == {"value": LINK, "source": "env"}
    assert view["reply_timeout_seconds"] == {"value": 300, "source": "default"}
    assert view["telegram"]["clearance"] == {"value": "public", "source": "env"}
    assert view["telegram"]["allowed_users"] == {"value": [], "source": "default"}
    assert view["telegram"]["secrets"]["bot_token"] == {"set": False, "source": None}
    assert _db_dump() == "[]"
    # Il canale segue: senza token (il .env non ne ha) si ferma
    assert env.channel is None and view["telegram"]["status"]["running"] is False
    [entry] = _audit_entries(start)
    assert entry["tool_name"] == "settings_reset"
    assert json.loads(entry["arguments_json"]) == {"section": "channels", "by": "user", "parts": ["telegram"]}


# --- Credenziali -----------------------------------------------------------------------------------

def test_saving_the_token_without_api_secret_key_is_409_and_saves_nothing(client):
    res = _patch(client, fields={"web_ui_url": LINK}, telegram=_tg({"allowed_users": [12]}, {"bot_token": TOKEN}),
                 confirm=True)
    assert res.status_code == 409 and _detail(res)["code"] == "no_secret_key"
    assert TOKEN not in res.text
    assert _db_dump() == "[]"  # nemmeno i campi della stessa richiesta
    assert client.get("/v1/settings/channels").json()["web_ui_url"]["source"] == "default"
    # Senza credenziali, i campi si salvano anche senza chiave
    assert _patch(client, fields={"web_ui_url": LINK}).status_code == 200


def test_the_token_never_leaves_the_transport(keyed, env, caplog):
    caplog.set_level(logging.DEBUG)
    start = _audit_start()
    responses = [
        _patch(keyed, telegram=_tg({"allowed_users": [12]}, {"bot_token": TOKEN}), confirm=True),
        keyed.get("/v1/settings/channels"),
        keyed.post("/v1/settings/channels/telegram/test"),
        keyed.post("/v1/settings/channels/telegram/test", json={"secrets": {"bot_token": TOKEN2}}),
        _patch(keyed, telegram=_tg(secrets={"bot_token": TOKEN2})),
        _patch(keyed, telegram=_tg(secrets={"bot_token": TOKEN + "/../x"})),  # 422: il messaggio non lo ripete
        _patch(keyed, telegram=_tg(secrets={"bot_token": 5})),
        keyed.post("/v1/settings/channels/reset"),
    ]
    assert [r.status_code for r in responses] == [200, 200, 200, 200, 200, 422, 422, 200]
    assert responses[1].json()["telegram"]["secrets"] == {"bot_token": {"set": True, "source": "ui"}}
    # Il token è stato usato davvero, verso la Bot API: lì e solo lì
    assert env.api.polled_with(TOKEN) and env.api.count(TOKEN2, "getMe") == 1
    text = "".join(r.text for r in responses) + json.dumps(audit_log.get_recent(limit=200)) + caplog.text
    for token in (TOKEN, TOKEN2):
        assert token not in text and token.split(":")[1] not in text
    assert len(_audit_entries(start)) == 3  # due salvataggi e il ripristino


def test_the_token_is_sealed_at_rest(keyed, env):
    _start_bot(keyed)
    raw = _db_dump()
    assert TOKEN not in raw and TOKEN.split(":")[1] not in raw and "__secrets__" in raw
    assert runtime_settings.get("telegram", "bot_token") == TOKEN


def test_null_clears_the_ui_token_and_the_env_one_shows_through(keyed, env):
    env.env_set("telegram_bot_token", ENV_TOKEN)
    env.env_set("telegram_allowed_users", "12")
    view = _patch(keyed, telegram=_tg(secrets={"bot_token": TOKEN})).json()
    assert view["telegram"]["secrets"]["bot_token"] == {"set": True, "source": "ui"}
    assert env.channel._token == TOKEN
    view = _patch(keyed, telegram=_tg(secrets={"bot_token": None})).json()
    assert view["telegram"]["secrets"]["bot_token"] == {"set": True, "source": "env"}
    assert env.channel._token == ENV_TOKEN and "__secrets__" not in _db_dump()


def test_an_unreadable_token_keeps_the_channel_off_until_entered_again(keyed, env, monkeypatch):
    _start_bot(keyed)
    monkeypatch.setattr(settings, "api_secret_key", "un'altra-chiave")
    other = TestClient(api, headers={"X-API-Key": "un'altra-chiave"})
    telegram.apply_settings()
    assert env.channel is None
    part = other.get("/v1/settings/channels").json()["telegram"]
    assert part["secrets"]["bot_token"] == {"set": True, "source": "ui"}
    assert part["enabled"]["value"] is True and "non si legge" in part["status"]["last_error"]
    test = other.post("/v1/settings/channels/telegram/test").json()
    assert test["ok"] is False and "non si legge" in test["error"]
    view = _patch(other, telegram=_tg(secrets={"bot_token": TOKEN2})).json()
    assert view["telegram"]["status"]["running"] is True and env.channel._token == TOKEN2


# --- Conferme --------------------------------------------------------------------------------------

def test_raising_the_clearance_needs_confirm_and_lowering_does_not(client, env):
    _patch(client, telegram=_tg({"clearance": "public"}))
    res = _patch(client, telegram=_tg({"clearance": "internal"}))
    assert res.status_code == 409 and _detail(res)["code"] == "confirm_required"
    assert "internal" in _detail(res)["message"]
    assert runtime_settings.get("telegram", "clearance") == "public"
    assert _patch(client, telegram=_tg({"clearance": "internal"}), confirm=True).status_code == 200
    assert _patch(client, telegram=_tg({"clearance": "public"})).status_code == 200
    # Tornare al .env (internal di base) da public è un rialzo: va confermato anche con null
    res = _patch(client, telegram=_tg({"clearance": None}))
    assert res.status_code == 409 and _detail(res)["code"] == "confirm_required"


def test_adding_a_user_needs_confirm_and_removing_does_not(client, env):
    env.env_set("telegram_allowed_users", "12")
    res = _patch(client, telegram=_tg({"allowed_users": [12, 34]}))
    assert res.status_code == 409 and _detail(res)["code"] == "confirm_required"
    assert "34" in _detail(res)["message"] and "comandi" in _detail(res)["message"]
    assert runtime_settings.get("telegram", "allowed_users") == [12]
    assert _patch(client, telegram=_tg({"allowed_users": [12, 34]}), confirm=True).status_code == 200
    assert _patch(client, telegram=_tg({"allowed_users": [34]})).status_code == 200  # togliere: nessuna conferma
    assert _patch(client, telegram=_tg({"allowed_users": []})).status_code == 200
    # null riporta il 12 del .env: è un utente in più
    res = _patch(client, telegram=_tg({"allowed_users": None}))
    assert res.status_code == 409 and _detail(res)["code"] == "confirm_required"


def test_a_refused_confirmation_saves_nothing_of_the_request(client):
    res = _patch(client, fields={"web_ui_url": LINK}, telegram=_tg({"allowed_users": [12], "enabled": False}))
    assert res.status_code == 409 and _db_dump() == "[]"


def test_other_fields_change_without_confirm(client):
    view = _patch(client, telegram=_tg({"enabled": False}), fields={"reply_timeout_seconds": 90}).json()
    assert view["telegram"]["enabled"] == {"value": False, "source": "ui"}


# --- Validazione -----------------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    {"telegram": {"fields": {"allowed_users": ["abc"]}}},
    {"telegram": {"fields": {"allowed_users": [0]}}},
    {"telegram": {"fields": {"allowed_users": [-5]}}},
    {"telegram": {"fields": {"allowed_users": [True]}}},
    {"telegram": {"fields": {"allowed_users": [1.5]}}},
    {"telegram": {"fields": {"allowed_users": "12,34"}}},
    {"telegram": {"fields": {"allowed_users": list(range(1, 102))}}},
    {"telegram": {"fields": {"clearance": "private"}}},
    {"telegram": {"fields": {"clearance": "secret"}}},
    {"telegram": {"fields": {"clearance": "Internal"}}},
    {"telegram": {"fields": {"enabled": "sì"}}},
    {"telegram": {"fields": {"colore": "blu"}}},
    {"telegram": {"secrets": {"api_key": TOKEN}}},
    {"telegram": {"secrets": {"bot_token": "non-un-token"}}},
    {"telegram": {"secrets": {"bot_token": ""}}},
    {"telegram": {"altro": {}}},
    {"telegram": []},
    {"fields": {"web_ui_url": "ftp://agent.example.test"}},
    {"fields": {"web_ui_url": "agent.example.test"}},
    {"fields": {"web_ui_url": "https://agent example.test"}},
    {"fields": {"web_ui_url": 5}},
    {"fields": {"reply_timeout_seconds": 29}},
    {"fields": {"reply_timeout_seconds": 3601}},
    {"fields": {"reply_timeout_seconds": "60"}},
    {"fields": {"reply_timeout_seconds": 60.5}},
    {"fields": {"reply_timeout_seconds": True}},
    {"fields": {"bot_token": TOKEN}},
    {"secrets": {"bot_token": TOKEN}},
    {"search": {}},
    {"fields": []},
    {"confirm": "yes"},
])
def test_invalid_values_are_422_and_save_nothing(keyed, body):
    # Un campo valido nella stessa richiesta: non si salva nemmeno quello
    payload = body if "fields" in body else {"fields": {"web_ui_url": LINK}, **body}
    res = keyed.patch("/v1/settings/channels", json=payload)
    assert res.status_code == 422, res.text
    assert _detail(res)["code"] == "invalid" and isinstance(_detail(res)["message"], str)
    assert TOKEN not in res.text and "non-un-token" not in res.text
    assert _db_dump() == "[]"


def test_private_is_refused_with_the_reason(client):
    res = _patch(client, telegram=_tg({"clearance": "private"}), confirm=True)
    assert res.status_code == 422 and "Telegram" in _detail(res)["message"]


def test_an_unknown_section_or_a_part_is_404(client):
    for res in (client.get("/v1/settings/nessuna"), client.patch("/v1/settings/nessuna", json={}),
                client.post("/v1/settings/nessuna/reset"), client.get("/v1/settings/telegram"),
                client.patch("/v1/settings/telegram", json={})):
        assert res.status_code == 404 and _detail(res)["code"] == "not_found", res.text


# --- Riavvio a caldo -------------------------------------------------------------------------------

def test_a_token_from_the_ui_starts_the_channel_without_a_restart(keyed, env):
    assert env.channel is None
    view = _start_bot(keyed)
    channel = env.channel
    assert channel is not None and channel.running and view["telegram"]["status"]["running"] is True
    assert _wait_until(lambda: env.api.polled_with(TOKEN))
    assert channel._allowed == frozenset({12}) and channel.capabilities.clearance == Label.INTERNAL


def test_disabling_stops_the_channel_and_enabling_starts_it_again(keyed, env):
    _start_bot(keyed)
    first = env.channel
    view = _patch(keyed, telegram=_tg({"enabled": False})).json()
    assert env.channel is None and not first.running and first._thread is None
    assert view["telegram"]["status"] == {"running": False, "last_error": None, "ignored": {}}
    polls = env.api.count(TOKEN, "getUpdates")
    time.sleep(0.1)
    assert env.api.count(TOKEN, "getUpdates") == polls  # nessun ciclo rimasto acceso
    view = _patch(keyed, telegram=_tg({"enabled": True})).json()
    assert view["telegram"]["status"]["running"] is True and env.channel is not first


def test_a_new_token_stops_the_old_bot_and_starts_the_new_one(keyed, env):
    _start_bot(keyed)
    old = env.channel
    assert _wait_until(lambda: env.api.polled_with(TOKEN))
    _patch(keyed, telegram=_tg(secrets={"bot_token": TOKEN2}))
    new = env.channel
    assert new is not old and new._token == TOKEN2 and new.running
    assert not old.running and old._thread is None and old._client is None
    polls = env.api.count(TOKEN, "getUpdates")
    assert _wait_until(lambda: env.api.polled_with(TOKEN2))
    time.sleep(0.1)
    assert env.api.count(TOKEN, "getUpdates") == polls  # il vecchio bot non legge più


def test_removing_the_token_or_the_users_stops_the_channel(keyed, env):
    _start_bot(keyed)
    _patch(keyed, telegram=_tg({"allowed_users": []}))
    assert env.channel is None
    _patch(keyed, telegram=_tg({"allowed_users": [12]}), confirm=True)
    assert env.channel.running
    _patch(keyed, telegram=_tg(secrets={"bot_token": None}))
    assert env.channel is None


def test_lowering_the_clearance_applies_to_the_running_channel(keyed, env):
    _start_bot(keyed)
    _patch(keyed, telegram=_tg({"clearance": "public"}))
    assert env.channel.capabilities.clearance == Label.PUBLIC and env.channel.destination().clearance == Label.PUBLIC


def test_a_channel_field_change_does_not_restart_telegram(keyed, env):
    _start_bot(keyed)
    channel = env.channel
    _patch(keyed, fields={"web_ui_url": LINK})
    assert env.channel is channel and channel.running


def test_the_status_reports_the_last_bot_api_error_redacted(keyed, env):
    env.api.rejected.add(TOKEN)
    _start_bot(keyed)
    assert _wait_until(lambda: env.channel.last_error is not None)
    status = keyed.get("/v1/settings/channels").json()["telegram"]["status"]
    assert status["running"] is True and "401" in status["last_error"]
    assert TOKEN not in status["last_error"] and telegram.REDACTED in status["last_error"]
    env.channel.ignored["message"] += 2
    assert keyed.get("/v1/settings/channels").json()["telegram"]["status"]["ignored"] == {"message": 2}


# --- Il hub: sostituire e togliere ----------------------------------------------------------------

class RecordingChannel(Channel):
    """Un canale finto che conta quanti sono avviati insieme con lo stesso id (`active`)."""

    active = {}
    overlaps = []
    lock = threading.Lock()

    def __init__(self, channel_id="fake", clearance=Label.INTERNAL):
        self._id = channel_id
        self._caps = Capabilities(max_message_length=500, clearance=clearance)
        self.running = False
        self.sent = []

    id = property(lambda self: self._id)
    capabilities = property(lambda self: self._caps)

    def start(self):
        with RecordingChannel.lock:
            RecordingChannel.active[self._id] = RecordingChannel.active.get(self._id, 0) + 1
            if RecordingChannel.active[self._id] > 1:
                RecordingChannel.overlaps.append(self._id)
            self.running = True
        time.sleep(0.001)

    def stop(self):
        time.sleep(0.002)  # come il join del ciclo di polling: fermare richiede tempo
        with RecordingChannel.lock:
            if self.running:
                RecordingChannel.active[self._id] -= 1
            self.running = False

    def deliver(self, chat_id, message):
        self.sent.append((chat_id, message))

    def texts(self):
        return [t for _, m in self.sent for t in m.chunks]


def test_replace_and_unregister_are_thread_safe():
    hub = ChannelHub()
    hub.start()
    RecordingChannel.active, RecordingChannel.overlaps = {}, []
    channels = [RecordingChannel("corsa") for _ in range(40)]
    hub.replace(channels[0])
    barrier = threading.Barrier(50)

    def together(fn, *args):
        barrier.wait(5)
        fn(*args)

    workers = [threading.Thread(target=together, args=(hub.replace, c)) for c in channels[1:]]
    workers += [threading.Thread(target=together, args=(hub.unregister, "corsa")) for _ in range(11)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(5)
    running = [c for c in channels if c.running]
    assert RecordingChannel.overlaps == []
    assert len(running) <= 1 and (hub.get("corsa") in running if running else hub.get("corsa") is None)
    hub.stop()
    assert not any(c.running for c in channels)


def test_replace_before_the_hub_starts_only_registers():
    hub = ChannelHub()
    channel = RecordingChannel("presto")
    hub.replace(channel)
    assert hub.get("presto") is channel and not channel.running
    hub.start()
    assert channel.running
    assert hub.unregister("presto") is channel and not channel.running and hub.get("presto") is None
    assert hub.unregister("presto") is None


def test_an_answer_in_flight_goes_out_through_the_channel_that_replaced_the_old_one(env, monkeypatch):
    """Un turno partito prima di un salvataggio risponde con il canale di adesso e con il suo livello."""
    gate = threading.Event()
    monkeypatch.setattr(agent_runner, "start_turn", lambda *a, **k: object())
    monkeypatch.setattr(agent_runner, "thread_has_active_turn", lambda thread_id: False)
    answer = {"response": "dato interno", "sensitivity": {"label": "internal", "untrusted": False, "reasons": []}}
    monkeypatch.setattr(hub_module, "_wait", lambda sess, timeout: gate.wait(5) and ("final", answer))
    old = RecordingChannel("fake")
    env.hub.register(old)
    worker = env.hub.dispatch(InboundMessage("fake", "c1", "u1", "ciao"))
    new = RecordingChannel("fake", clearance=Label.PUBLIC)
    env.hub.replace(new)
    gate.set()
    worker.join(5)
    assert old.sent == [] and new.texts() == ["La risposta contiene dati interni e non la mostro qui. (nessun link configurato)"]
    # Tolto del tutto: la risposta resta nell'app
    gate.clear()
    worker = env.hub.dispatch(InboundMessage("fake", "c1", "u1", "ciao"))
    env.hub.unregister("fake")
    gate.set()
    worker.join(5)
    assert len(new.sent) == 1


# --- Prova il bot ----------------------------------------------------------------------------------

def test_the_bot_test_uses_the_draft_or_the_saved_token(keyed, env):
    assert keyed.post("/v1/settings/channels/telegram/test").json() == {
        "ok": False, "bot_username": None, "error": "Nessun token: scrivilo qui o in TELEGRAM_BOT_TOKEN."}
    assert env.api.calls == []
    res = keyed.post("/v1/settings/channels/telegram/test", json={"secrets": {"bot_token": TOKEN2}})
    assert res.json() == {"ok": True, "bot_username": "bot_987654321", "error": None}
    assert _db_dump() == "[]"  # la bozza non si salva
    env.env_set("telegram_bot_token", ENV_TOKEN)
    assert keyed.post("/v1/settings/channels/telegram/test").json()["bot_username"] == "bot_555555555"
    _start_bot(keyed)
    assert keyed.post("/v1/settings/channels/telegram/test", json={}).json()["bot_username"] == "bot_123456789"
    assert env.api.count(TOKEN, "getMe") == 1 and env.api.count(TOKEN2, "getMe") == 1


def test_a_rejected_token_is_reported_without_the_token(client, env):
    env.api.rejected.add(TOKEN)
    res = client.post("/v1/settings/channels/telegram/test", json={"secrets": {"bot_token": TOKEN}})
    result = res.json()
    assert result["ok"] is False and result["bot_username"] is None and "401" in result["error"]
    assert TOKEN not in res.text and TOKEN.split(":")[1] not in res.text and telegram.REDACTED in result["error"]


def test_a_transport_error_in_the_bot_test_is_redacted(client, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)

    def leaky(request):
        raise httpx.ConnectError(f"impossibile raggiungere {request.url}")

    monkeypatch.setattr(telegram, "_bot_transport", lambda: httpx.MockTransport(leaky))
    res = client.post("/v1/settings/channels/telegram/test", json={"secrets": {"bot_token": TOKEN}})
    assert res.status_code == 200 and res.json()["ok"] is False and "ConnectError" in res.json()["error"]
    assert TOKEN not in res.text and TOKEN not in caplog.text


def test_a_malformed_draft_token_is_422(client, env):
    for body in ({"secrets": {"bot_token": "abc"}}, {"secrets": {"bot_token": 5}}, {"secrets": []},
                 {"secrets": {"altro": "x"}}):
        res = client.post("/v1/settings/channels/telegram/test", json=body)
        assert res.status_code == 422 and _detail(res)["code"] == "invalid", body
    assert env.api.calls == []


# --- Audit -----------------------------------------------------------------------------------------

def test_every_change_goes_to_the_audit_log_with_names_only(keyed, env):
    start = _audit_start()
    _patch(keyed, fields={"web_ui_url": "https://riconoscibile.example.test"})
    _start_bot(keyed, users=(424242,))
    entries = list(reversed(_audit_entries(start)))
    assert [e["tool_name"] for e in entries] == ["settings_update", "settings_update"]
    first, second = (json.loads(e["arguments_json"]) for e in entries)
    assert first == {"section": "channels", "by": "user", "fields": ["web_ui_url"], "secrets": [], "confirm": False}
    assert second == {"section": "telegram", "by": "user", "fields": ["allowed_users"], "secrets": ["bot_token"],
                      "confirm": True}
    text = json.dumps(entries)
    assert "riconoscibile" not in text and "424242" not in text and TOKEN not in text


# --- Percorsi e confini ----------------------------------------------------------------------------

def test_every_settings_route_requires_the_api_key(monkeypatch):
    from app.api.routes import settings as settings_routes
    routes = [r for r in settings_routes.router.routes if isinstance(r, APIRoute)]
    assert {(next(iter(r.methods)), r.path) for r in routes} == {
        ("GET", "/v1/settings/{section}"), ("PATCH", "/v1/settings/{section}"),
        ("POST", "/v1/settings/{section}/reset"), ("POST", "/v1/settings/channels/telegram/test")}
    for route in routes:
        assert verify_api_key in [d.call for d in route.dependant.dependencies], route.path
    monkeypatch.setattr(settings, "api_secret_key", KEY)
    anonymous = TestClient(api)
    for method, path in (("get", "/v1/settings/channels"), ("patch", "/v1/settings/channels"),
                         ("post", "/v1/settings/channels/reset"), ("post", "/v1/settings/channels/telegram/test")):
        assert getattr(anonymous, method)(path).status_code == 401, path
    wrong = TestClient(api, headers={"X-API-Key": "sbagliata"})
    assert wrong.get("/v1/settings/channels").status_code == 401
