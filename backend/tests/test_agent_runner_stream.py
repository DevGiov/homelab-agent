"""Streaming del turno web (run_agent_flow_stream) con il grafo sostituito: il comportamento che i canali condividono."""
import asyncio
import json
import time
from unittest.mock import patch

from app.agent.stream_session import current_session_var, get_session, remove_session
from app.api import agent_runner
from app.memory import thread_store


class _Graph:
    def __init__(self, answer="Ciao dal grafo", label="public", fail=None):
        self.answer, self.label, self.fail = answer, label, fail
        self.states = []

    def invoke(self, state, config=None):
        self.states.append(state)
        if self.fail:
            raise RuntimeError(self.fail)
        return {"final_response": self.answer, "mode": "chat", "tag": {"label": self.label, "untrusted": False, "reasons": []}}


class _FallbackGraph(_Graph):
    """Un grafo in cui due chiamate (la stessa coppia due volte) e una terza vanno al modello locale."""

    def invoke(self, state, config=None):
        sess = current_session_var.get()
        for reason, to in (("label", "local"), ("label", "local"), ("budget", "local2")):
            sess.put({"type": "provider_fallback", "from": "cloud", "to": to, "reason": reason})
        return super().invoke(state, config)


def _collect(response) -> list:
    async def run():
        return [chunk async for chunk in response.body_iterator]
    events = []
    for raw in asyncio.run(run()):
        payload = raw.strip()[len("data: "):]
        events.append(payload if payload == "[DONE]" else json.loads(payload))
    return events


def _stream(graph, thread_id, **kwargs):
    with patch.object(agent_runner, "get_app_graph", return_value=graph), \
            patch.object(thread_store, "generate_and_save_title"):
        response = agent_runner.run_agent_flow_stream("ciao", thread_id, model="m", **kwargs)
        events = _collect(response)
    return events


def test_stream_saves_the_message_and_ends_with_final_and_done():
    thread = f"t-stream-{time.time_ns()}"
    graph = _Graph()
    events = _stream(graph, thread)
    assert events[-1] == "[DONE]"
    final = [e for e in events if isinstance(e, dict) and e["type"] == "final"][0]
    assert final["response"]["response"] == "Ciao dal grafo"
    assert final["response"]["thread_id"] == thread
    messages = thread_store.get_thread_messages(thread)
    assert [m["sender"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "ciao"
    assert graph.states[0]["thread_id"] == thread
    assert graph.states[0]["security_mode"] == "normal"
    assert "channel" not in graph.states[0] or graph.states[0]["channel"] is None
    remove_session(thread)


def test_stream_reports_and_saves_the_fallbacks_once_per_distinct_note():
    thread = f"t-stream-fb-{time.time_ns()}"
    events = _stream(_FallbackGraph(), thread)
    expected = [{"from": "cloud", "to": "local", "reason": "label"}, {"from": "cloud", "to": "local2", "reason": "budget"}]
    final = [e for e in events if isinstance(e, dict) and e["type"] == "final"][0]
    assert final["response"]["fallbacks"] == expected
    assert thread_store.get_thread_messages(thread)[-1]["fallbacks"] == expected
    remove_session(thread)


def test_stream_without_fallbacks_saves_none():
    thread = f"t-stream-nofb-{time.time_ns()}"
    events = _stream(_Graph(), thread)
    final = [e for e in events if isinstance(e, dict) and e["type"] == "final"][0]
    assert final["response"]["fallbacks"] is None
    assert thread_store.get_thread_messages(thread)[-1]["fallbacks"] is None
    remove_session(thread)


def test_stream_builds_a_thread_id_when_missing():
    graph = _Graph()
    events = _stream(graph, None)
    final = [e for e in events if isinstance(e, dict) and e["type"] == "final"][0]
    assert final["response"]["thread_id"].startswith("thread_")
    remove_session(final["response"]["thread_id"])


def test_stream_error_is_saved_and_sent():
    thread = f"t-stream-err-{time.time_ns()}"
    events = _stream(_Graph(fail="boom"), thread)
    assert any(isinstance(e, dict) and e["type"] == "error" and "boom" in e["error"] for e in events)
    last = thread_store.get_thread_messages(thread)[-1]
    assert last["sender"] == "assistant" and "boom" in last["content"]
    remove_session(thread)


def test_stream_keeps_the_requested_security_mode_and_level():
    thread = f"t-stream-mode-{time.time_ns()}"
    graph = _Graph()
    _stream(graph, thread, security_mode="dangerous", sensitivity="private")
    assert graph.states[0]["security_mode"] == "dangerous"
    assert graph.states[0]["tag"]["label"] == "private"
    remove_session(thread)


def test_stream_attaches_to_an_active_turn_without_starting_another():
    thread = f"t-stream-busy-{time.time_ns()}"
    sess = agent_runner.create_session(thread, task="x")
    graph = _Graph()
    with patch.object(agent_runner, "get_app_graph", return_value=graph):
        response = agent_runner.run_agent_flow_stream("secondo", thread, model="m")
    assert get_session(thread) is sess
    assert graph.states == []
    # Il messaggio viene salvato anche se non parte un secondo turno (comportamento della Web UI)
    assert thread_store.get_thread_messages(thread)[0]["content"] == "secondo"
    sess.put(None)
    _collect(response)
    remove_session(thread)


def _start(graph, thread, **kwargs):
    with patch.object(agent_runner, "get_app_graph", return_value=graph), \
            patch.object(thread_store, "generate_and_save_title"):
        sess = agent_runner.start_turn("ciao", thread, model="m", **kwargs)
        queue_ = sess.subscribe()
        deadline = time.time() + 5
        while not sess.is_finished() and time.time() < deadline:
            time.sleep(0.01)
        sess.unsubscribe(queue_)
    return sess


def test_start_turn_returns_the_session_of_the_thread():
    thread = f"t-start-{time.time_ns()}"
    sess = _start(_Graph(), thread)
    assert sess.thread_id == thread and get_session(thread) is sess
    assert sess.final_response["response"] == "Ciao dal grafo"
    remove_session(thread)


def test_start_turn_with_a_channel_puts_it_in_the_state_and_forces_normal_mode():
    thread = f"t-start-ch-{time.time_ns()}"
    graph = _Graph()
    _start(graph, thread, channel="fake", security_mode="dangerous")
    assert graph.states[0]["channel"] == "fake"
    assert graph.states[0]["security_mode"] == "normal"
    remove_session(thread)


def test_start_turn_without_a_channel_leaves_the_mode_alone():
    thread = f"t-start-web-{time.time_ns()}"
    graph = _Graph()
    _start(graph, thread, security_mode="dangerous")
    assert graph.states[0]["security_mode"] == "dangerous"
    assert "channel" not in graph.states[0]
    remove_session(thread)


def test_start_turn_joins_the_extra_tag_to_the_request():
    thread = f"t-start-tag-{time.time_ns()}"
    graph = _Graph()
    extra = agent_runner.flows.tag_of("public", "inoltrato", untrusted=True)
    _start(graph, thread, channel="fake", extra_tag=extra)
    assert graph.states[0]["tag"]["untrusted"] is True
    assert "untrusted:inoltrato" in graph.states[0]["tag"]["reasons"]
    remove_session(thread)
    plain = _Graph()
    thread = f"t-start-tag2-{time.time_ns()}"
    _start(plain, thread, channel="fake")
    assert plain.states[0]["tag"]["untrusted"] is False
    remove_session(thread)


class _Provider:
    """Provider finto: ricorda i messaggi che riceve."""
    def __init__(self):
        self.calls = []

    def effective_model(self, model):
        return model or "m"

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs["role"]))
        return {"content": "ok", "reasoning_content": ""}


