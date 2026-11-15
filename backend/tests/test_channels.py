"""Fase C0 dei canali: interfaccia, legame chat-conversazione, hub con il controllo di sensibilità e rendering.

Il grafo è sostituito come in test_agent_runner_stream; `FakeChannel` ricorda ciò che consegna."""
import threading
import time
import uuid
from unittest.mock import patch

import pytest

from app import startup
from app.agent.stream_session import create_session, get_session, remove_session
from app.api import agent_runner
from app.channels import hub as hub_module
from app.channels import render, threads
from app.channels.base import Capabilities, Channel, InboundMessage
from app.channels.hub import BUSY_TEXT, ChannelHub
from app.core.config import settings
from app.memory import thread_store
from app.security import audit_log, flows
from app.security.flows import Label

LINK_BASE = "https://agent.example.test"


class FakeChannel(Channel):
    """Canale finto: ricorda cosa riceve `deliver`."""

    def __init__(self, channel_id="fake", capabilities=None):
        self._id = channel_id
        self._caps = capabilities or Capabilities(
            max_message_length=200, text_format="markdown", buttons=True, style_hint="Rispondi in breve, senza tabelle.",
            clearance=Label.INTERNAL, confirm_up_to=Label.PRIVATE)
        self.sent = []
        self.started = 0
        self.stopped = 0

    id = property(lambda self: self._id)
    capabilities = property(lambda self: self._caps)

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def deliver(self, chat_id, message):
        self.sent.append((chat_id, message))

    def texts(self, chat_id=None):
        return [t for c, m in self.sent if chat_id in (None, c) for t in m.chunks]


class FakeGraph:
    """Grafo finto: risponde `answer` con l'etichetta `label`; con `gate` aspetta che il test lo apra."""

    def __init__(self, answer="Risposta del grafo", label="public", gate=None, extra=None, fail=None):
        self.answer, self.label, self.gate, self.extra, self.fail = answer, label, gate, extra or {}, fail
        self.states = []
        self.entered = threading.Event()

    def invoke(self, state, config=None):
        self.states.append(state)
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(10)
        if self.fail:
            raise RuntimeError(self.fail)
        final = {"final_response": self.answer, "mode": "chat", "tag": {"label": self.label, "untrusted": False, "reasons": []}}
        final.update(self.extra)
        return final


@pytest.fixture
def env(monkeypatch):
    """Un hub con un FakeChannel, il link della Web UI impostato e il grafo sostituibile con `env.graph(...)`."""
    monkeypatch.setattr(settings, "web_ui_url", LINK_BASE)
    monkeypatch.setattr(settings, "channel_reply_timeout_seconds", 10)
    monkeypatch.setattr(thread_store, "generate_and_save_title", lambda *a, **k: None)

    class Env:
        hub = ChannelHub()
        channel = FakeChannel()
        chat = f"chat-{uuid.uuid4().hex[:8]}"
        current_graph = FakeGraph()

        def graph(self, **kwargs):
            self.current_graph = FakeGraph(**kwargs)
            return self.current_graph

        def say(self, text, chat=None, **kwargs):
            self.hub.handle_inbound(InboundMessage("fake", chat or self.chat, "u1", text, **kwargs))

        def thread(self, chat=None):
            return threads.current_thread("fake", chat or self.chat)

        def exits(self, chat=None):
            rows = audit_log.get_recent(limit=50, thread_id=self.thread(chat))
            return [(r["destination"], r["label"], r["flow"]) for r in rows if r["tool_name"] == "channel_delivery"]

    e = Env()
    e.hub.register(e.channel)
    monkeypatch.setattr(agent_runner, "get_app_graph", lambda: e.current_graph)
    yield e
    for chat_thread in list(threads_of(e)):
        remove_session(chat_thread)


def threads_of(e):
    conn = threads._get_conn()
    try:
        return [r[0] for r in conn.execute("SELECT thread_id FROM channel_threads WHERE channel = 'fake'")]
    finally:
        conn.close()


# --- Un messaggio diventa un turno ----------------------------------------------------------------

def test_a_message_becomes_a_turn_on_the_chat_thread_and_the_answer_comes_back(env):
    env.graph(answer="Ciao, sono l'agente")
    env.say("Ciao")
    thread = env.thread()
    assert env.channel.sent[-1][0] == env.chat
    assert env.channel.texts() == ["Ciao, sono l'agente"]
    state = env.current_graph.states[0]
    assert state["thread_id"] == thread and state["channel"] == "fake" and state["task"] == "Ciao"
    assert [m["sender"] for m in thread_store.get_thread_messages(thread)] == ["user", "assistant"]


