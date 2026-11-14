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
        thread_store.save_assistant_message(thread, {"response": assistant, "mode": "chat", "sensitivity": {"label": "public"}},
                                             ast_msg_id=f"{thread}-a{i}")
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


def test_facts_differing_only_in_identifiers_are_not_duplicates(sandbox):
    old, _ = facts.add_fact("Pi-hole ha l'IP 192.168.1.53")
    new, created = facts.add_fact("Pi-hole ha l'IP 192.168.1.250")
    assert created and new != old
    assert facts.add_fact("Pi-hole ha l'IP 192.168.1.53.") == (old, False)  # stessa cosa: resta un doppione


def test_an_update_creates_the_new_fact_even_if_it_looks_like_the_old_one(sandbox):
    old, _ = facts.add_fact("Pi-hole ha l'IP 192.168.1.53")
    _say("b", "2026-10-01", ("Ho cambiato l'IP di Pi-hole: ora è 192.168.1.250.", "Ricevuto."))

    def propose(messages, related, model=None):  # il fatto vecchio è privato: lo vede solo la lettura a quel livello
        if old not in [f["id"] for f in related]:
            return []
        return [FactOperation(op="update", message=1, fact="Pi-hole ha l'IP 192.168.1.250", replaces=old)]

    with patch.object(mc, "propose_operations", side_effect=propose):
        assert mc.consolidate_messages()["updated"] == 1
    assert [f["content"] for f in facts.list_facts()[0]] == ["Pi-hole ha l'IP 192.168.1.250"]


def test_settings_are_saved_and_validated(sandbox):
    from app.api.main import api

    client = TestClient(api)
    assert client.get("/v1/memory/consolidation").json()["settings"] == {"enabled": True, "time": "03:00", "timezone": "Europe/Rome", "model": None}
    saved = client.put("/v1/memory/consolidation/settings", json={"enabled": True, "time": "22:30", "timezone": "Europe/Rome", "model": "loaded"})
    assert saved.status_code == 200 and mc.get_settings().time == "22:30" and mc.get_settings().model == "loaded"
    assert client.get("/v1/memory/consolidation").json()["next_run"].endswith("22:30+01:00")
    for bad in ({"time": "25:00"}, {"timezone": "Marte/Olympus"}):
        assert client.put("/v1/memory/consolidation/settings", json=bad).status_code == 422


def test_schedule_runs_once_a_day_within_an_hour_of_the_time():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    rome = ZoneInfo("Europe/Rome")
    config = mc.ConsolidationSettings(time="22:30", timezone="Europe/Rome")
    at = lambda h, m: datetime(2026, 10, 31, h, m, tzinfo=rome)  # noqa: E731
    assert not mc.is_due(at(22, 29), config, None)
    assert mc.is_due(at(22, 30), config, None)
    # L'orario è nel fuso delle impostazioni anche se il server è in UTC
    assert mc.is_due(datetime(2026, 10, 31, 21, 45, tzinfo=ZoneInfo("UTC")), config, None)
    assert not mc.is_due(at(23, 31), config, None)  # finestra di un'ora: un backend spento non recupera dopo
    assert not mc.is_due(at(22, 40), config, "2026-10-31")
    assert not mc.is_due(at(22, 40), config.model_copy(update={"enabled": False}), None)
    assert mc.next_scheduled(at(23, 0), config) == datetime(2026, 11, 1, 22, 30, tzinfo=rome)


@pytest.mark.parametrize("body, saved, expected", [
    ({}, "loaded", "Qwen3.6-35B"),                         # senza scelta: quella delle impostazioni
    ({"model": "LFM2.5-24B-A2B-Fast"}, "loaded", "LFM2.5-24B-A2B-Fast"),
    ({"model": None}, "loaded", None),                       # null esplicito: il default del server
])
def test_manual_run_uses_the_requested_or_saved_model(sandbox, body, saved, expected):
    from app.api.main import api

    mc.save_settings(mc.ConsolidationSettings(model=saved))
    with patch.object(mc, "run_in_background", return_value=True) as start:
        assert TestClient(api).post("/v1/memory/consolidation", json=body).status_code == 202
    chosen = start.call_args.args[0]
    with patch("app.agent.memory_consolidation.resolve_model", side_effect=lambda m: "Qwen3.6-35B" if m == "loaded" else m), \
            patch.object(mc.get_provider(), "default_model", "modello-predefinito"):
        with patch.object(mc, "consolidate_messages", return_value={"messages": 0}) as consolidate, patch.object(mc, "deduplicate", return_value=0):
            result = mc.run(chosen)
    assert consolidate.call_args.args[0] == expected
    assert result["model"] == (expected or "modello-predefinito")