class _AnsweringGraph:
    """Grafo che scrive una risposta e una scelta di tool con il provider finto, come i nodi veri."""
    def __init__(self):
        self.provider = _Provider()

    def invoke(self, state, config=None):
        from app.agent import llm_calls
        from app.llm import roles
        with patch.object(llm_calls, "get_provider", return_value=self.provider):
            llm_calls.call_llm("domanda", system_prompt="Sei l'agente.", tag=agent_runner.flows.PUBLIC_TAG, role=roles.ANSWER)
            llm_calls.call_llm("scegli", system_prompt="Scegli il tool.", tag=agent_runner.flows.PUBLIC_TAG, role=roles.SELECT_TOOL)
            llm_calls.call_llm("senza", tag=agent_runner.flows.PUBLIC_TAG, role=roles.ANSWER)
        return {"final_response": "ok", "mode": "chat"}


def _system_prompts(graph):
    return [([m["content"] for m in messages if m["role"] == "system"] or [None])[0] for messages, _ in graph.provider.calls]


def test_the_style_hint_reaches_the_answer_prompts_only():
    thread = f"t-style-{time.time_ns()}"
    graph = _AnsweringGraph()
    _start(graph, thread, channel="fake", style_hint="Rispondi in breve, senza tabelle.")
    answer, selection, no_system = _system_prompts(graph)
    assert answer == "Sei l'agente.\n\nRispondi in breve, senza tabelle."
    assert selection == "Scegli il tool."
    assert no_system == "Rispondi in breve, senza tabelle."
    remove_session(thread)


def test_the_web_ui_gets_no_style_line():
    thread = f"t-nostyle-{time.time_ns()}"
    graph = _AnsweringGraph()
    _start(graph, thread)
    assert _system_prompts(graph) == ["Sei l'agente.", "Scegli il tool.", None]
    remove_session(thread)