def test_the_same_chat_keeps_its_thread_and_nuova_changes_it(env):
    env.say("uno")
    first = env.thread()
    env.say("due")
    assert env.thread() == first
    assert {s["thread_id"] for s in env.current_graph.states} == {first}
    env.say("/nuova")
    assert env.channel.texts()[-1] == "Conversazione nuova aperta."
    second = env.thread()
    assert second != first
    env.say("tre")
    assert env.current_graph.states[-1]["thread_id"] == second
    assert len(thread_store.get_thread_messages(first)) == 4  # la vecchia conversazione resta com'era


def test_two_chats_get_two_threads(env):
    env.say("a", chat="chat-A-" + env.chat)
    env.say("b", chat="chat-B-" + env.chat)
    a, b = env.thread("chat-A-" + env.chat), env.thread("chat-B-" + env.chat)
    assert a != b
    assert [s["thread_id"] for s in env.current_graph.states] == [a, b]


def test_the_command_may_carry_the_bot_name_and_blank_messages_are_ignored(env):
    env.say("/nuova@mio_bot")
    assert env.channel.texts() == ["Conversazione nuova aperta."]
    env.say("   ")
    assert len(env.channel.sent) == 1 and env.current_graph.states == []


def test_the_user_message_may_carry_images(env):
    env.say("guarda", images=("data:image/png;base64,AA",))
    assert env.current_graph.states[0]["images"] == ["data:image/png;base64,AA"]
    assert env.current_graph.states[0]["tag"]["untrusted"] is True


# --- Turno in corso, /stop, /link -----------------------------------------------------------------

def test_a_busy_thread_refuses_the_message_and_saves_nothing(env):
    thread = env.thread()
    sess = create_session(thread, task="in corso")
    env.say("secondo messaggio")
    assert env.channel.texts() == [BUSY_TEXT]
    assert env.current_graph.states == []
    assert thread_store.get_thread_messages(thread) == []
    assert get_session(thread) is sess
    sess.put(None)


def test_stop_stops_the_running_turn_of_the_chat_thread(env):
    gate = threading.Event()
    graph = env.graph(gate=gate)
    worker = env.hub.dispatch(InboundMessage("fake", env.chat, "u1", "lungo", ))
    assert graph.entered.wait(5)
    thread = env.thread()
    sess = get_session(thread)
    assert sess.is_active()
    env.say("/stop")
    assert env.channel.texts() == ["Turno fermato."]
    assert sess.is_stopped()
    worker.join(5)
    assert not worker.is_alive()
    gate.set()
    assert env.channel.texts() == ["Turno fermato."]  # la risposta tardiva non viene consegnata
    assert thread_store.get_thread_messages(thread)[-1]["content"] == "[Esecuzione interrotta dall'utente]"


def test_stop_without_a_turn_says_so_and_does_not_touch_the_conversation(env):
    env.say("/stop")
    assert env.channel.texts() == ["Nessun turno in corso."]
    assert thread_store.get_thread_messages(env.thread()) == []


def test_link_with_and_without_web_ui_url(env, monkeypatch):
    env.say("/link")
    assert env.channel.texts() == [f"{LINK_BASE}/c/{env.thread()}"]
    monkeypatch.setattr(settings, "web_ui_url", LINK_BASE + "/")
    env.say("/link")
    assert env.channel.texts()[-1] == f"{LINK_BASE}/c/{env.thread()}"
    monkeypatch.setattr(settings, "web_ui_url", "")
    env.say("/link")
    assert "Nessun link configurato" in env.channel.texts()[-1]


# --- Contenuto scritto da altri, modalità, stile ---------------------------------------------------

def test_a_forwarded_message_enters_as_untrusted_and_is_never_a_command(env):
    env.say("testo di un altro", forwarded=True)
    tag = env.current_graph.states[0]["tag"]
    assert tag["untrusted"] is True and tag["label"] == "public"
    env.say("/nuova", forwarded=True)  # un "/nuova" inoltrato è testo, non un comando
    assert len(env.current_graph.states) == 2 and env.current_graph.states[1]["task"] == "/nuova"
    env.say("scritto da me")
    assert env.current_graph.states[2]["tag"]["untrusted"] is False