# --- Etichetta dei fatti per provenienza (decisione del 14/11/2026) ---

def _say_labeled(thread, user, user_label, assistant, assistant_label):
    thread_store.save_user_message(thread, user, user_msg_id=f"{thread}-u", sensitivity=user_label)
    thread_store.save_assistant_message(thread, {"response": assistant, "mode": "ask",
                                                 "sensitivity": {"label": assistant_label}}, ast_msg_id=f"{thread}-a")


def _labels():
    return {f["content"]: f["sensitivity"] for f in facts.list_facts()[0]}


def _reader(by_level):
    """Finto modello del consolidamento: `by_level(messages, related)` → operazioni; registra cosa ha visto ogni lettura."""
    seen = []

    def propose(messages, related, model=None):
        seen.append(([m["content"] for m in messages], [f["content"] for f in related]))
        return by_level(messages, related)

    return propose, seen


def test_a_block_is_read_level_by_level_and_a_fact_takes_the_label_of_what_was_read(sandbox):
    # La risposta è privata perché il turno aveva memoria privata: ciò che riporta resta privato
    _say_labeled("p1", "Uso Linux per giocare.", "public", "Il tuo NAS ha 4 dischi da 8 TB.", "private")

    def by_level(messages, related):
        if len(messages) == 1:
            return [FactOperation(op="add", message=1, fact="L'utente gioca su Linux")]
        # Chi ha letto la risposta privata scrive privato, qualunque messaggio indichi
        return [FactOperation(op="add", message=1, fact="Il NAS dell'utente ha 4 dischi da 8 TB"),
                FactOperation(op="add", message=99, fact="Numero di messaggio fuori dal blocco")]

    propose, seen = _reader(by_level)
    with patch.object(mc, "propose_operations", side_effect=propose):
        assert mc.consolidate_messages() == {"messages": 2, "added": 3, "updated": 0, "invalidated": 0}
    assert _labels() == {"L'utente gioca su Linux": "public", "Il NAS dell'utente ha 4 dischi da 8 TB": "private",
                         "Numero di messaggio fuori dal blocco": "private"}
    # Prima i soli messaggi pubblici, poi tutto, con il fatto appena scritto mostrato come già in memoria
    assert seen == [(["Uso Linux per giocare."], []),
                    (["Uso Linux per giocare.", "Il tuo NAS ha 4 dischi da 8 TB."], ["L'utente gioca su Linux"])]


def test_a_private_fact_is_not_shown_to_the_public_reading_and_what_quotes_it_stays_private(sandbox):
    """Il caso della revisione del 14/11: un fatto privato mostrato al modello e ripetuto in un fatto nuovo attribuito
    al messaggio pubblico dell'utente."""
    facts.add_fact("Il codice cliente dell'utente presso il fornitore di energia è 4458812", entities=[],
                   entities_checked=True, sensitivity="private")
    _say_labeled("p7", "Ho cambiato fornitore di energia: ora sono con Enel.", "public", "Annotato.", "public")

    def by_level(messages, related):
        if not related:
            return [FactOperation(op="add", message=1, fact="L'utente ha Enel come fornitore di energia")]
        return [FactOperation(op="add", message=1, fact="L'utente è cliente Enel con il codice 4458812")]

    propose, seen = _reader(by_level)
    with patch.object(mc, "propose_operations", side_effect=propose):
        mc.consolidate_messages()
    assert seen[0][1] == [] and "Il codice cliente dell'utente presso il fornitore di energia è 4458812" in seen[1][1]
    labels = _labels()
    assert labels["L'utente ha Enel come fornitore di energia"] == "public"
    assert labels["L'utente è cliente Enel con il codice 4458812"] == "private"


