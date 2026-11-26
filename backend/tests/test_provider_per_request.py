"""Ogni richiesta porta il suo provider (docs/providers/PROVIDERS_DESIGN.md, 5.8.1): nessun provider attivo globale.

Il test centrale fa girare due turni in parallelo, uno su un provider finto locale e uno su un provider finto cloud,
attraverso un grafo LangGraph vero con le chiamate interne di oggi (router, risposta, un tool in parallelo che chiama
un modello, il titolo in un thread a parte): ogni chiamata registrata è sul provider del suo turno."""
import threading
import time
from typing import Any, Dict, List, Optional, TypedDict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langgraph.graph import END, START, StateGraph

from app.agent import llm_calls, mode_router
from app.agent.stream_session import current_session_var, remove_session
from app.api import agent_runner
from app.api.main import api
from app.llm import providers, roles
from app.llm.providers import LLMProvider
from app.memory import thread_store
from app.registry.manager import ToolRegistryManager
from app.security.flows import PUBLIC_TAG, Label


class FakeProvider(LLMProvider):
    """Un provider che non va in rete: registra chi l'ha chiamato, con che ruolo, modello e turno."""

    def __init__(self, name: str, clearance: Label, model: str, calls: List[Dict[str, Any]], lock: threading.Lock):
        self.name, self.clearance, self.default_model = name, clearance, model
        self._calls, self._lock = calls, lock

    def chat(self, messages, *, tag, role, model=None, **kwargs):
        sess = current_session_var.get()
        with self._lock:
            self._calls.append({"provider": self.name, "role": role, "model": self.effective_model(model),
                                "thread": sess.thread_id if sess else None, "text": str(messages[-1]["content"])})
        time.sleep(0.005)  # lascia spazio all'altro turno
        return super().chat(messages, tag=tag, role=role, model=model, **kwargs)

    def _chat(self, messages, **kwargs):
        return {"content": "ok", "reasoning_content": "", "metrics": {}}

    def health(self) -> bool:
        return True

    def list_models(self) -> List[str]:
        return [self.default_model]


class _State(TypedDict, total=False):
    task: str
    thread_id: str
    model: Optional[str]
    final_response: str
    mode: str


def _graph(barrier: threading.Barrier):
    """Un grafo vero (LangGraph) con le chiamate interne che un turno fa oggi, intervallate con l'altro turno."""

    def route(state):
        barrier.wait()
        mode_router._ask_router_model("sistema", state["task"], state.get("model"), PUBLIC_TAG)
        return {}

    def answer(state):
        barrier.wait()
        llm_calls.call_llm(state["task"], tag=PUBLIC_TAG, role=roles.ANSWER, model=state.get("model"))
        return {}

    def tools(state):
        barrier.wait()

        # Come inspect_image: un tool che chiama un modello dentro i thread di execute_tools_parallel
        def execute_tool(tool_name, arguments, allowed, **kw):
            choice = llm_calls.choose_provider(None, PUBLIC_TAG, providers.get_provider())
            return choice.provider.chat([{"role": "user", "content": f"{tool_name} {state['task']}"}], tag=PUBLIC_TAG,
                                        role=roles.VISION)

        fake_manager = type("M", (), {"execute_tool": staticmethod(execute_tool)})()
        ToolRegistryManager.execute_tools_parallel(fake_manager, [{"tool_name": "a"}, {"tool_name": "b"}], [])
        return {"final_response": f"fatto: {state['task']}", "mode": "chat"}

    builder = StateGraph(_State)
    builder.add_node("route", route)
    builder.add_node("answer", answer)
    builder.add_node("tools", tools)
    builder.add_edge(START, "route")
    builder.add_edge("route", "answer")
    builder.add_edge("answer", "tools")
    builder.add_edge("tools", END)
    return builder.compile()


@pytest.fixture
def fakes():
    from app.llm import costs
    costs.init_costs_db()  # senza le tabelle dei tetti ogni chiamata ripiegherebbe per `budget`
    calls: List[Dict[str, Any]] = []
    lock = threading.Lock()
    local = FakeProvider("fake-local", Label.PRIVATE, "modello-locale", calls, lock)
    remote = FakeProvider("fake-cloud", Label.PUBLIC, "modello-cloud", calls, lock)
    providers.register_provider(local)
    providers.register_provider(remote)
    return calls


def _finish(sess, timeout=20.0) -> Dict[str, Any]:
    """Aspetta la fine del turno e restituisce la risposta salvata (l'evento `final` può arrivare prima che ci si
    iscriva alla sessione)."""
    deadline = time.time() + timeout
    while time.time() < deadline and sess.is_active():
        time.sleep(0.05)
    assert not sess.is_active(), "il turno non è finito"
    messages = [m for m in thread_store.get_thread_messages(sess.thread_id) if m["sender"] == "assistant"]
    return messages[-1]


