"""Consolidamento della memoria: messaggi → fatti datati, sostituzioni e invalidazioni, cursore per thread,
ordine cronologico tra thread, deduplicazione, API."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.agent import memory_consolidation as mc
from app.agent.memory_consolidation import Deduplication, FactOperation, Superseded
from app.evals.suites import memory_sandbox
from app.llm.providers import LLMUnavailableError
from app.memory import facts, thread_store


@pytest.fixture
def sandbox():
    with memory_sandbox():
        yield


def _say(thread, date, *turns):
    import sqlite3

    from app.core.config import settings

    start = len(thread_store.get_history(thread)) // 2
    for i, (user, assistant) in enumerate(turns, start=start):
        thread_store.save_user_message(thread, user, user_msg_id=f"{thread}-u{i}")
        thread_store.save_assistant_message(thread, {"response": assistant, "mode": "chat"}, ast_msg_id=f"{thread}-a{i}")
    with sqlite3.connect(settings.checkpoint_db_path) as conn:
        conn.execute(f"UPDATE thread_messages SET created_at = ? WHERE thread_id = ? AND message_id IN ({','.join('?' * (2 * len(turns)))})",
                     (f"{date} 10:00:00", thread, *[f"{thread}-{k}{i}" for i in range(start, start + len(turns)) for k in "ua"]))


def _ops(*operations):
    return list(operations)


def test_new_messages_become_dated_facts_and_updates_supersede(sandbox):
    _say("a", "2026-08-20", ("Immich gira sul CT 130.", "Annotato."))
    with patch.object(mc, "propose_operations", return_value=_ops(FactOperation(op="add", message=1, fact="Immich gira sul CT 130"))):
        assert mc.consolidate_messages()["added"] == 1
    old = facts.list_facts()[0][0]
    assert old["created_at"].startswith("2026-08-20")

    _say("b", "2026-10-05", ("Ho spostato Immich sul CT 141.", "Ricevuto."))
    seen = {}

    def propose(messages, related, model=None):
        seen["related"] = [f["id"] for f in related]
        return [FactOperation(op="update", message=1, fact="Immich gira sul CT 141", replaces=old["id"])]

    with patch.object(mc, "propose_operations", side_effect=propose):
        assert mc.consolidate_messages() == {"messages": 2, "added": 0, "updated": 1, "invalidated": 0}
    assert seen["related"] == [old["id"]]  # il fatto vecchio era tra quelli mostrati
    valid = facts.list_facts()[0]
    assert [f["content"] for f in valid] == ["Immich gira sul CT 141"]
    history = {f["id"]: f for f in facts.list_facts(include_superseded=True)[0]}
    assert history[old["id"]]["invalid_at"].startswith("2026-10-05") and history[old["id"]]["superseded_by"] == valid[0]["id"]
    assert [f["content"] for f in facts.search_facts("Su che container gira Immich?", min_score=0)] == ["Immich gira sul CT 141"]
    assert facts.stats()["superseded_facts"] == 1


def test_only_shown_facts_can_be_replaced(sandbox):
    stranger, _ = facts.add_fact("La sauna va accesa alle 18")
    _say("a", "2026-09-01", ("Il NAS ha IP 192.168.1.20.", "Ok."))
    operations = _ops(
        FactOperation(op="invalidate", message=1, replaces=stranger),
        FactOperation(op="update", message=1, fact="Il NAS ha IP 192.168.1.20", replaces=stranger),
    )
    with patch.object(mc, "propose_operations", return_value=operations), patch.object(mc, "_related_facts", return_value=[]):
        result = mc.consolidate_messages()
    assert (result["invalidated"], result["updated"], result["added"]) == (0, 0, 1)  # l'update diventa un add
    assert facts.get_fact(stranger)["invalid_at"] is None


def test_invalidate_without_replacement(sandbox):
    kuma, _ = facts.add_fact("Uptime Kuma gira sul CT 145")
    _say("a", "2026-10-03", ("Ho dismesso Uptime Kuma.", "Ricevuto."))
    with patch.object(mc, "propose_operations", return_value=_ops(FactOperation(op="invalidate", message=1, replaces=kuma))):
        assert mc.consolidate_messages()["invalidated"] == 1
    fact = facts.get_fact(kuma)
    assert fact["invalid_at"].startswith("2026-10-03") and fact["superseded_by"] is None
    assert facts.list_facts()[1] == 0


def test_cursor_advances_only_on_success_and_blocks_follow_time_across_threads(sandbox):
    _say("late", "2026-10-01", ("Messaggio di ottobre", "ok"))
    _say("early", "2026-08-01", ("Messaggio di agosto", "ok"))
    order = []

    def propose(messages, related, model=None):
        order.append(messages[0]["content"])
        return []

    with patch.object(mc, "propose_operations", side_effect=propose):
        mc.consolidate_messages()
    assert order == ["Messaggio di agosto", "Messaggio di ottobre"]
    assert mc.pending() == {"messages": 0, "threads": 0}

    _say("late", "2026-10-02", ("Secondo messaggio", "ok"))
    with patch.object(mc, "propose_operations", return_value=None):  # risposta non valida: il blocco resta da fare
        assert mc.consolidate_messages()["messages"] == 0
    assert mc.pending() == {"messages": 2, "threads": 1}
    with patch.object(mc, "propose_operations", side_effect=propose) as again:
        mc.consolidate_messages()
    assert again.call_args.args[0][0]["content"] == "Secondo messaggio"  # solo i messaggi nuovi


def test_run_records_the_result_and_stops_when_the_model_is_down(sandbox):
    _say("a", "2026-09-01", ("Il NAS ha IP 192.168.1.20.", "Ok."))
    with patch.object(mc, "propose_operations", side_effect=LLMUnavailableError("spento")):
        result = mc.run()
    assert "Modello non disponibile" in result["error"]
    status = mc.status()
    assert status["last_result"]["error"] and status["pending"]["messages"] == 2 and not status["running"]


def test_deduplication_asks_once_per_new_fact(sandbox):
    a, _ = facts.add_fact("Il NAS Synology fa i backup di Proxmox alle 3:30")
    b, _ = facts.add_fact("Ogni notte alle 3:30 il NAS Synology esegue i backup di Proxmox")
    with patch("app.agent.llm_calls.call_llm_structured", return_value=Deduplication(superseded=[Superseded(id=a, by=b)])) as llm:
        assert mc.deduplicate() == 1
    assert facts.get_fact(a)["superseded_by"] == b
    with patch("app.agent.llm_calls.call_llm_structured") as llm:
        assert mc.deduplicate() == 0
    llm.assert_not_called()


def test_turns_no_longer_extract_facts(sandbox):
    from app.agent.nodes.respond import respond_node

    with patch("app.agent.llm_calls.call_llm_structured") as llm:
        respond_node({"thread_id": "t", "task": "Il NAS ha IP 192.168.1.20", "mode": "chat", "final_response": "Annotato"})
    llm.assert_not_called()
    assert facts.list_facts()[1] == 0


def test_consolidation_and_restore_api(sandbox):
    from app.api.main import api

    client = TestClient(api)
    old, _ = facts.add_fact("Pi-hole ha IP 192.168.1.53")
    new, _ = facts.add_fact("Pi-hole ha IP 192.168.1.250")
    facts.supersede_fact(old, by=new)
    assert [f["id"] for f in client.get("/v1/memory/facts").json()["facts"]] == [new]
    assert {f["id"] for f in client.get("/v1/memory/facts", params={"include_superseded": True}).json()["facts"]} == {old, new}
    assert client.post(f"/v1/memory/facts/{old}/restore").json()["invalid_at"] is None

    _say("a", "2026-09-01", ("ciao", "ciao"))
    assert client.get("/v1/memory/consolidation").json()["pending"] == {"messages": 2, "threads": 1}
    with patch.object(mc, "run_in_background", return_value=True):
        assert client.post("/v1/memory/consolidation").status_code == 202
    with patch.object(mc, "run_in_background", return_value=False):
        assert client.post("/v1/memory/consolidation").status_code == 409