def test_the_facts_shown_to_a_reading_are_found_with_the_messages_it_sees(sandbox):
    """Anche la scelta dei fatti da mostrare dice qualcosa dei messaggi: un fatto pubblico che somiglia solo al
    messaggio privato non arriva alla lettura pubblica."""
    facts.add_fact("Il gatto dell'utente si chiama Micio", entities=[], entities_checked=True, sensitivity="public")
    thread_store.save_user_message("p12", "Uso Linux per giocare.", user_msg_id="p12-u0", sensitivity="public")
    thread_store.save_assistant_message("p12", {"response": "Ok.", "sensitivity": {"label": "public"}}, ast_msg_id="p12-a0")
    thread_store.save_user_message("p12", "Il mio gatto Micio deve andare dal veterinario.", user_msg_id="p12-u1", sensitivity="private")
    thread_store.save_assistant_message("p12", {"response": "Segnato.", "sensitivity": {"label": "private"}}, ast_msg_id="p12-a1")
    propose, seen = _reader(lambda messages, related: [])
    with patch.object(mc, "propose_operations", side_effect=propose):
        mc.consolidate_messages()
    assert [len(messages) for messages, _ in seen] == [2, 4]
    assert seen[0][1] == [] and seen[1][1] == ["Il gatto dell'utente si chiama Micio"]


def test_a_block_at_one_level_with_nothing_higher_in_memory_is_read_once(sandbox):
    facts.add_fact("L'utente usa Arch Linux", entities=[], entities_checked=True, sensitivity="public")
    _say_labeled("p8", "Uso Arch Linux anche sul portatile.", "public", "Ok.", "public")
    propose, seen = _reader(lambda messages, related: [])
    with patch.object(mc, "propose_operations", side_effect=propose):
        mc.consolidate_messages()
    assert len(seen) == 1 and seen[0][1] == ["L'utente usa Arch Linux"]


def test_a_reading_that_fails_leaves_the_whole_block_for_the_next_run(sandbox):
    _say_labeled("p9", "Uso Linux per giocare.", "public", "Il tuo NAS ha 4 dischi da 8 TB.", "private")
    propose, seen = _reader(lambda messages, related: [] if len(messages) == 1 else None)
    with patch.object(mc, "propose_operations", side_effect=propose):
        assert mc.consolidate_messages()["messages"] == 0
    assert len(seen) == 2 and mc.pending() == {"messages": 2, "threads": 1}


def test_answers_alone_are_not_read_below_their_question(sandbox):
    # Domanda privata (conversazione privata), risposta pubblica: la risposta da sola non si legge
    _say_labeled("p10", "Il mio IBAN è cambiato.", "private", "Ok.", "public")
    propose, seen = _reader(lambda messages, related: [])
    with patch.object(mc, "propose_operations", side_effect=propose):
        mc.consolidate_messages()
    assert [messages for messages, _ in seen] == [["Il mio IBAN è cambiato.", "Ok."]]


def test_reading_levels():
    from app.security.flows import Label
    public, private = {"role": "user", "sensitivity": "public"}, {"role": "assistant", "sensitivity": "private"}
    internal_fact, private_fact = {"sensitivity": "internal"}, {"metadata": {}}
    assert mc.reading_levels([public], []) == [Label.PUBLIC]
    assert mc.reading_levels([public, private], [private_fact]) == [Label.PUBLIC, Label.PRIVATE]
    assert mc.reading_levels([public], [internal_fact]) == [Label.PUBLIC, Label.INTERNAL]
    assert mc.reading_levels([public], [internal_fact, private_fact]) == [Label.PUBLIC, Label.PRIVATE]
    assert mc.reading_levels([private], [internal_fact]) == [Label.PRIVATE]
    # Un messaggio segreto si legge al livello più alto dei fatti: privato
    assert mc.reading_levels([{"role": "user", "sensitivity": "secret"}], []) == [Label.PRIVATE]