def test_the_security_mode_of_a_channel_turn_is_normal(env):
    env.say("ciao")
    assert env.current_graph.states[0]["security_mode"] == "normal"


def test_the_style_hint_of_the_channel_reaches_the_answer_prompt(env, monkeypatch):
    from app.agent import llm_calls
    from app.llm import roles

    class Provider:
        calls = []

        def effective_model(self, model):
            return "m"

        def chat(self, messages, **kwargs):
            self.calls.append([m["content"] for m in messages if m["role"] == "system"])
            return {"content": "ok", "reasoning_content": ""}

    provider = Provider()

    class Answering(FakeGraph):
        def invoke(self, state, config=None):
            with patch.object(llm_calls, "get_provider", return_value=provider):
                llm_calls.call_llm("q", system_prompt="Sei l'agente.", tag=flows.PUBLIC_TAG, role=roles.ANSWER)
            return super().invoke(state, config)

    env.current_graph = Answering()
    env.say("ciao")
    assert provider.calls == [["Sei l'agente.\n\nRispondi in breve, senza tabelle."]]


# --- Il controllo di sensibilità ------------------------------------------------------------------

@pytest.mark.parametrize("label", ["public", "internal"])
def test_an_answer_up_to_the_clearance_is_delivered(env, label):
    env.graph(answer="Contenuto", label=label)
    env.say("ciao")
    assert env.channel.texts() == ["Contenuto"]
    assert env.channel.sent[-1][1].actions == []
    assert env.exits() == [("channel:fake", label, "allow")]


def test_a_private_answer_gives_a_notice_and_reveal_delivers_it_once(env):
    env.graph(answer="Dati riservati", label="private")
    env.say("ciao")
    chat, notice = env.channel.sent[-1]
    assert notice.chunks == ["La risposta contiene dati private."]
    assert [a.label for a in notice.actions] == ["Mostra qui", "Apri nell'app"]
    assert notice.link == f"{LINK_BASE}/c/{env.thread()}"
    assert "Dati riservati" not in " ".join(env.channel.texts())
    assert env.exits() == [("channel:fake", "private", "ask")]
    token = next(a.token for a in notice.actions if a.kind == "reveal")
    assert env.hub.reveal(token, chat) is True
    assert env.channel.texts()[-1] == "Dati riservati"
    assert env.exits() == [("channel:fake", "private", "approved"), ("channel:fake", "private", "ask")]
    assert env.hub.reveal(token, chat) is False  # una volta sola
    assert env.channel.texts().count("Dati riservati") == 1


def test_a_reveal_token_expires(env, monkeypatch):
    env.graph(answer="Dati riservati", label="private")
    env.say("ciao")
    token = env.channel.sent[-1][1].actions[0].token
    time.sleep(0.01)
    monkeypatch.setattr(hub_module, "REVEAL_TTL_SECONDS", -1)  # i token nuovi scadono subito
    env.say("ancora")
    expired = env.channel.sent[-1][1].actions[0].token
    time.sleep(0.01)
    assert env.hub.reveal(expired) is False
    assert "scaduta" in env.channel.texts()[-1]
    assert "Dati riservati" not in env.channel.texts()[-1]
    assert not any(f == "approved" for _, _, f in env.exits())
    assert env.hub.reveal(token) is True  # quello fatto prima della modifica vale ancora


def test_a_reveal_token_is_bound_to_its_chat_and_unknown_tokens_do_nothing(env):
    env.graph(answer="Dati riservati", label="private")
    env.say("ciao")
    token = env.channel.sent[-1][1].actions[0].token
    sent = len(env.channel.sent)
    assert env.hub.reveal(token, "altra-chat") is False
    assert env.hub.reveal("token-inventato", env.chat) is False
    assert len(env.channel.sent) == sent
    assert env.hub.reveal(token, env.chat) is True


def test_a_secret_answer_gives_the_notice_and_the_link_only(env):
    env.graph(answer="la password è hunter2", label="secret")
    env.say("ciao")
    message = env.channel.sent[-1][1]
    assert "segreto" in message.chunks[0] and message.link == f"{LINK_BASE}/c/{env.thread()}"
    assert [a.kind for a in message.actions] == ["open"]
    assert "hunter2" not in " ".join(env.channel.texts())
    assert env.exits() == [("channel:fake", "secret", "deny")]


