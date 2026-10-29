"""Ricerca per parole e ibrida, tool search_conversations ed episodi di esecuzione, su un database temporaneo."""
from unittest.mock import patch

import pytest

from app.agent.nodes import respond
from app.agent.nodes.retrieve_memory import retrieve_memory_node
from app.evals.suites import memory_sandbox
from app.memory import episodes, facts, hybrid_search, thread_store, vector_store
from app.registry.memory import MemoryRegistry


@pytest.fixture
def sandbox():
    with memory_sandbox():
        yield


def _fts_rows(table):
    conn = vector_store._get_conn()
    try:
        return conn.execute(f"SELECT content FROM {table}").fetchall()
    finally:
        conn.close()


def test_fts_query_keeps_meaningful_words():
    assert hybrid_search.fts_query("Che distribuzione uso di solito per i nuovi container?") == 'distri* OR "nuovi" OR contai*'
    assert hybrid_search.fts_query("Qual è l'IP 192.168.1.250 del CT 150?") == '"192 168 1 250" OR "150"'
    assert hybrid_search.fts_query("che cosa è?") == ""


def test_keyword_match_recovers_a_fact_below_the_similarity_threshold(sandbox):
    facts.add_fact("L'utente preferisce utilizzare Debian 12 per i nuovi container e non Ubuntu.")
    facts.add_fact("Il NAS fa i backup alle 3:30.")
    question = "Che distribuzione uso di solito per i nuovi container?"

    assert vector_store.search_memory(question, k=5, kind="fact")[0]["score"] < 0.9
    hits = facts.search_facts(question, k=5, min_score=0.9)  # il vettoriale da solo non lo troverebbe
    assert [h["content"] for h in hits] == ["L'utente preferisce utilizzare Debian 12 per i nuovi container e non Ubuntu."]
    assert 0 < hits[0]["score"] < 0.9  # il punteggio resta il coseno


def test_memory_index_follows_inserts_updates_and_deletes(sandbox):
    fact_id, _ = facts.add_fact("Jellyfin gira sul CT 133")
    facts.update_fact(fact_id, "Jellyfin gira sul CT 140", [])
    assert _fts_rows("memory_fts") == [("Jellyfin gira sul CT 140",)]
    facts.delete_fact(fact_id)
    assert _fts_rows("memory_fts") == []


def test_message_index_has_the_active_version_and_no_errors(sandbox):
    thread_store.save_user_message("t1", "Come configuro il certificato di nginx?", user_msg_id="u1")
    versions = [{"content": "Usa certbot standalone."}, {"content": "Usa certbot con il plugin nginx sul CT 125."}]
    thread_store.save_assistant_message("t1", {"response": "Usa certbot standalone.", "mode": "ask"}, ast_msg_id="a1", versions=versions, version_index=1)
    thread_store.save_assistant_message("t1", {"response": "[Errore certbot]", "error": True}, ast_msg_id="a2")
    thread_store.save_user_message("t1", "Come configuro il certificato di nginx?", user_msg_id="u1")  # INSERT OR REPLACE

    results = MemoryRegistry().execute_tool("search_conversations", {"query": "certbot nginx"})["results"]
    assert [(r["message_id"], r["role"]) for r in results] == [("a1", "assistant"), ("u1", "user")]
    assert results[0]["excerpt"] == "Usa «certbot» con il plugin «nginx» sul CT 125." and results[0]["thread_title"] == "t1"
    assert len(_fts_rows("message_fts")) == 2

    thread_store.delete_thread_messages("t1")
    assert MemoryRegistry().execute_tool("search_conversations", {"query": "certbot"})["results"] == []


def test_indexes_are_backfilled_when_created(sandbox):
    thread_store.save_user_message("t1", "Il router si chiama Orione", user_msg_id="u1")
    conn = vector_store._get_conn()
    conn.executescript("DROP TABLE message_fts; DROP TRIGGER message_fts_insert; DROP TRIGGER message_fts_update; DROP TRIGGER message_fts_delete;")
    conn.close()
    hybrid_search.init_search_indexes()
    assert [r["message_id"] for r in hybrid_search.search_messages("Orione")] == ["u1"]


TRACE = [
    {"tool_name": "get_container_status", "args": {"vmid": 130}, "result": {"status": "stopped"}},
    {"tool_name": "exec_lxc_command", "args": {"vmid": 130, "command": "systemctl restart immich"}, "error": "Unit immich.service not found"},
    {"tool_name": "exec_lxc_command", "args": {"vmid": 130, "command": "systemctl restart immich"}, "duplicate_blocked": True},
]


def test_episode_describes_tools_errors_and_outcome():
    text = episodes.describe("Riavvia Immich sul CT 130", TRACE)
    assert text.startswith("Richiesta: «Riavvia Immich sul CT 130» → get_container_status")
    assert "exec_lxc_command" in text and "✗ Unit immich.service not found" in text
    assert text.endswith("esito: fallito") and text.count("exec_lxc_command") == 1
    assert episodes.describe("ciao", [{"tool_name": "x", "duplicate_blocked": True}]) is None
    assert episodes.remember_episode("Riavvia", "act", [{"tool_name": "exec_lxc_command", "approval_required": True}], "t") is None


def test_act_turn_saves_an_episode_and_later_act_turns_see_it(sandbox):
    with patch.object(respond, "remember_turn", return_value=0):
        respond.respond_node({"thread_id": "t1", "task": "Riavvia Immich sul CT 130", "mode": "act",
                              "execution_trace": TRACE, "final_response": "Non riuscito"})
        respond.respond_node({"thread_id": "t1", "task": "Che ore sono?", "mode": "chat", "final_response": "Le 10"})
    assert vector_store.count_memory("episode") == 1

    act = retrieve_memory_node({"thread_id": "t2", "task": "Riavvia Immich sul CT 130", "mode": "act"})["memory_context"]
    assert "### Esecuzioni simili passate" in act and "Unit immich.service not found" in act
    ask = retrieve_memory_node({"thread_id": "t2", "task": "Riavvia Immich sul CT 130", "mode": "ask"})["memory_context"]
    assert "Esecuzioni simili" not in ask
    assert facts.search_facts("Riavvia Immich", k=5) == []  # gli episodi non sono fatti


def test_episodes_api_lists_searches_and_deletes(sandbox):
    from fastapi.testclient import TestClient

    from app.api.main import api

    episode_id = episodes.remember_episode("Riavvia Immich sul CT 130", "act", TRACE, "t1")
    client = TestClient(api)
    body = client.get("/v1/memory/episodes").json()
    assert body["total"] == 1
    episode = body["episodes"][0]
    assert (episode["id"], episode["mode"], episode["outcome"], episode["thread_id"]) == (episode_id, "act", "fallito", "t1")
    assert [s["tool"] for s in episode["steps"]] == ["get_container_status", "exec_lxc_command"]
    assert episode["steps"][1]["error"] == "Unit immich.service not found"
    assert client.get("/v1/memory/episodes", params={"query": "riavvio immich"}).json()["episodes"][0]["score"] > 0
    assert client.get("/v1/memory/stats").json()["episodes"] == 1

    assert client.delete(f"/v1/memory/facts/{episode_id}").status_code == 404  # un episodio non è un fatto
    assert client.delete(f"/v1/memory/episodes/{episode_id}").status_code == 204
    assert client.delete(f"/v1/memory/episodes/{episode_id}").status_code == 404
    episodes.remember_episode("Riavvia Immich", "act", TRACE, "t1")
    assert client.delete("/v1/memory/episodes").json() == {"deleted": 1}
