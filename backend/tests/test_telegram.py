"""Fase C1 dei canali: Telegram, testo. Nessuna rete: la Bot API è un httpx.MockTransport (`BotApi`).

Il hub e il turno sono quelli veri (come in test_channels), con il grafo sostituito da `FakeGraph`."""
import json
import logging
import queue
import random
import threading
import time

import httpx
import pytest

from app import startup
from app.agent.stream_session import remove_session
from app.api import agent_runner
from app.channels import hub as hub_module
from app.channels import render, telegram, threads
from app.channels.base import Action, Capabilities, OutgoingMessage
from app.channels.hub import BUSY_TEXT, ChannelHub
from app.channels.telegram import TelegramChannel, TelegramError
from app.core.config import Settings, settings
from app.memory import thread_store
from app.security import audit_log
from app.security.flows import Label

# Token inventato, con la forma di quelli veri (id del bot, due punti, segreto)
TOKEN = "123456789:AAH-invented_token-for-the-tests-only"
LINK_BASE = "https://agent.example.test"


def ok(result):
    return httpx.Response(200, json={"ok": True, "result": result})


def api_error(code, description, **parameters):
    body = {"ok": False, "error_code": code, "description": description}
    if parameters:
        body["parameters"] = parameters
    return httpx.Response(code, json=body)