def test_above_the_confirmation_level_gives_the_notice_and_the_link_only(env):
    env.channel._caps = Capabilities(max_message_length=200, buttons=True, clearance=Label.INTERNAL, confirm_up_to=Label.INTERNAL)
    env.graph(answer="dati privati", label="private")
    env.say("ciao")
    message = env.channel.sent[-1][1]
    assert [a.kind for a in message.actions] == ["open"] and message.link
    assert "dati privati" not in " ".join(env.channel.texts())
    assert env.exits() == [("channel:fake", "private", "deny")]


def test_without_buttons_a_private_answer_is_not_offered_for_confirmation(env):
    env.channel._caps = Capabilities(max_message_length=200, buttons=False, clearance=Label.INTERNAL, confirm_up_to=Label.PRIVATE)
    env.graph(answer="dati privati", label="private")
    env.say("ciao")
    message = env.channel.sent[-1][1]
    assert message.actions == [] and message.link
    assert env.exits() == [("channel:fake", "private", "deny")]


def test_a_notice_without_web_ui_url_says_there_is_no_link(env, monkeypatch):
    monkeypatch.setattr(settings, "web_ui_url", "")
    env.graph(answer="dati privati", label="private")
    env.say("ciao")
    message = env.channel.sent[-1][1]
    assert [a.kind for a in message.actions] == ["reveal"] and message.link is None
    env.graph(answer="segreto", label="secret")
    env.say("ancora")
    assert "nessun link configurato" in env.channel.texts()[-1]


def test_an_answer_without_a_label_is_treated_as_private(env):
    env.hub._deliver_answer(env.channel, env.chat, env.thread(), {"response": "senza etichetta"})
    assert "senza etichetta" not in " ".join(env.channel.texts())
    assert env.exits() == [("channel:fake", "private", "ask")]


def test_an_answer_that_needs_an_approval_gives_a_notice(env):
    env.graph(answer="Eseguo il comando rm -rf?", label="public",
              extra={"approval_required": True, "request_id": "apr_1"})
    env.say("cancella tutto")
    message = env.channel.sent[-1][1]
    assert message.chunks == ["Serve un'approvazione: apri l'app."] and message.link
    assert "rm -rf" not in " ".join(env.channel.texts())
    assert env.exits() == []  # nessun dato è uscito


def test_every_delivery_is_a_data_exit_the_ui_view_reads(env):
    since = "1970-01-01T00:00:00"
    before = {d["destination"]: d for d in audit_log.flow_summary(since)["destinations"]}.get("channel:fake", {"allow": 0, "ask": 0, "deny": 0, "approved": 0})
    for label in ("public", "private", "secret"):
        env.graph(label=label)
        env.say("ciao")
    summary = {d["destination"]: d for d in audit_log.flow_summary(since)["destinations"]}["channel:fake"]
    assert summary["allow"] - before["allow"] == 1
    assert summary["ask"] - before["ask"] == 1
    assert summary["deny"] - before["deny"] == 1
    recent = [e for e in audit_log.flow_summary(since, recent=50)["recent"] if e["destination"] == "channel:fake" and e["thread_id"] == env.thread()]
    assert {e["flow"] for e in recent} == {"ask", "deny"}
    assert all("caratteri" in e["summary"] for e in recent)
    row = [r for r in audit_log.get_recent(limit=50, thread_id=env.thread()) if r["tool_name"] == "channel_delivery"][0]
    assert "Risposta del grafo" not in str(row)  # il testo della risposta non finisce nell'audit


# --- Timeout, errori ------------------------------------------------------------------------------

def test_a_slow_turn_replies_that_the_answer_will_be_in_the_app(env, monkeypatch):
    monkeypatch.setattr(settings, "channel_reply_timeout_seconds", 0.3)
    gate = threading.Event()
    env.graph(gate=gate, answer="Risposta lenta")
    started = time.monotonic()
    env.say("ciao")
    assert time.monotonic() - started < 3
    message = env.channel.sent[-1][1]
    assert "più tempo" in message.chunks[0] and message.link == f"{LINK_BASE}/c/{env.thread()}"
    assert get_session(env.thread()).is_active()  # il turno continua
    gate.set()
    for _ in range(100):
        if not get_session(env.thread()).is_active():
            break
        time.sleep(0.05)
    assert thread_store.get_thread_messages(env.thread())[-1]["content"] == "Risposta lenta"
    assert "Risposta lenta" not in " ".join(env.channel.texts())