def test_two_concurrent_turns_never_swap_provider_or_model(fakes):
    barrier = threading.Barrier(2, timeout=10)
    graph = _graph(barrier)
    threads = {"fake-local": f"t-local-{time.time_ns()}", "fake-cloud": f"t-cloud-{time.time_ns()}"}
    tasks = {"fake-local": "domanda per il locale", "fake-cloud": "domanda per il cloud"}
    with patch.object(agent_runner, "get_app_graph", return_value=graph):
        sessions = {name: agent_runner.start_turn(tasks[name], threads[name], provider=name) for name in threads}
        finals = {name: _finish(sess) for name, sess in sessions.items()}
    # Il titolo si genera in un thread a parte, dopo la risposta
    deadline = time.time() + 10
    while time.time() < deadline and sum(c["role"] == roles.TITLE for c in fakes) < 2:
        time.sleep(0.05)

    for name in threads:
        assert finals[name]["content"] == f"fatto: {tasks[name]}", finals[name]["content"]
    by_role = {}
    for call in fakes:
        by_role.setdefault(call["role"], []).append(call)
    assert {r: len(c) for r, c in by_role.items()} == {roles.ROUTE: 2, roles.ANSWER: 2, roles.VISION: 4, roles.TITLE: 2}
    thread_to_provider = {t: name for name, t in threads.items()}
    model_of = {"fake-local": "modello-locale", "fake-cloud": "modello-cloud"}
    for call in fakes:
        if call["role"] == roles.TITLE:
            # Il thread del titolo non ha la sessione del turno: lo riconosce la richiesta da cui nasce
            expected = next(name for name, task in tasks.items() if task in call["text"])
        else:
            expected = thread_to_provider[call["thread"]]
        assert call["provider"] == expected, call
        assert call["model"] == model_of[expected], call
    for name in threads:
        assert finals[name]["provider"] == name and finals[name]["model"] == model_of[name], finals[name]
        assert thread_store.get_thread_model(threads[name]) == (name, None)
        remove_session(threads[name])


def test_a_parallel_tool_sees_the_provider_of_its_turn():
    seen = []

    def execute_tool(tool_name, arguments, allowed, **kw):
        seen.append(providers.turn_provider_name())
        return None

    fake_manager = type("M", (), {"execute_tool": staticmethod(execute_tool)})()
    with providers.use_provider("fake-cloud"):
        ToolRegistryManager.execute_tools_parallel(fake_manager, [{"tool_name": "a"}, {"tool_name": "b"}], [])
    assert seen == ["fake-cloud", "fake-cloud"]


def test_background_work_uses_the_default_provider(fakes):
    providers.set_provider_settings("fake-local", providers.fallback_provider_name())
    assert providers.get_provider().name == "fake-local"
    with providers.use_provider("fake-cloud"):
        assert providers.get_provider().name == "fake-cloud"
    assert providers.get_provider().name == "fake-local"


def test_the_global_active_provider_is_gone():
    for name in ("_ACTIVE_PROVIDER_NAME", "set_active_provider", "get_active_provider_name", "get_active_model_name"):
        assert not hasattr(providers, name), name
    from app.api.routes import providers as provider_routes
    paths = {(r.path, m) for r in provider_routes.router.routes for m in getattr(r, "methods", ())}
    assert ("/v1/providers", "GET") in paths
    assert ("/v1/providers/default", "PUT") not in paths and ("/v1/providers/active", "POST") not in paths


def test_an_unusable_provider_is_an_error_not_a_silent_switch(fakes):
    with pytest.raises(providers.ProviderUnavailableError) as e:
        providers.get_provider("inesistente")
    assert str(e.value) == "Il provider 'inesistente' non esiste: scegli un altro modello"
    providers.replace_provider("fake-cloud", None, Label.PUBLIC, providers.DISABLED)
    with pytest.raises(providers.ProviderUnavailableError, match="è disattivato"):
        providers.get_provider("fake-cloud")


def test_a_chat_request_naming_an_unusable_provider_gets_409(fakes):
    providers.replace_provider("fake-cloud", None, Label.PUBLIC, providers.DISABLED)
    client = TestClient(api)
    for name, text in (("fake-cloud", "Il provider 'fake-cloud' è disattivato: scegli un altro modello"),
                       ("sparito", "Il provider 'sparito' non esiste: scegli un altro modello")):
        res = client.post("/v1/chat", json={"input": "ciao", "provider": name})
        assert res.status_code == 409
        assert res.json()["detail"] == {"code": "provider_disabled", "message": text}


def test_a_conversation_continues_with_its_saved_pair(fakes):
    thread = f"t-pair-{time.time_ns()}"
    assert agent_runner.turn_selection(thread, None, None) == (providers.default_provider_name(), None)
    thread_store.set_thread_model(thread, "fake-cloud", "modello-cloud")
    assert agent_runner.turn_selection(thread, None, None) == ("fake-cloud", "modello-cloud")
    # Una richiesta che sceglie lei vince sulla coppia salvata
    assert agent_runner.turn_selection(thread, "fake-local", None) == ("fake-local", None)
    assert agent_runner.turn_selection(thread, None, "altro") == (providers.default_provider_name(), "altro")
    assert agent_runner.turn_selection(None, None, None) == (providers.default_provider_name(), None)


def test_old_conversations_read_as_the_default_provider():
    thread = f"t-old-{time.time_ns()}"
    thread_store.save_user_message(thread, "ciao")
    thread_store.save_assistant_message(thread, {"response": "risposta", "model": "m"})
    assert thread_store.get_thread_model(thread) == (providers.default_provider_name(), None)
    messages = thread_store.get_thread_messages(thread)
    assert [m["provider"] for m in messages] == [None, providers.default_provider_name()]


def test_a_saved_answer_keeps_its_provider():
    thread = f"t-saved-{time.time_ns()}"
    thread_store.save_assistant_message(thread, {"response": "r", "model": "m", "provider": "fake-cloud"})
    assert thread_store.get_thread_messages(thread)[0]["provider"] == "fake-cloud"