def test_an_answer_saved_without_a_label_counts_as_private(sandbox):
    """Risposte precedenti alle etichette, o salvate da un percorso che non le calcola: non si sa cosa avevano letto."""
    thread_store.save_user_message("p2", "Il mio editor è Neovim.", user_msg_id="p2-u")
    thread_store.save_assistant_message("p2", {"response": "Annotato: usi Neovim sul server 10.0.0.7.", "mode": "chat"}, ast_msg_id="p2-a")

    def by_level(messages, related):
        if len(messages) == 1:
            return [FactOperation(op="add", message=1, fact="L'utente usa Neovim")]
        return [FactOperation(op="add", message=1, fact="Il server dell'utente è 10.0.0.7")]

    propose, _ = _reader(by_level)
    with patch.object(mc, "propose_operations", side_effect=propose):
        mc.consolidate_messages()
    assert _labels() == {"L'utente usa Neovim": "public", "Il server dell'utente è 10.0.0.7": "private"}


def test_an_update_keeps_at_least_the_label_of_the_fact_it_replaces(sandbox):
    old, _ = facts.add_fact("Il router di casa è un Fritz!Box 7590", entities=[], entities_checked=True)  # senza etichetta: privato
    _say_labeled("p3", "Ho cambiato il router con un Fritz!Box 5690.", "public", "Ricevuto.", "public")

    def by_level(messages, related):  # il fatto privato si vede solo alla lettura privata, che lo sostituisce
        if old not in [f["id"] for f in related]:
            return []
        return [FactOperation(op="update", message=1, fact="Il router di casa è un Fritz!Box 5690", replaces=old)]

    propose, seen = _reader(by_level)
    with patch.object(mc, "propose_operations", side_effect=propose):
        assert mc.consolidate_messages()["updated"] == 1
    assert len(seen) == 2 and _labels() == {"Il router di casa è un Fritz!Box 5690": "private"}


def _untrusted_flags():
    return {f["content"]: f["untrusted"] for f in facts.list_facts()[0]}


def test_a_fact_written_after_reading_untrusted_content_carries_the_mark(sandbox):
    """La risposta è stata scritta dopo aver letto una pagina web: ciò che ne viene è un dato, non una cosa detta
    dall'utente. Quello che l'utente ha scritto resta attendibile."""
    thread_store.save_user_message("u1", "Cerco un dissipatore per la mia GPU.", user_msg_id="u1-u", sensitivity="public")
    thread_store.save_assistant_message("u1", {"response": "Secondo il sito il modello X regge 250 W.",
                                               "sensitivity": {"label": "public", "untrusted": True, "reasons": ["untrusted:tool:web_search"]}},
                                        ast_msg_id="u1-a")
    assert [m["untrusted"] for m in thread_store.get_history("u1")] == [False, True]

    with patch.object(mc, "propose_operations", return_value=_ops(
            FactOperation(op="add", message=1, fact="Il dissipatore X regge 250 W"))):
        mc.consolidate_messages()
    assert _untrusted_flags() == {"Il dissipatore X regge 250 W": True}

    # Un fatto che la lettura successiva scrive vedendo quel fatto ne eredita il segno
    thread_store.save_user_message("u2", "Quale dissipatore regge 250 W?", user_msg_id="u2-u", sensitivity="public")
    thread_store.save_assistant_message("u2", {"response": "Ok.", "sensitivity": {"label": "public"}}, ast_msg_id="u2-a")

    def propose(messages, related, model=None):
        assert [f["content"] for f in related] == ["Il dissipatore X regge 250 W"]
        return [FactOperation(op="add", message=1, fact="L'utente vuole un dissipatore da almeno 250 W come il modello X")]

    with patch.object(mc, "propose_operations", side_effect=propose):
        mc.consolidate_messages()
    assert _untrusted_flags()["L'utente vuole un dissipatore da almeno 250 W come il modello X"] is True


def test_what_the_user_wrote_stays_trusted_and_editing_a_fact_clears_the_mark(sandbox):
    thread_store.save_user_message("u3", "Il mio alimentatore è da 850 W.", user_msg_id="u3-u", sensitivity="public")
    thread_store.save_assistant_message("u3", {"response": "Annotato.", "sensitivity": {"label": "public"}}, ast_msg_id="u3-a")
    with patch.object(mc, "propose_operations", return_value=_ops(
            FactOperation(op="add", message=1, fact="L'alimentatore dell'utente è da 850 W"))):
        mc.consolidate_messages()
    assert _untrusted_flags() == {"L'alimentatore dell'utente è da 850 W": False}

    marked, _ = facts.add_fact("Il sito dice che il cavo regge 600 W", entities=[], entities_checked=True, untrusted=True)
    assert facts.get_fact(marked)["untrusted"] is True
    facts.update_fact(marked, "Il cavo dell'utente regge 600 W", [])
    assert facts.get_fact(marked)["untrusted"] is False