def test_a_failed_turn_replies_with_a_generic_notice(env):
    env.graph(fail="boom interno")
    env.say("ciao")
    assert "non è riuscito" in env.channel.texts()[-1]
    assert "boom" not in env.channel.texts()[-1]


def test_a_turn_that_finishes_before_the_hub_subscribes_is_still_delivered(env):
    graph = env.graph(answer="Veloce")
    original = agent_runner.start_turn

    def start_and_wait(*args, **kwargs):
        sess = original(*args, **kwargs)
        assert graph.entered.wait(5)
        for _ in range(200):
            if sess.is_finished():
                break
            time.sleep(0.01)
        return sess

    with patch.object(agent_runner, "start_turn", start_and_wait):
        env.say("ciao")
    assert env.channel.texts() == ["Veloce"]


def test_delivery_errors_are_logged_and_do_not_escape(env):
    env.channel.deliver = lambda chat_id, message: (_ for _ in ()).throw(RuntimeError("rete"))
    env.say("ciao")
    env.hub.handle_inbound(InboundMessage("sconosciuto", "c", "u", "x"))


# --- Hub: ciclo di vita ---------------------------------------------------------------------------

def test_the_hub_starts_and_stops_its_channels_and_a_failing_one_does_not_block_the_rest():
    hub = ChannelHub()
    broken, fine = FakeChannel("broken"), FakeChannel("fine")
    broken.start = lambda: (_ for _ in ()).throw(RuntimeError("niente token"))
    hub.register(broken)
    hub.register(fine)
    hub.start()
    assert fine.started == 1
    hub.stop()
    assert fine.stopped == 1 and broken.stopped == 1
    with pytest.raises(ValueError):
        hub.register(FakeChannel("fine"))
    assert hub.get("fine") is fine and hub.get("altro") is None


def test_with_no_channel_registered_nothing_starts(monkeypatch):
    empty = ChannelHub()
    empty.start()
    empty.stop()
    monkeypatch.setattr(hub_module, "_hub", empty)
    calls = []
    monkeypatch.setattr(startup, "get_registry_manager", lambda: None)
    monkeypatch.setattr(startup.health, "start_sampler", lambda: calls.append("sampler"))
    monkeypatch.setattr(startup.memory_consolidation, "start_scheduler", lambda: calls.append("consolidation"))
    monkeypatch.setattr(settings, "enable_automation_scheduler", False)
    startup.start()
    assert calls == ["sampler", "consolidation"]


def test_the_app_start_and_stop_reach_the_registered_channels(monkeypatch):
    hub = ChannelHub()
    channel = FakeChannel("app")
    hub.register(channel)
    monkeypatch.setattr(hub_module, "_hub", hub)
    monkeypatch.setattr(startup, "get_registry_manager", lambda: None)
    monkeypatch.setattr(startup.health, "start_sampler", lambda: None)
    monkeypatch.setattr(startup.health, "stop_sampler", lambda: None)
    monkeypatch.setattr(startup.memory_consolidation, "start_scheduler", lambda: None)
    monkeypatch.setattr(startup.memory_consolidation, "stop_scheduler", lambda: None)
    monkeypatch.setattr(settings, "enable_automation_scheduler", False)
    startup.start()
    assert channel.started == 1
    startup.stop()
    assert channel.stopped == 1


# --- Capacità, destinazione, legame con la conversazione ------------------------------------------

def test_the_destination_comes_from_the_capabilities():
    channel = FakeChannel("tg", Capabilities(max_message_length=10, clearance=Label.PUBLIC))
    dest = channel.destination()
    assert (dest.id, dest.kind, dest.clearance) == ("channel:tg", "channel", Label.PUBLIC)
    assert flows.channel_destination("x", Label.INTERNAL) == flows.Destination("channel:x", "channel", Label.INTERNAL)
    assert flows.can_flow(flows.tag_of("internal", "t"), dest).allowed is False
    assert flows.can_flow(flows.tag_of("internal", "t"), flows.channel_destination("x", Label.INTERNAL)).allowed is True


@pytest.mark.parametrize("kwargs", [
    {"max_message_length": 0}, {"max_message_length": 5, "text_format": "rtf"},
    {"max_message_length": 5, "clearance": Label.SECRET}, {"max_message_length": 5, "confirm_up_to": Label.SECRET},
    {"max_message_length": 5, "clearance": Label.PRIVATE, "confirm_up_to": Label.INTERNAL}])
