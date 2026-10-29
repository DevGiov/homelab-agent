"""Memoria a lungo termine: fatti con entità, relazioni, estrazione a fine turno, tool di recall e API dell'explorer."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.agent import fact_extraction
from app.agent.fact_extraction import EntityTagging, ExtractedEntity, ExtractedFact, FactExtraction, TaggedFact
from app.llm.providers import LLMUnavailableError
from app.memory import facts, vector_store
from app.registry.memory import MemoryRegistry

STRUCTURED = "app.agent.llm_calls.call_llm_structured"


@pytest.fixture(autouse=True)
def clean_memory():
    vector_store.clear_all_memories()
    facts.clear_facts()
    yield


@pytest.fixture
def api():
    from app.api.main import api as app

    return TestClient(app)


def ent(name, etype="other"):
    return {"name": name, "type": etype}


def entity_named(name):
    return next(e for e in facts.list_entities() if e["name"] == name)


# --- Fatti ed entità ---


def test_fact_with_entities_and_relations():
    debian, _ = facts.add_fact("Il CT 125 usa Debian 12 come sistema operativo", entities=[ent("CT 125", "infrastructure"), ent("Debian", "software")])
    facts.add_fact("Il backend dell'agente gira nel CT 125 con Docker", entities=[ent("ct 125 "), ent("Docker", "software")])
    facts.add_fact("Mario Rossi gestisce il cluster Proxmox di casa", entities=[ent("Mario Rossi", "person")])

    ct = entity_named("CT 125")
    # Stesso nome normalizzato: un'unica entità, il tipo specifico resta
    assert (ct["type"], ct["fact_count"]) == ("infrastructure", 2)
    related = {r["name"]: r["shared"] for r in facts.get_entity(ct["id"])["related"]}
    assert related == {"Debian": 1, "Docker": 1}

    listed, total = facts.list_facts(entity_id=ct["id"])
    assert total == 2 and {e["name"] for e in listed[-1]["entities"]} == {"CT 125", "Debian"}
    assert listed[-1]["id"] == debian


def test_near_duplicate_is_not_saved_twice_but_gets_new_entities():
    first, created = facts.add_fact("L'utente preferisce Debian per i container LXC")
    again, created_again = facts.add_fact("L'utente preferisce Debian per i container LXC.", entities=[ent("Debian", "software")])
    assert created and not created_again and again == first
    assert facts.stats()["facts"] == 1
    assert [e["name"] for e in facts.get_fact(first)["entities"]] == ["Debian"]


def test_update_fact_reembeds_and_replaces_entities():
    fact_id, _ = facts.add_fact("Il gateway di casa ha IP 192.168.1.1", entities=[ent("gateway", "infrastructure")])
    updated = facts.update_fact(fact_id, "La stampante Brother ha IP 192.168.1.50", [ent("Brother", "organization")])

    assert updated["content"] == "La stampante Brother ha IP 192.168.1.50"
    assert [e["name"] for e in updated["entities"]] == ["Brother"]
    assert [e["name"] for e in facts.list_entities()] == ["Brother"]  # 'gateway' orfana eliminata
    assert facts.search_facts("che IP ha la stampante?", k=1)[0]["id"] == fact_id


def test_entity_rename_conflict_merge_and_delete():
    facts.add_fact("Immich conserva le foto di famiglia", entities=[ent("Immich", "software")])
    facts.add_fact("Il servizio immich-server gira su CT 130", entities=[ent("immich-server", "software"), ent("CT 130", "infrastructure")])
    immich, server = entity_named("Immich"), entity_named("immich-server")

    with pytest.raises(facts.EntityConflictError):
        facts.update_entity(server["id"], "IMMICH", "software")
    merged = facts.merge_entities(server["id"], immich["id"])
    assert merged["fact_count"] == 2 and [r["name"] for r in merged["related"]] == ["CT 130"]

    assert facts.delete_entity(immich["id"])
    assert facts.stats()["facts"] == 2  # i fatti restano
    assert [e["name"] for e in facts.list_entities()] == ["CT 130"]


def test_search_is_not_crowded_out_by_documents():
    for i in range(30):
        vector_store.add_memory(f"Capitolo {i} del manuale sulla configurazione di Debian e dei container", kind="kb")
    fact_id, _ = facts.add_fact("L'utente usa Debian sui container")
    assert [f["id"] for f in facts.search_facts("Debian container", k=3)] == [fact_id]


# --- Estrazione a fine turno ---


def extraction(*items):
    return FactExtraction(facts=[ExtractedFact(text=t, entities=[ExtractedEntity(name=n, type=k) for n, k in es]) for t, es in items])


def test_remember_turn_saves_facts_with_entities():
    result = extraction(
        ("Il NAS Synology ha IP 192.168.1.20", [("Synology", "organization"), ("NAS", "infrastructure")]),
        ("L'utente preferisce risposte brevi", []),
        ("ok", []),
    )
    with patch(STRUCTURED, return_value=result) as llm:
        created = fact_extraction.remember_turn("Che IP ha il NAS?", "Il NAS ha IP 192.168.1.20", "", "thread-m1")
    assert created == 2
    assert llm.call_args.kwargs["reasoning_budget"] == 0
    stats = facts.stats()
    # Il fatto senza entità è già stato analizzato: non resta in coda per l'etichettatura
    assert (stats["facts"], stats["entities"], stats["facts_without_entities"]) == (2, 2, 0)
    assert {f["source"] for f in facts.list_facts()[0]} == {"conversation"}


def test_extraction_tolerates_llm_unavailable():
    with patch(STRUCTURED, side_effect=LLMUnavailableError("timeout")):
        assert fact_extraction.remember_turn("domanda", "risposta", "", "t") == 0


def test_tag_untagged_facts_in_batches():
    ids = [facts.add_fact(text)[0] for text in (
        "Luca lavora al progetto Odysseus",
        "La sauna va accesa alle 18",
        "Il router Fritz!Box è in soggiorno",
    )]

    def tagging(prompt, *args, **kwargs):
        # Il modello salta il terzo fatto: resta in coda
        return EntityTagging(facts=[
            TaggedFact(id=ids[0], entities=[ExtractedEntity(name="Luca", type="person"), ExtractedEntity(name="Odysseus", type="project")]),
            TaggedFact(id=ids[1], entities=[]),
        ])

    with patch(STRUCTURED, side_effect=tagging):
        result = fact_extraction.tag_untagged_facts()
    assert result == {"processed": 3, "tagged": 1, "remaining": 1}
    assert [f["content"] for f in facts.facts_without_entities(10)] == ["Il router Fritz!Box è in soggiorno"]


# --- Tool dell'agente ---


def test_recall_memory_tool_returns_facts_with_entities():
    facts.add_fact("Il backup notturno di Proxmox parte alle 2:00", thread_id="t-old", entities=[ent("Proxmox", "software")])
    res = MemoryRegistry().execute_tool("recall_memory", {"query": "a che ora parte il backup?"})
    assert res["results"][0]["fact"].startswith("Il backup notturno")
    assert res["results"][0]["entities"] == ["Proxmox"]
    assert MemoryRegistry().execute_tool("recall_memory", {"query": "ricetta della carbonara"})["results"] == []


# --- API ---


def test_facts_api_crud(api):
    res = api.post("/v1/memory/facts", json={"content": "Il server di Minecraft gira su Purpur", "entities": [ent("Minecraft", "software")]})
    assert res.status_code == 201
    fact = res.json()
    assert api.post("/v1/memory/facts", json={"content": "Il server di Minecraft gira su Purpur"}).status_code == 409

    res = api.put(f"/v1/memory/facts/{fact['id']}", json={"content": "Il server di Minecraft gira su Purpur 1.21", "entities": [ent("Purpur", "software")]})
    assert [e["name"] for e in res.json()["entities"]] == ["Purpur"]

    listed = api.get("/v1/memory/facts").json()
    assert listed["total"] == 1
    found = api.get("/v1/memory/facts", params={"query": "videogioco a blocchi"}).json()["facts"]
    assert found[0]["id"] == fact["id"] and "score" in found[0]
    # I fatti poco simili non compaiono tra i risultati
    assert api.get("/v1/memory/facts", params={"query": "ricetta della carbonara"}).json()["facts"] == []

    assert api.delete(f"/v1/memory/facts/{fact['id']}").status_code == 204
    assert api.delete(f"/v1/memory/facts/{fact['id']}").status_code == 404
    assert api.get("/v1/memory/stats").json() == {"facts": 0, "threads": 0, "entities": 0, "facts_without_entities": 0, "episodes": 0, "procedures_proposed": 0}


def test_entities_api(api):
    api.post("/v1/memory/facts", json={"content": "Giulia cura il giardino", "entities": [ent("Giulia", "person")]})
    api.post("/v1/memory/facts", json={"content": "Giulia e Marco vanno in montagna a gennaio", "entities": [ent("giulia"), ent("Marco", "person")]})
    entities = api.get("/v1/memory/entities").json()
    assert [(e["name"], e["fact_count"]) for e in entities] == [("Giulia", 2), ("Marco", 1)]
    giulia, marco = entities[0]["id"], entities[1]["id"]

    assert api.get(f"/v1/memory/entities/{giulia}").json()["related"][0]["name"] == "Marco"
    assert api.get("/v1/memory/entities", params={"type": "person", "query": "mar"}).json()[0]["name"] == "Marco"
    assert api.put(f"/v1/memory/entities/{marco}", json={"name": "GIULIA", "type": "person"}).status_code == 409
    assert api.put(f"/v1/memory/entities/{marco}", json={"name": "Marco Bianchi", "type": "person"}).json()["name"] == "Marco Bianchi"
    assert api.post(f"/v1/memory/entities/{marco}/merge", json={"into": giulia}).json()["fact_count"] == 2
    assert api.delete(f"/v1/memory/entities/{giulia}").status_code == 204
    assert api.get(f"/v1/memory/entities/{giulia}").status_code == 404
    assert api.get("/v1/memory/facts").json()["total"] == 2


def test_extract_entities_api(api):
    api.post("/v1/memory/facts", json={"content": "Paolo ripara la caldaia Viessmann"})
    fact_id = api.get("/v1/memory/facts").json()["facts"][0]["id"]
    tagging = EntityTagging(facts=[TaggedFact(id=fact_id, entities=[ExtractedEntity(name="Viessmann", type="organization")])])
    with patch(STRUCTURED, return_value=tagging):
        assert api.post("/v1/memory/entities/extract").json() == {"processed": 1, "tagged": 1, "remaining": 0}


def test_incognito_chat_does_not_save_facts(api):
    with patch("app.agent.llm_calls.call_llm") as mock_llm, patch(STRUCTURED) as structured:
        mock_llm.return_value = {"content": "Risposta di test in incognito", "reasoning_content": ""}
        res = api.post("/v1/chat", json={"input": "Messaggio di prova in incognito", "thread_id": "thread_incognito_test", "incognito": True, "force_mode": "chat"})
        assert res.status_code == 200
    structured.assert_not_called()
    assert api.get("/v1/memory/stats").json()["facts"] == 0