def test_personal_data_in_a_fact_makes_it_private(sandbox):
    facts.add_fact("Mario Rossi è il commercialista dell'utente", entities=[{"name": "Mario Rossi", "type": "person"}],
                   entities_checked=True, sensitivity="private")
    _say_labeled("p4", "Scrivo a Mario e a Giulia.", "public", "Ok.", "public")
    with patch.object(mc, "propose_operations", return_value=_ops(
            FactOperation(op="add", message=1, fact="L'email dell'utente per le fatture è fatture@example.org"),
            FactOperation(op="add", message=1, fact="L'utente sente spesso Mario Rossi per le tasse"),
            FactOperation(op="add", message=1, fact="Giulia è la collega che gestisce i turni",
                          entities=[{"name": "Giulia", "type": "person"}]),
            FactOperation(op="add", message=1, fact="L'utente usa Proxmox VE 9 sul server di casa",
                          entities=[{"name": "Proxmox VE", "type": "software"}]))):
        mc.consolidate_messages()
    labels = _labels()
    assert labels["L'email dell'utente per le fatture è fatture@example.org"] == "private"
    assert labels["L'utente sente spesso Mario Rossi per le tasse"] == "private"
    assert labels["Giulia è la collega che gestisce i turni"] == "private"
    assert labels["L'utente usa Proxmox VE 9 sul server di casa"] == "public"


def test_an_identical_fact_keeps_the_label_of_the_existing_one(sandbox):
    """Lo stesso testo di un fatto già in memoria non ne crea uno nuovo: resta quello, con la sua etichetta."""
    facts.add_fact("Il codice cliente dell'utente presso il fornitore di energia è 4458812", entities=[],
                   entities_checked=True, sensitivity="private")
    _say_labeled("p5", "Grazie.", "public", "Il tuo codice cliente è 4458812.", "private")
    with patch.object(mc, "propose_operations", return_value=_ops(
            FactOperation(op="add", message=1, fact="Il codice cliente dell'utente presso il fornitore di energia è 4458812"))):
        mc.consolidate_messages()
    assert _labels() == {"Il codice cliente dell'utente presso il fornitore di energia è 4458812": "private"}


def test_secrets_never_reach_the_memory(sandbox):
    _say_labeled("p6", "La chiave è sk-proj-abcdefghijklmnopqrstuvwx123456", "private", "Ok.", "private")
    with patch.object(mc, "propose_operations", return_value=_ops(
            FactOperation(op="add", message=1, fact="La chiave API dell'utente è sk-proj-abcdefghijklmnopqrstuvwx123456"))):
        mc.consolidate_messages()
    (content,) = _labels()
    assert "sk-proj-" not in content and "[RIMOSSO: segreto]" in content


def test_a_fact_that_carried_a_secret_is_private_even_from_public_messages(sandbox):
    _say_labeled("p11", "Segna la chiave del servizio.", "public", "Fatto.", "public")
    with patch.object(mc, "propose_operations", return_value=_ops(
            FactOperation(op="add", message=1, fact="La chiave del servizio è sk-proj-abcdefghijklmnopqrstuvwx123456"))):
        mc.consolidate_messages()
    ((content, label),) = _labels().items()
    assert "sk-proj-" not in content and label == "private"


def test_fact_label_never_goes_above_private():
    from app.security.flows import Label
    op = FactOperation(op="add", message=1, fact="token ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    tag = mc.fact_label(op, [{"role": "user", "content": "x", "sensitivity": None}], [], [])
    assert tag.label == Label.PRIVATE


def test_add_fact_rejects_an_unknown_label(sandbox):
    with pytest.raises(ValueError):
        facts.add_fact("Fatto qualsiasi", sensitivity="secret")