def test_invalid_capabilities_are_refused(kwargs):
    with pytest.raises(ValueError):
        Capabilities(**kwargs)


def test_the_channel_threads_table_lives_in_the_conversations_database():
    import sqlite3
    conn = sqlite3.connect(settings.checkpoint_db_path)
    try:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(channel_threads)")]
        pk = [r[1] for r in conn.execute("PRAGMA table_info(channel_threads)") if r[5]]
        assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'thread_messages'").fetchone()
    finally:
        conn.close()
    assert columns == ["channel", "chat_id", "thread_id", "updated_at"] and sorted(pk) == ["channel", "chat_id"]


def test_threads_are_created_on_first_use_and_are_unique():
    chat = uuid.uuid4().hex
    first = threads.current_thread("fake", chat)
    assert first.startswith("thread_") and threads.current_thread("fake", chat) == first
    assert threads.current_thread("other", chat) != first
    assert threads.current_thread("fake", chat + "x") != first
    fresh = threads.new_thread("fake", chat)
    assert fresh != first and threads.current_thread("fake", chat) == fresh
    ids = {threads.new_thread("fake", f"{chat}-{i}") for i in range(20)}
    assert len(ids) == 20


# --- Rendering ------------------------------------------------------------------------------------

def test_short_text_is_a_single_chunk():
    assert render.split_markdown("Ciao\n\nmondo", 100) == ["Ciao\n\nmondo"]
    assert render.split_markdown("", 100) == []


def test_split_prefers_paragraphs_then_lines_and_respects_the_length():
    text = "uno uno uno\n\ndue due due\n\ntre tre tre"
    assert render.split_markdown(text, 25) == ["uno uno uno\n\ndue due due", "tre tre tre"]
    lines = "\n".join(f"riga {i}" for i in range(10))
    chunks = render.split_markdown(lines, 22)
    assert all(len(c) <= 22 for c in chunks) and "\n".join(chunks) == lines
    long_line = "parola " * 30
    chunks = render.split_markdown(long_line, 40)
    assert all(len(c) <= 40 for c in chunks) and " ".join(chunks).split() == long_line.split()
    assert all(len(c) <= 10 for c in render.split_markdown("x" * 35, 10)) and "".join(render.split_markdown("x" * 35, 10)) == "x" * 35


def test_a_code_block_that_fits_is_never_split_from_its_text():
    text = "Ecco:\n\n```python\nprint(1)\n```\n\nFine."
    assert render.split_markdown(text, 100) == [text]
    chunks = render.split_markdown(text, 25)
    assert chunks == ["Ecco:", "```python\nprint(1)\n```", "Fine."]
    assert all(len(c) <= 25 for c in chunks)
    assert any(c.startswith("```python") and c.endswith("```") for c in chunks)


def test_a_code_block_too_long_is_closed_and_reopened_in_each_chunk():
    code = "\n".join(f"x{i} = {i}" for i in range(20))
    chunks = render.split_markdown(f"Prima\n\n```python\n{code}\n```\n\nDopo", 70)
    assert len(chunks) > 3 and all(len(c) <= 70 for c in chunks)
    for chunk in chunks:
        assert chunk.count("```") % 2 == 0  # ogni recinto è chiuso dentro lo stesso pezzo
    code_chunks = [c for c in chunks if "```python" in c]
    assert all(c.startswith("```python\n") and c.endswith("\n```") for c in code_chunks)
    rebuilt = "\n".join(line for c in code_chunks for line in c.split("\n")[1:-1])
    assert rebuilt == code
    assert chunks[0] == "Prima" and chunks[-1] == "Dopo"


def test_blank_lines_inside_code_survive_and_an_unclosed_fence_is_closed():
    chunks = render.split_markdown("```\na\n\nb\n```", 100)
    assert chunks == ["```\na\n\nb\n```"]
    assert render.split_markdown("```\na\nb", 100) == ["```\na\nb\n```"]


def test_a_long_fence_marker_is_closed_with_the_same_marker():
    chunks = render.split_markdown("````\n" + "\n".join(["riga lunga lunga"] * 6) + "\n````", 40)
    assert all(c.startswith("````\n") and c.endswith("\n````") and len(c) <= 40 for c in chunks)


