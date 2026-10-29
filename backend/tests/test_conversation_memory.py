"""Memoria conversazionale: cronologia da thread_store, riassunto incrementale senza buchi, memoria per modalità."""
import json
from unittest.mock import patch

import pytest

from app.agent.nodes import retrieve_memory
from app.agent.nodes.retrieve_memory import (
    RECENT_KEEP,
    RECENT_MAX,
    conversation_window,
    recent_turns_node,
    retrieve_memory_node,
)
from app.memory import facts, profile, thread_store


@pytest.fixture
def thread():
    thread_id = "conv-test"
    thread_store.init_db()
    thread_store.delete_thread_messages(thread_id)
    profile.init_profile_db()
    profile.save_profile("")
    yield thread_id
    thread_store.delete_thread_messages(thread_id)
    profile.save_profile("")


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


RECALLED = [
    {"content": "fatto di questo thread", "score": 0.9, "thread_id": "conv-test", "created_at": "2026-10-01T10:00:00+00:00"},
    {"content": "Il NAS ha IP 192.168.1.20", "score": 0.8, "thread_id": "altro", "created_at": "2026-08-12T10:00:00+00:00"},
]


def test_router_sees_only_the_last_messages_and_the_previous_mode(thread):
    _exchanges(thread, 3)
    thread_store.save_user_message(thread, "domanda corrente", user_msg_id="u-now")
    with patch.object(retrieve_memory, "_update_summary") as summarize:
        state = recent_turns_node({"thread_id": thread, "task": "domanda corrente"})
    summarize.assert_not_called()
    assert state["routing_context"] == "User: domanda 1\nAssistant: risposta 1\nUser: domanda 2\nAssistant: risposta 2"
    assert (state["previous_mode"], state["last_tool_used"]) == ("ask", "web_search")


def test_ask_memory_has_profile_conversation_and_dated_facts_in_stable_order(thread):
    _exchanges(thread, 2)
    thread_store.save_user_message(thread, "domanda corrente", user_msg_id="u-now")
    profile.save_profile("Mi chiamo Dani, uso Debian 12.")
    with patch.object(facts, "search_facts", return_value=RECALLED) as search:
        context = retrieve_memory_node({"thread_id": thread, "task": "domanda corrente", "mode": "ask"})["memory_context"]

    assert search.call_args.kwargs["k"] == 10  # facts_k di ask, raddoppiato per scartare i fatti del thread
    assert "domanda corrente" not in context and "fatto di questo thread" not in context
    assert "- [2026-08-12] Il NAS ha IP 192.168.1.20" in context and "verificali" not in context
    order = [context.index(s) for s in ("Mi chiamo Dani", "User: domanda 0", "Il NAS ha IP")]
    assert order == sorted(order)


def test_chat_memory_is_a_small_window_without_facts(thread):
    for i in range(8):
        thread_store.save_user_message(thread, f"domanda {i} " + "x" * 1200, user_msg_id=f"u{i}")
    with patch.object(facts, "search_facts") as search:
        context = retrieve_memory_node({"thread_id": thread, "task": "ciao", "mode": "chat"})["memory_context"]
    search.assert_not_called()
    assert "domanda 7" in context and "domanda 2" not in context  # ~300 token a messaggio, budget 1500


def test_act_facts_are_marked_to_verify(thread):
    with patch.object(facts, "search_facts", return_value=RECALLED):
        context = retrieve_memory_node({"thread_id": thread, "task": "riavvia il NAS", "mode": "act"})["memory_context"]
    assert "verificali con i tool prima di agire" in context


def test_incognito_skips_memory():
    assert recent_turns_node({"thread_id": "x", "task": "ciao", "incognito": True}) == {"routing_context": None}
    assert retrieve_memory_node({"thread_id": "x", "task": "ciao", "incognito": True}) == {"memory_context": None}


def test_profile_api_roundtrip(thread):
    from fastapi.testclient import TestClient

    from app.api.main import api

    client = TestClient(api)
    assert client.get("/v1/memory/profile").json()["content"] == ""
    saved = client.put("/v1/memory/profile", json={"content": "  Preferisco Debian.  "}).json()
    assert saved["content"] == "Preferisco Debian." and saved["updated_at"]
    assert client.put("/v1/memory/profile", json={"content": "x" * (profile.MAX_CHARS + 1)}).status_code == 422


def test_thread_detail_has_no_external_memory_fields(thread):
    from fastapi.testclient import TestClient

    from app.api.main import api

    _exchanges(thread, 1)
    body = TestClient(api).get(f"/v1/threads/{thread}").json()
    assert [m["content"] for m in body["messages"]] == ["domanda 0", "risposta 0"]
    assert not {"agent_id", "letta_messages"} & set(body)
    assert json.dumps(body)  # serializzabile
