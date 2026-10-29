"""Memoria conversazionale: cronologia da thread_store, riassunto incrementale senza buchi, contesto del turno."""
import json
from unittest.mock import patch

import pytest

from app.agent.nodes import retrieve_memory
from app.agent.nodes.retrieve_memory import RECENT_KEEP, RECENT_MAX, conversation_window, retrieve_memory_node
from app.memory import thread_store


@pytest.fixture
def thread():
    thread_id = "conv-test"
    thread_store.init_db()
    thread_store.delete_thread_messages(thread_id)
    yield thread_id
    thread_store.delete_thread_messages(thread_id)


def _exchanges(thread_id, n, start=0):
    for i in range(start, start + n):
        thread_store.save_user_message(thread_id, f"domanda {i}", user_msg_id=f"u{i}")
        thread_store.save_assistant_message(thread_id, {"response": f"risposta {i}", "mode": "ask", "tool_used": "web_search"}, ast_msg_id=f"a{i}")


def test_history_uses_active_version_and_skips_errors(thread):
    thread_store.save_user_message(thread, "prima domanda", user_msg_id="u1")
    versions = [{"content": "risposta vecchia"}, {"content": "risposta rigenerata"}]
    thread_store.save_assistant_message(thread, {"response": "risposta vecchia", "mode": "chat"}, ast_msg_id="a1", versions=versions, version_index=1)
    thread_store.save_assistant_message(thread, {"response": "[Errore durante l'esecuzione]", "error": True}, ast_msg_id="a2")
    thread_store.save_user_message(thread, "   ", user_msg_id="u2", images=["img.png"])

    history = thread_store.get_history(thread)
    assert [(m["role"], m["content"]) for m in history] == [("user", "prima domanda"), ("assistant", "risposta rigenerata")]
    assert history[1]["mode"] == "chat" and history[1]["created_at"]


def test_short_conversation_needs_no_summary(thread):
    _exchanges(thread, 3)
    with patch.object(retrieve_memory, "_update_summary") as summarize:
        summary, window = conversation_window(thread, thread_store.get_history(thread), None)
    summarize.assert_not_called()
    assert summary == "" and len(window) == 6


def test_old_messages_are_folded_into_the_summary_without_gaps(thread):
    _exchanges(thread, 11)  # 22 messaggi > RECENT_MAX
    with patch.object(retrieve_memory, "_update_summary", return_value="riassunto 1") as summarize:
        summary, window = conversation_window(thread, thread_store.get_history(thread), None)
    folded = summarize.call_args.args[1]
    assert len(folded) == 22 - RECENT_KEEP and folded[0]["content"] == "domanda 0"
    assert summary == "riassunto 1" and len(window) == RECENT_KEEP
    assert thread_store.get_summary(thread) == ("riassunto 1", 22 - RECENT_KEEP)

    # I messaggi successivi si aggiungono alla finestra, che riparte da dove arriva il riassunto
    _exchanges(thread, 2, start=11)
    with patch.object(retrieve_memory, "_update_summary") as summarize:
        summary, window = conversation_window(thread, thread_store.get_history(thread), None)
    summarize.assert_not_called()
    assert summary == "riassunto 1" and len(window) == RECENT_KEEP + 4
    assert window[0]["content"] == "domanda 6" and window[-1]["content"] == "risposta 12"

    # Superata di nuovo la soglia, il riassunto precedente viene esteso con i soli messaggi nuovi
    _exchanges(thread, 4, start=13)
    assert len(thread_store.get_history(thread)) - (22 - RECENT_KEEP) > RECENT_MAX
    with patch.object(retrieve_memory, "_update_summary", return_value="riassunto 2") as summarize:
        conversation_window(thread, thread_store.get_history(thread), None)
    assert summarize.call_args.args[0] == "riassunto 1"
    assert summarize.call_args.args[1][0]["content"] == "domanda 6"
    assert thread_store.get_summary(thread) == ("riassunto 2", 34 - RECENT_KEEP)


def test_failed_summary_keeps_coverage_and_trims_the_window(thread):
    _exchanges(thread, 11)
    with patch.object(retrieve_memory, "_update_summary", return_value=""):
        summary, window = conversation_window(thread, thread_store.get_history(thread), None)
    assert summary == "" and len(window) == RECENT_KEEP
    assert thread_store.get_summary(thread) == ("", 0)


def test_summary_is_reset_when_messages_were_deleted(thread):
    thread_store.save_summary(thread, "riassunto di messaggi cancellati", 40)
    _exchanges(thread, 2)
    summary, window = conversation_window(thread, thread_store.get_history(thread), None)
    assert summary == "" and len(window) == 4


def test_deleting_a_thread_removes_its_summary(thread):
    thread_store.save_summary(thread, "riassunto", 10)
    thread_store.delete_thread_messages(thread)
    assert thread_store.get_summary(thread) == ("", 0)


def test_turn_context_excludes_the_current_message(thread):
    _exchanges(thread, 2)
    thread_store.save_user_message(thread, "domanda corrente", user_msg_id="u-now")
    with patch("app.memory.vector_store.search_memory", return_value=[
        {"content": "Il NAS ha IP 192.168.1.20", "score": 0.8, "thread_id": "altro"},
        {"content": "fatto di questo thread", "score": 0.9, "thread_id": thread},
        {"content": "fatto poco pertinente", "score": 0.2, "thread_id": "altro"},
    ]):
        state = retrieve_memory_node({"thread_id": thread, "task": "domanda corrente"})

    context = state["memory_context"]
    assert "domanda corrente" not in context
    assert "User: domanda 1\nAssistant: risposta 1" in context
    assert "- Il NAS ha IP 192.168.1.20" in context
    assert "fatto di questo thread" not in context and "poco pertinente" not in context
    assert (state["previous_mode"], state["last_tool_used"]) == ("ask", "web_search")


def test_incognito_skips_memory():
    assert retrieve_memory_node({"thread_id": "x", "task": "ciao", "incognito": True}) == {"memory_context": None}


def test_thread_detail_has_no_external_memory_fields(thread):
    from fastapi.testclient import TestClient

    from app.api.main import api

    _exchanges(thread, 1)
    body = TestClient(api).get(f"/v1/threads/{thread}").json()
    assert [m["content"] for m in body["messages"]] == ["domanda 0", "risposta 0"]
    assert not {"agent_id", "letta_messages"} & set(body)
    assert json.dumps(body)  # serializzabile