def test_plain_text_loses_the_markdown_marks_but_keeps_code_and_words():
    md = ("# Titolo\n\nUn **grassetto**, un *corsivo*, un _altro_ e snake_case_name, `a*b*c` e ~~tolto~~.\n"
          "> citazione\n* voce\n- altra\n[sito](http://x.test) ![foto](http://i.test/a.png)\n---\n"
          "| a | b |\n|---|---|\n| 1 | 2 |\n```py\nx = 2 * 3 * 4\n```\nFine")
    plain = render.strip_markdown(md)
    assert plain == ("Titolo\n\nUn grassetto, un corsivo, un altro e snake_case_name, a*b*c e tolto.\n"
                     "citazione\n- voce\n- altra\nsito (http://x.test) foto (http://i.test/a.png)\n"
                     "| a | b |\n| 1 | 2 |\nx = 2 * 3 * 4\nFine")


def test_render_chunks_follows_the_capabilities():
    plain = Capabilities(max_message_length=30, text_format="plain")
    assert render.render_chunks("**ciao** `x`", plain) == ["ciao x"]
    md = Capabilities(max_message_length=30, text_format="markdown")
    assert render.render_chunks("**ciao** `x`", md) == ["**ciao** `x`"]
    assert render.render_chunks("", md) == []
    with pytest.raises(NotImplementedError):
        render.render_chunks("x", Capabilities(max_message_length=30, text_format="html"))


def test_a_long_answer_is_delivered_in_several_chunks_within_the_limit(env):
    env.channel._caps = Capabilities(max_message_length=50, text_format="plain", clearance=Label.INTERNAL)
    env.graph(answer="# Titolo\n\n" + "frase di prova. " * 12)
    env.say("ciao")
    chunks = env.channel.sent[-1][1].chunks
    assert len(chunks) > 2 and all(len(c) <= 50 for c in chunks) and chunks[0] == "Titolo"


def test_an_empty_answer_is_still_delivered(env):
    env.graph(answer="")
    env.say("ciao")
    assert env.channel.texts() == ["(risposta vuota)"]


def test_actions_are_dropped_for_channels_without_buttons(env):
    env.channel._caps = Capabilities(max_message_length=200, buttons=False)
    env.graph(label="secret")
    env.say("ciao")
    assert env.channel.sent[-1][1].actions == [] and env.channel.sent[-1][1].link


def test_dispatch_runs_the_message_in_its_own_thread(env):
    worker = env.hub.dispatch(InboundMessage("fake", env.chat, "u1", "ciao"))
    worker.join(5)
    assert env.channel.texts() == ["Risposta del grafo"]


# --- Casi di confine (aggiunti dopo le mutazioni sopravvissute) ------------------------------------

def test_stop_after_the_turn_ended_does_not_add_an_interruption_note(env):
    env.say("ciao")
    thread = env.thread()
    before = len(thread_store.get_thread_messages(thread))
    env.say("/stop")
    assert env.channel.texts()[-1] == "Nessun turno in corso."
    assert len(thread_store.get_thread_messages(thread)) == before
    assert not get_session(thread).is_stopped()


def test_pieces_that_exactly_fill_the_limit_share_a_chunk():
    assert render.split_markdown("aaaa\n\nbbbb", 10) == ["aaaa\n\nbbbb"]
    assert render.split_markdown("aaaa\n\nbbbb", 9) == ["aaaa", "bbbb"]


def test_the_hub_never_sends_actions_to_a_channel_without_buttons(env):
    env.channel._caps = Capabilities(max_message_length=200, buttons=False)
    from app.channels.base import Action, OutgoingMessage
    env.hub._deliver(env.channel, env.chat, OutgoingMessage(["x"], [Action("reveal", "Mostra", "t")]))
    assert env.channel.sent[-1][1].actions == []


def test_held_answers_are_purged_when_expired_and_capped(env, monkeypatch):
    monkeypatch.setattr(hub_module, "REVEAL_TTL_SECONDS", -1)
    env.hub._hold("fake", env.chat, "t1", "a", Label.PRIVATE)
    env.hub._hold("fake", env.chat, "t1", "b", Label.PRIVATE)
    assert len(env.hub._pending) == 1  # il primo, scaduto, è stato tolto dal secondo
    monkeypatch.setattr(hub_module, "REVEAL_TTL_SECONDS", 600)
    monkeypatch.setattr(hub_module, "MAX_PENDING", 3)
    tokens = [env.hub._hold("fake", env.chat, "t1", str(i), Label.PRIVATE) for i in range(5)]
    assert len(env.hub._pending) == 3
    assert tokens[0] not in env.hub._pending and tokens[-1] in env.hub._pending