class BotApi:
    """La Bot API finta: registra ogni chiamata, dà gli update messi in `batches`, e per un metodo può rispondere con
    gli errori messi in `failures[metodo]` (uno per chiamata)."""

    def __init__(self):
        self.calls = []
        self.paths = []
        self.batches = queue.Queue()
        self.failures = {}
        self.lock = threading.Lock()

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        prefix = f"/bot{TOKEN}/"
        assert path.startswith(prefix), path
        method = path[len(prefix):]
        params = json.loads(request.content) if request.content else {}
        with self.lock:
            self.paths.append(path)
            self.calls.append((method, params))
            pending = self.failures.get(method)
            failure = pending.pop(0) if pending else None
        if failure is not None:
            return failure() if callable(failure) else failure
        if method == "getUpdates":
            batch = []
            if params.get("timeout"):
                try:
                    batch = self.batches.get(timeout=0.05)
                except queue.Empty:
                    pass
            return ok(batch)
        if method == "sendMessage":
            return ok({"message_id": len(self.calls)})
        return ok(True)

    def of(self, method):
        with self.lock:
            return [p for m, p in self.calls if m == method]

    def texts(self):
        return [p["text"] for p in self.of("sendMessage")]

    def wait_for(self, predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False


class FakeGraph:
    def __init__(self, answer="Risposta del grafo", label="public", gate=None, extra=None):
        self.answer, self.label, self.gate, self.extra = answer, label, gate, extra or {}
        self.states = []
        self.entered = threading.Event()

    def invoke(self, state, config=None):
        self.states.append(state)
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(10)
        final = {"final_response": self.answer, "mode": "chat", "tag": {"label": self.label, "untrusted": False, "reasons": []}}
        final.update(self.extra)
        return final


def message(update_id, user, text=None, chat=None, chat_type="private", **extra):
    body = {"message_id": update_id, "date": 0, "from": {"id": user, "is_bot": False, "first_name": "Utente"},
            "chat": {"id": user if chat is None else chat, "type": chat_type}}
    if text is not None:
        body["text"] = text
    body.update(extra)
    return {"update_id": update_id, "message": body}


def callback(update_id, user, data, chat=None, chat_type="private", with_message=True):
    query = {"id": f"q{update_id}", "from": {"id": user, "is_bot": False, "first_name": "Utente"}, "data": data}
    if with_message:
        query["message"] = {"message_id": 1, "chat": {"id": user if chat is None else chat, "type": chat_type}}
    return {"update_id": update_id, "callback_query": query}


@pytest.fixture
def tg(monkeypatch):
    monkeypatch.setattr(settings, "web_ui_url", LINK_BASE)
    monkeypatch.setattr(settings, "channel_reply_timeout_seconds", 10)
    monkeypatch.setattr(thread_store, "generate_and_save_title", lambda *a, **k: None)

    class Env:
        api = BotApi()
        hub = ChannelHub()
        alice = random.randint(10 ** 8, 10 ** 9)  # id nuovi a ogni test: ogni chat ha la sua conversazione
        bob = alice + 1
        eve = alice + 2  # non ammessa
        graph = FakeGraph()

        def take(self, update):
            worker = self.channel._take(update)
            if worker is not None:
                worker.join(10)
                assert not worker.is_alive()
            return worker

        def thread(self, user=None):
            return threads.current_thread("telegram", str(user or self.alice))

        def reveal_token(self):
            markup = [p for p in self.api.of("sendMessage") if "reply_markup" in p][-1]["reply_markup"]
            data = next(b["callback_data"] for b in markup["inline_keyboard"][0] if "callback_data" in b)
            return data

    e = Env()
    e.channel = TelegramChannel(TOKEN, frozenset({e.alice, e.bob}), e.hub, transport=httpx.MockTransport(e.api.handler),
                                poll_timeout=1)
    e.hub.register(e.channel)
    e.channel._client = e.channel._make_client()
    monkeypatch.setattr(agent_runner, "get_app_graph", lambda: e.graph)
    yield e
    e.channel.stop()
    if e.channel._client is not None:
        e.channel._client.close()
    for user in (e.alice, e.bob):
        remove_session(e.thread(user))


# --- Ricezione: long polling e offset -------------------------------------------------------------

def test_polling_reads_updates_advances_the_offset_and_stop_acknowledges(tg):
    tg.channel._client = None
    tg.channel.start()
    tg.api.batches.put([message(41, tg.alice, "ciao"), message(42, tg.alice, "/link")])
    assert tg.api.wait_for(lambda: len(tg.api.texts()) >= 2)
    assert tg.api.wait_for(lambda: any(p.get("offset") == 43 for p in tg.api.of("getUpdates")))
    first = tg.api.of("getUpdates")[0]
    assert "offset" not in first and first["timeout"] == 1 and first["allowed_updates"] == ["message", "callback_query"]
    assert set(tg.api.texts()) == {"Risposta del grafo", f"{LINK_BASE}/c/{tg.thread()}"}
    tg.channel.stop()
    final = tg.api.of("getUpdates")[-1]
    assert final == {"timeout": 0, "limit": 1, "offset": 43}  # conferma gli update gestiti e chiude l'attesa
    assert tg.channel._thread is None and tg.channel._client is None
    calls = len(tg.api.calls)
    time.sleep(0.2)
    assert len(tg.api.calls) == calls  # il ciclo è fermo


def test_every_update_moves_the_offset_even_if_it_cannot_be_handled(tg):
    tg.take({"update_id": 7, "edited_message": {"text": "x"}})
    tg.take(message(9, tg.eve, "chi sono?"))
    assert tg.channel._offset == 10
    tg.take({"update_id": "rotto"})
    assert tg.channel._offset == 10


def test_errors_back_off_and_polling_resumes(tg, monkeypatch):
    delays = []
    monkeypatch.setattr(telegram, "_backoff", lambda failures, retry_after: delays.append((failures, retry_after)) or 0.01)
    tg.api.failures["getUpdates"] = [api_error(502, "Bad Gateway"), api_error(429, "Too Many Requests", retry_after=3),
                                     lambda: (_ for _ in ()).throw(httpx.ConnectError("rete giù"))]
    tg.channel._client = None
    tg.channel.start()
    tg.api.batches.put([message(5, tg.alice, "ciao")])
    assert tg.api.wait_for(lambda: tg.api.texts() == ["Risposta del grafo"])
    assert delays == [(1, None), (2, 3), (3, None)]
    assert any(p.get("offset") == 6 for p in tg.api.of("getUpdates")) or tg.api.wait_for(
        lambda: any(p.get("offset") == 6 for p in tg.api.of("getUpdates")))


def test_backoff_doubles_up_to_a_minute_and_honours_retry_after():
    assert [telegram._backoff(n, None) for n in (1, 2, 3, 4, 7, 20)] == [1, 2, 4, 8, 60, 60]
    assert telegram._backoff(1, 30) == 30
    assert telegram._backoff(1, 10 ** 6) == 300


def test_a_batch_received_while_stopping_is_not_handled_nor_acknowledged(tg):
    tg.channel._stopping.set()
    tg.api.batches.put([message(3, tg.alice, "tardi")])
    tg.channel._poll_loop()  # esce subito: il ciclo non gira con lo stop impostato
    assert tg.api.of("getUpdates") == [] and tg.channel._offset is None
    tg.channel._stopping.clear()
    tg.api.failures["getUpdates"] = [lambda: (tg.channel._stopping.set(), ok([message(3, tg.alice, "tardi")]))[1]]
    tg.channel._poll_loop()
    assert tg.channel._offset is None and tg.api.texts() == []


# --- Chi può scrivere -----------------------------------------------------------------------------

def test_only_allowed_users_in_private_chats_reach_the_agent(tg, caplog):
    caplog.set_level(logging.DEBUG)
    tg.take(message(1, tg.eve, "testo di uno sconosciuto"))
    tg.take(message(2, tg.alice, "testo nel gruppo", chat=-100123, chat_type="group"))
    tg.take(message(3, tg.alice, "chat di un altro", chat=tg.bob))
    tg.take({"update_id": 4, "message": {"message_id": 4, "chat": {"id": tg.alice, "type": "private"}, "text": "senza mittente"}})
    assert tg.graph.states == [] and tg.api.of("sendMessage") == []
    assert tg.channel.ignored["message"] == 4
    assert "sconosciuto" not in caplog.text and "nel gruppo" not in caplog.text  # il testo non si salva
    assert str(tg.eve) in caplog.text  # l'id sì: serve a chi configura TELEGRAM_ALLOWED_USERS
    tg.take(message(5, tg.alice, "ciao"))
    tg.take(message(6, tg.bob, "ciao anche da me"))
    assert [s["task"] for s in tg.graph.states] == ["ciao", "ciao anche da me"]
    assert [p["chat_id"] for p in tg.api.of("sendMessage")] == [tg.alice, tg.bob]
    assert tg.thread(tg.alice) != tg.thread(tg.bob)


def test_an_ignored_user_is_logged_once(tg, caplog):
    caplog.set_level(logging.INFO, logger="channels.telegram")
    for i in range(3):
        tg.take(message(i, tg.eve, "spam"))
    assert caplog.text.count(str(tg.eve)) == 1 and tg.channel.ignored["message"] == 3


def test_a_forwarded_message_enters_as_untrusted_and_is_not_a_command(tg):
    tg.take(message(1, tg.alice, "scritto da altri", forward_origin={"type": "hidden_user", "sender_user_name": "X", "date": 0}))
    tg.take(message(2, tg.alice, "/nuova", forward_date=0))
    tg.take(message(3, tg.alice, "scritto da me"))
    tags = [s["tag"] for s in tg.graph.states]
    assert [s["task"] for s in tg.graph.states] == ["scritto da altri", "/nuova", "scritto da me"]
    assert tags[0]["untrusted"] is True and tags[1]["untrusted"] is True and tags[2]["untrusted"] is False


def test_a_message_without_text_gets_a_short_reply(tg):
    tg.take(message(1, tg.alice, photo=[{"file_id": "f"}]))
    assert tg.api.texts() == [telegram.TEXT_ONLY] and tg.graph.states == []


# --- Comandi --------------------------------------------------------------------------------------

def test_start_greets_and_lists_the_commands(tg):
    tg.take(message(1, tg.alice, "/start"))
    tg.take(message(2, tg.alice, "/start@mio_bot payload"))
    assert tg.api.texts() == [render.literal(telegram.START_TEXT, tg.channel.capabilities)] * 2
    assert all(c in telegram.START_TEXT for c in ("/nuova", "/stop", "/link"))
    assert tg.graph.states == []


def test_nuova_stop_and_link(tg):
    tg.take(message(1, tg.alice, "uno"))
    first = tg.thread()
    tg.take(message(2, tg.alice, "/nuova"))
    assert tg.api.texts()[-1] == "Conversazione nuova aperta." and tg.thread() != first
    tg.take(message(3, tg.alice, "/link@mio_bot"))
    assert tg.api.texts()[-1] == f"{LINK_BASE}/c/{tg.thread()}"
    tg.take(message(4, tg.alice, "/stop"))
    assert tg.api.texts()[-1] == "Nessun turno in corso."


def test_stop_reaches_a_running_turn_and_busy_is_refused(tg):
    gate = threading.Event()
    tg.graph = FakeGraph(gate=gate)
    running = tg.channel._take(message(1, tg.alice, "lungo"))
    assert tg.graph.entered.wait(5)
    tg.take(message(2, tg.alice, "altro"))
    assert tg.api.texts()[-1] == render.literal(BUSY_TEXT, tg.channel.capabilities)
    tg.take(message(3, tg.alice, "/stop"))
    assert tg.api.texts()[-1] == "Turno fermato."
    running.join(5)
    gate.set()
    assert "Risposta del grafo" not in tg.api.texts()


def test_typing_is_shown_while_the_turn_runs(tg, monkeypatch):
    monkeypatch.setattr(telegram, "TYPING_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(telegram, "TYPING_INTERVAL_SECONDS", 0.05)
    gate = threading.Event()
    tg.graph = FakeGraph(gate=gate)
    worker = tg.channel._take(message(1, tg.alice, "pensa"))
    assert tg.api.wait_for(lambda: len(tg.api.of("sendChatAction")) >= 2)
    assert tg.api.of("sendChatAction")[0] == {"chat_id": tg.alice, "action": "typing"}
    gate.set()
    worker.join(5)
    actions = len(tg.api.of("sendChatAction"))
    time.sleep(0.15)
    assert len(tg.api.of("sendChatAction")) == actions  # finito il turno, smette


# --- Uscita: HTML, divisione, link ----------------------------------------------------------------

def test_the_answer_is_sent_as_telegram_html_without_link_previews(tg):
    tg.graph = FakeGraph(answer="**Fatto**: `a < b` & <script>x</script>")
    tg.take(message(1, tg.alice, "ciao"))
    sent = tg.api.of("sendMessage")[-1]
    assert sent["parse_mode"] == "HTML" and sent["link_preview_options"] == {"is_disabled": True}
    assert sent["text"] == "<b>Fatto</b>: <code>a &lt; b</code> &amp; &lt;script&gt;x&lt;/script&gt;"
    assert "reply_markup" not in sent and sent["chat_id"] == tg.alice


def test_markdown_to_html_escapes_everything_and_maps_the_blocks():
    md = ("# Titolo <b>\n\nUn **grassetto**, *corsivo*, ~~tolto~~, snake_case_name e `x<y>&z`.\n"
          "[sito](https://x.test/?a=1&b=\"2\") [male](javascript:alert(1))\n- voce\n* altra\n"
          "> citazione **forte**\n---\n```python\nif a < b: print(\"&\")\n```\n```\n<raw>\n```")
    out = render.to_telegram_html(md)
    assert out.split("\n") == [
        "<b>Titolo &lt;b&gt;</b>", "",
        "Un <b>grassetto</b>, <i>corsivo</i>, <s>tolto</s>, snake_case_name e <code>x&lt;y&gt;&amp;z</code>.",
        '<a href="https://x.test/?a=1&amp;b=&quot;2&quot;">sito</a> male (javascript:alert(1))',
        "• voce", "• altra",
        "<blockquote>citazione <b>forte</b></blockquote>",
        render.RULE_TEXT,
        '<pre><code class="language-python">if a &lt; b: print("&amp;")</code></pre>',
        "<pre>&lt;raw&gt;</pre>"]


def test_a_table_becomes_an_aligned_monospace_block():
    md = "| nome | valore |\n|---|---|\n| a<b | 1 |\n| lungo nome | `22` |"
    assert render.to_telegram_html(md) == ("<pre>nome       | valore\n-----------+-------\na&lt;b        | 1\n"
                                           "lungo nome | 22</pre>")


def test_crossed_marks_fall_back_to_escaped_plain_text():
    out = render.to_telegram_html("**a *b** c* <x>")
    assert out == "a b c &lt;x&gt;"
    assert render._balanced(out)


def test_no_user_text_can_open_a_tag():
    hostile = '<a href="javascript:x">y</a> <b>**</b> `</code>` [<i>](https://x.test/"><b>) </pre>'
    out = render.to_telegram_html(hostile)
    tags = render._OUR_TAG.findall(out)
    assert tags == [("", "code"), ("/", "code"), ("", "a"), ("/", "a")]
    assert 'href="https://x.test/&quot;&gt;&lt;b&gt;"' in out


def test_long_answers_are_split_within_the_telegram_limit():
    caps = TelegramChannel(TOKEN, frozenset({1}), ChannelHub()).capabilities
    text = "\n\n".join(f"Paragrafo {i}: " + "parola " * 80 for i in range(30))
    chunks = render.render_chunks(text, caps)
    assert len(chunks) > 3 and all(render._visible_length(c) <= 4096 for c in chunks)
    emoji = "\U0001F600" * 3000  # ognuna vale due unità UTF-16 per Telegram
    chunks = render.render_chunks(emoji, caps)
    assert len(chunks) == 2 and all(render._visible_length(c) <= 4096 for c in chunks)
    assert "".join(chunks) == emoji
    code = "```\n" + "\n".join(f"riga {i} <x>" for i in range(800)) + "\n```"
    chunks = render.render_chunks(code, caps)
    assert len(chunks) > 1 and all(c.startswith("<pre>") and c.endswith("</pre>") for c in chunks)
    assert all(render._visible_length(c) <= 4096 for c in chunks)


def test_an_answer_too_long_for_the_chat_ends_with_the_link(tg):
    tg.graph = FakeGraph(answer="\n\n".join("x" * 4000 for _ in range(8)))
    tg.take(message(1, tg.alice, "tanto"))
    sent = tg.api.of("sendMessage")
    assert len(sent) == telegram.MAX_MESSAGES
    assert sent[-1]["text"] == "La risposta continua nell'app."
    assert sent[-1]["reply_markup"] == {"inline_keyboard": [[{"text": "Apri nell'app", "url": f"{LINK_BASE}/c/{tg.thread()}"}]]}
    assert all("reply_markup" not in p for p in sent[:-1])


def test_html_refused_by_telegram_is_resent_as_plain_text(tg):
    tg.api.failures["sendMessage"] = [api_error(400, "Bad Request: can't parse entities: unexpected end tag")]
    tg.channel.deliver(str(tg.alice), OutgoingMessage(["<b>ciao</b> &amp; addio"]))
    first, second = tg.api.of("sendMessage")
    assert first["parse_mode"] == "HTML"
    assert "parse_mode" not in second and second["text"] == "ciao & addio"


def test_a_refused_url_button_becomes_a_link_in_the_text(tg):
    tg.api.failures["sendMessage"] = [api_error(400, "Bad Request: BUTTON_URL_INVALID")]
    link = f"{LINK_BASE}/c/t1"
    tg.channel.deliver(str(tg.alice), OutgoingMessage(
        ["dati private"], [Action("reveal", "Mostra qui", "tok"), Action("open", "Apri nell'app", "tok")], link))
    second = tg.api.of("sendMessage")[-1]
    assert second["text"] == f"dati private\n{link}"
    assert second["reply_markup"] == {"inline_keyboard": [[{"text": "Mostra qui", "callback_data": "reveal:tok"}]]}


def test_a_rate_limited_send_waits_and_retries_once(tg):
    waits = []
    tg.channel._sleep = waits.append
    tg.api.failures["sendMessage"] = [api_error(429, "Too Many Requests: retry after 2", retry_after=2)]
    tg.channel.deliver(str(tg.alice), OutgoingMessage(["ciao"]))
    assert waits == [2.0] and len(tg.api.of("sendMessage")) == 2
    tg.api.failures["sendMessage"] = [api_error(500, "Internal")]
    with pytest.raises(TelegramError):
        tg.channel.deliver(str(tg.alice), OutgoingMessage(["ciao"]))


def test_an_answer_that_needs_an_approval_points_to_the_app(tg):
    tg.graph = FakeGraph(answer="rm -rf /", extra={"approval_required": True, "request_id": "apr_1"})
    tg.take(message(1, tg.alice, "cancella"))
    sent = tg.api.of("sendMessage")[-1]
    assert sent["text"] == "Serve un'approvazione: apri l'app." and "rm -rf" not in json.dumps(tg.api.calls)
    assert sent["reply_markup"]["inline_keyboard"][0] == [{"text": "Apri nell'app", "url": f"{LINK_BASE}/c/{tg.thread()}"}]


# --- `private`: pulsanti e callback -------------------------------------------------------------

def test_a_private_answer_offers_the_buttons_and_reveal_shows_it_once(tg):
    tg.graph = FakeGraph(answer="Il codice del cancello è 4321", label="private")
    tg.take(message(1, tg.alice, "codice?"))
    notice = tg.api.of("sendMessage")[-1]
    assert notice["text"] == "La risposta contiene dati private."
    data = tg.reveal_token()
    assert notice["reply_markup"] == {"inline_keyboard": [[
        {"text": "Mostra qui", "callback_data": data},
        {"text": "Apri nell'app", "url": f"{LINK_BASE}/c/{tg.thread()}"}]]}
    assert data.startswith("reveal:") and len(data.encode()) <= 64
    assert "4321" not in json.dumps(tg.api.calls)
    tg.take(callback(2, tg.alice, data))
    assert tg.api.texts()[-1] == "Il codice del cancello è 4321"
    assert tg.api.of("answerCallbackQuery") == [{"callback_query_id": "q2"}]
    tg.take(callback(3, tg.alice, data))  # una volta sola
    assert tg.api.texts().count("Il codice del cancello è 4321") == 1
    assert tg.api.of("answerCallbackQuery")[-1] == {"callback_query_id": "q3", "text": telegram.REVEAL_GONE}
    flows = [r["flow"] for r in audit_log.get_recent(limit=20, thread_id=tg.thread()) if r["tool_name"] == "channel_delivery"]
    assert flows == ["approved", "ask"]


def test_a_callback_from_someone_else_reveals_nothing(tg):
    tg.graph = FakeGraph(answer="Il codice del cancello è 4321", label="private")
    tg.take(message(1, tg.alice, "codice?"))
    data = tg.reveal_token()
    tg.take(callback(2, tg.eve, data, chat=tg.alice))  # non ammessa, sul messaggio della chat di Alice
    tg.take(callback(3, tg.eve, data))  # non ammessa, nella sua chat
    tg.take(callback(4, tg.alice, data, chat=-100123, chat_type="group"))  # Alice, ma da un gruppo
    tg.take(callback(5, tg.alice, data, with_message=False))  # senza messaggio (inline): nessuna chat da controllare
    assert tg.channel.ignored["callback"] == 4 and tg.api.of("answerCallbackQuery") == []
    tg.take(callback(6, tg.bob, data))  # ammesso, ma il token è della chat di Alice
    assert tg.api.of("answerCallbackQuery") == [{"callback_query_id": "q6", "text": telegram.REVEAL_GONE}]
    assert "4321" not in json.dumps(tg.api.calls)
    tg.take(callback(7, tg.alice, data))  # il token vale ancora per la chat giusta
    assert tg.api.texts()[-1] == "Il codice del cancello è 4321"


def test_unknown_callback_data_is_answered_and_does_nothing(tg):
    tg.take(callback(1, tg.alice, "reveal:inventato"))
    tg.take(callback(2, tg.alice, "altro"))
    assert [p.get("text") for p in tg.api.of("answerCallbackQuery")] == [telegram.REVEAL_GONE] * 2
    assert tg.api.of("sendMessage") == []


@pytest.mark.parametrize("label,expected", [("public", "allow"), ("internal", "allow"), ("secret", "deny")])
def test_labels_up_to_internal_pass_and_secret_never(tg, label, expected):
    tg.graph = FakeGraph(answer="contenuto 77", label=label)
    tg.take(message(1, tg.alice, "ciao"))
    assert ("contenuto 77" in tg.api.texts()) is (expected == "allow")
    assert [r["flow"] for r in audit_log.get_recent(limit=5, thread_id=tg.thread()) if r["tool_name"] == "channel_delivery"] == [expected]


def test_with_public_clearance_internal_needs_the_button(tg):
    channel = TelegramChannel(TOKEN, frozenset({1}), tg.hub, clearance=Label.PUBLIC)
    assert channel.capabilities.clearance == Label.PUBLIC and channel.capabilities.confirm_up_to == Label.PRIVATE
    assert channel.destination().id == "channel:telegram"


# --- Il token non esce mai ------------------------------------------------------------------------

def test_the_token_is_only_in_the_path_sent_to_telegram(tg, caplog):
    caplog.set_level(logging.DEBUG)
    for name in telegram._FILTERED_LOGGERS:
        logging.getLogger(name).addFilter(tg.channel._filter)
    try:
        tg.channel.deliver(str(tg.alice), OutgoingMessage(["ciao"]))
    finally:
        for name in telegram._FILTERED_LOGGERS:
            logging.getLogger(name).removeFilter(tg.channel._filter)
    assert tg.api.paths == [f"/bot{TOKEN}/sendMessage"]
    assert "HTTP Request: POST https://api.telegram.org/sendMessage" in caplog.text  # il log di httpx, senza token
    assert TOKEN not in caplog.text and TOKEN.split(":")[1] not in caplog.text


def test_transport_errors_never_carry_the_token(tg, caplog):
    def leaky(request):
        raise httpx.ConnectError(f"impossibile raggiungere {request.url}")

    tg.channel._transport = httpx.MockTransport(leaky)
    tg.channel._client = tg.channel._make_client()
    with pytest.raises(TelegramError) as raised:
        tg.channel.deliver(str(tg.alice), OutgoingMessage(["ciao"]))
    assert TOKEN not in str(raised.value) and telegram.REDACTED in str(raised.value)
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    with pytest.raises(httpx.ConnectError) as inner:
        tg.channel._client.post("/getMe")
    assert TOKEN not in str(inner.value) and TOKEN not in str(inner.value.request.url)
    assert inner.value.__cause__ is None and inner.value.__suppress_context__


def test_the_poll_loop_logs_failures_without_the_token(tg, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(telegram, "_backoff", lambda failures, retry_after: 0.01)
    tg.api.failures["getUpdates"] = [api_error(401, f"Unauthorized: bad token {TOKEN}"),
                                     lambda: (_ for _ in ()).throw(httpx.ReadTimeout(f"lento su /bot{TOKEN}/getUpdates")),
                                     api_error(409, "Conflict: terminated by other getUpdates request")]
    tg.channel._client = None
    tg.channel.start()
    assert tg.api.wait_for(lambda: len(tg.api.of("getUpdates")) >= 4)
    tg.channel.stop()
    assert "TELEGRAM_BOT_TOKEN" in caplog.text and "webhook" in caplog.text
    assert "getUpdates non riuscita" in caplog.text
    assert TOKEN not in caplog.text and TOKEN.split(":")[1] not in caplog.text


def test_a_failed_delivery_logged_by_the_hub_has_no_token(tg, caplog):
    caplog.set_level(logging.DEBUG)
    tg.api.failures["sendMessage"] = [lambda: (_ for _ in ()).throw(httpx.ConnectError(f"giù: /bot{TOKEN}/sendMessage"))]
    tg.take(message(1, tg.alice, "ciao"))
    assert "non gestito" in caplog.text
    assert TOKEN not in caplog.text


def test_redact_and_the_settings_repr():
    assert telegram.redact(f"x {TOKEN} y") == f"x {telegram.REDACTED} y"
    assert telegram.redact("altro 987654321:ABCDEFGHIJKLMNOPQRSTUV_-x fine") == f"altro {telegram.REDACTED} fine"
    assert telegram.redact("segreto-corto", "segreto-corto") == telegram.REDACTED
    configured = Settings(TELEGRAM_BOT_TOKEN=TOKEN)
    assert TOKEN not in repr(configured) and TOKEN not in str(configured)


# --- Configurazione -------------------------------------------------------------------------------

def test_the_channel_is_off_without_a_token(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "  ")
    monkeypatch.setattr(settings, "telegram_allowed_users", "1")
    hub = ChannelHub()
    assert telegram.register_configured(hub) is None and hub.get("telegram") is None


@pytest.mark.parametrize("users", ["", " , ", "12,abc", "-5", "@nome", "1.5"])
def test_the_channel_does_not_start_without_valid_allowed_users(monkeypatch, caplog, users):
    monkeypatch.setattr(settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(settings, "telegram_allowed_users", users)
    hub = ChannelHub()
    with caplog.at_level(logging.ERROR, logger="channels.telegram"):
        assert telegram.register_configured(hub) is None
    assert hub.get("telegram") is None
    assert "TELEGRAM_ALLOWED_USERS" in caplog.text and TOKEN not in caplog.text


def test_a_configured_channel_is_registered_once_with_its_clearance(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(settings, "telegram_allowed_users", " 12 , 34,12 ")
    monkeypatch.setattr(settings, "telegram_clearance", "public")
    hub = ChannelHub()
    channel = telegram.register_configured(hub)
    assert hub.get("telegram") is channel and channel._allowed == frozenset({12, 34})
    assert channel.capabilities.clearance == Label.PUBLIC
    assert telegram.register_configured(hub) is channel


def test_the_clearance_defaults_to_internal_and_bad_values_are_refused(caplog):
    assert Settings.model_fields["telegram_clearance"].default == "internal"
    assert Settings.model_fields["telegram_bot_token"].default == ""
    assert Settings.model_fields["telegram_allowed_users"].default == ""
    assert Settings(TELEGRAM_CLEARANCE=" Internal ").telegram_clearance == "internal"
    assert Settings(TELEGRAM_CLEARANCE="public").telegram_clearance == "public"
    for raw in ("private", "secret", "tutto", ""):
        with caplog.at_level(logging.ERROR, logger="config"):
            assert Settings(TELEGRAM_CLEARANCE=raw).telegram_clearance == "public"
    assert "TELEGRAM_CLEARANCE" in caplog.text


def test_the_app_start_registers_and_starts_the_configured_channel(monkeypatch):
    hub = ChannelHub()
    monkeypatch.setattr(hub_module, "_hub", hub)
    monkeypatch.setattr(settings, "telegram_bot_token", TOKEN)
    monkeypatch.setattr(settings, "telegram_allowed_users", "12")
    started, stopped = [], []
    monkeypatch.setattr(TelegramChannel, "start", lambda self: started.append(self))
    monkeypatch.setattr(TelegramChannel, "stop", lambda self: stopped.append(self))
    monkeypatch.setattr(startup, "get_registry_manager", lambda: None)
    monkeypatch.setattr(startup.health, "start_sampler", lambda: None)
    monkeypatch.setattr(startup.health, "stop_sampler", lambda: None)
    monkeypatch.setattr(startup.memory_consolidation, "start_scheduler", lambda: None)
    monkeypatch.setattr(startup.memory_consolidation, "stop_scheduler", lambda: None)
    monkeypatch.setattr(settings, "enable_automation_scheduler", False)
    startup.start()
    assert len(started) == 1 and hub.get("telegram") is started[0]
    startup.stop()
    assert stopped == started


def test_the_channel_needs_a_token_and_users():
    with pytest.raises(ValueError):
        TelegramChannel("", frozenset({1}), ChannelHub())
    with pytest.raises(ValueError):
        TelegramChannel(TOKEN, frozenset(), ChannelHub())


def test_capabilities_cap_the_number_of_messages():
    with pytest.raises(ValueError):
        Capabilities(max_message_length=10, max_messages=1)
    caps = TelegramChannel(TOKEN, frozenset({1}), ChannelHub()).capabilities
    assert (caps.max_message_length, caps.text_format, caps.buttons, caps.clearance, caps.confirm_up_to) == (
        4096, "html", True, Label.INTERNAL, Label.PRIVATE)
