"""Harness di valutazione dei modelli: casi, giudizi, esecuzione, report e piano strutturato senza ripieghi."""
import json
from unittest.mock import patch

import pytest

from app.evals import runner, suites
from app.evals.suites import (
    Outcome,
    RecallAnswer,
    grade_memory,
    grade_plan,
    grade_recall,
    grade_rollback,
    grade_routing,
    grade_tool,
)
from app.observability import store
from app.observability.turns import capture_llm_calls, record_llm_call

CATALOG = ["proxmox-mcp__list_containers", "proxmox-mcp__get_container_status", "proxmox-mcp__allocate_ip", "calendar_list_events"]


@pytest.mark.parametrize("suite", list(suites.SUITES))
def test_case_files_are_well_formed(suite):
    cases = suites.load_cases(suite)
    ids = [c["id"] for c in cases]
    assert cases and len(ids) == len(set(ids))
    required = {
        "routing": {"input", "expected_mode"},
        "tools": {"input", "expected_tool"},
        "planning": {"input", "required_tools"},
        "rollback": {"task", "steps", "error", "expect_mentions"},
        "memory": {"task", "response", "expect_facts"},
        "recall": {"sessions", "question"},
        "multistep": {"input", "tools", "expect_calls", "expect_answer"},
    }[suite]
    assert all(required <= set(c) for c in cases)
    if suite == "multistep":
        # Ogni chiamata attesa ha un risultato simulato, e le chiamate attese sono più d'una (una catena)
        for c in cases:
            expected = [e for g in c["expect_calls"] for e in (g if isinstance(g, list) else [g])]
            assert len(expected) >= 2 and all(suites._short(e["tool"]) in c["tools"] for e in expected)
    if suite == "recall":
        assert all(c.get("abstain") or c.get("expect_any") or c.get("expect_all") for c in cases)
        assert all({"thread", "date", "turns"} <= set(s) for c in cases for s in c["sessions"])


def test_grade_routing():
    case = {"expected_mode": "ask", "expect_web": True}
    assert grade_routing(case, "ask", True).passed
    assert grade_routing(case, "act", True).detail == "modalità act, attesa ask"
    assert not grade_routing(case, "ask", False).passed


def test_grade_tool():
    case = {"expected_tool": "proxmox-mcp__get_container_status", "expected_args": {"vmid": 125}}
    assert grade_tool(case, ["proxmox-mcp__get_container_status"], {"vmid": "125"}, CATALOG).passed
    # Il prefisso del server può mancare nella scelta del modello
    assert grade_tool(case, ["get_container_status"], {"vmid": 125}, CATALOG).passed
    assert "argomenti errati" in grade_tool(case, ["proxmox-mcp__get_container_status"], {"vmid": 124}, CATALOG).detail
    assert not grade_tool(case, ["proxmox-mcp__list_containers"], {}, CATALOG).passed
    assert grade_tool({"expected_tool": None}, [], {}, CATALOG).passed
    assert not grade_tool({"expected_tool": None}, ["web_search"], {}, CATALOG).passed
    assert grade_tool({"expected_tool": "list_automations"}, [], {}, CATALOG).skipped
    assert grade_tool({"expected_tool": "calendar_check_availability", "accept_tools": ["calendar_list_events"]}, ["calendar_list_events"], {}, CATALOG).passed


def test_grade_plan():
    case = {"required_tools": ["proxmox-mcp__allocate_ip"], "forbidden_tools": ["proxmox-mcp__list_containers"], "max_steps": 2}
    ok = {"steps": [{"tool": "allocate_ip"}, {"tool": "proxmox-mcp__get_container_status"}]}
    assert grade_plan(case, ok, CATALOG).passed
    assert grade_plan(case, None, CATALOG).detail == "nessun piano strutturato valido"
    assert "inesistenti" in grade_plan(case, {"steps": [{"tool": "proxmox-mcp__magic"}]}, CATALOG).detail
    assert "mancanti" in grade_plan(case, {"steps": [{"tool": "proxmox-mcp__get_container_status"}]}, CATALOG).detail
    assert "da evitare" in grade_plan(case, {"steps": [{"tool": "allocate_ip"}, {"tool": "list_containers"}]}, CATALOG).detail
    assert "al massimo" in grade_plan(case, {"steps": [{"tool": "allocate_ip"}] * 3}, CATALOG).detail


def test_grade_rollback():
    case = {"expect_mentions": ["stop_container", "release_ip"], "ordered": True}
    assert grade_rollback(case, "1. Stop container 150 (stop_container)\n2. Rilascia l'IP con release ip").passed
    assert "ordine" in grade_rollback(case, "1. release_ip\n2. stop_container").detail
    assert grade_rollback(case, "1. stop_container").detail == "manca release_ip"
    assert not grade_rollback(case, None).passed


def test_grade_memory():
    case = {"expect_facts": True, "expect_entities": ["Synology"], "forbid_phrases": ["the user asked"]}
    assert grade_memory(case, [{"text": "Il NAS Synology ha IP 192.168.1.20", "entities": ["NAS Synology"]}]).passed
    assert "mancanti" in grade_memory(case, [{"text": "Il NAS ha IP 192.168.1.20", "entities": ["NAS"]}]).detail
    assert "conversazione" in grade_memory(case, [{"text": "The user asked about Synology", "entities": ["Synology"]}]).detail
    assert grade_memory({"expect_facts": False}, []).passed
    assert not grade_memory({"expect_facts": False}, [{"text": "Un bigram è una coppia di parole", "entities": []}]).passed


def test_grade_recall():
    case = {"expect_any": ["192.168.1.250"], "forbid": ["192.168.1.53"]}
    assert grade_recall(case, {"answer": "L'IP di Pi-hole è 192.168.1.250", "found": True}, "IP 192.168.1.250").passed
    detail = grade_recall(case, {"answer": "Non lo so", "found": False}, "Pi-hole ha IP 192.168.1.53").detail
    assert "manca 192.168.1.250" in detail and "nel contesto: no" in detail
    assert "cita 192.168.1.53" in grade_recall(case, {"answer": "192.168.1.250, prima 192.168.1.53", "found": True}, "").detail
    assert "nel contesto: sì" in grade_recall({"expect_all": ["Grafana", "Loki"]}, {"answer": "Grafana", "found": True}, "Grafana, Loki").detail
    # Conta solo se i valori mancanti erano nel contesto, non quelli già nella risposta
    assert "manca Loki (nel contesto: no)" in grade_recall({"expect_all": ["Grafana", "Loki"]}, {"answer": "Grafana", "found": True}, "Grafana").detail
    assert grade_recall({"abstain": True}, {"answer": "Non ne abbiamo mai parlato", "found": False}, "").passed
    assert not grade_recall({"abstain": True}, {"answer": "Sul CT 140", "found": True}, "").passed
    assert not grade_recall(case, None, "").passed


def test_recall_runs_in_a_sandbox_and_leaves_real_memory_untouched():
    from app.agent import memory_consolidation
    from app.agent.memory_consolidation import FactOperation
    from app.agent.nodes import retrieve_memory
    from app.memory import facts, thread_store

    thread_store.init_db()
    real_threads = len(thread_store.get_history("a"))
    real_facts = facts.stats()
    case = {
        "sessions": [
            {"thread": "a", "date": "2026-08-15", "turns": [["Pi-hole ha l'IP 192.168.1.53.", "Annotato."]]},
            {"thread": "q", "date": "2026-10-12", "turns": [["Chiamiamo Orione il progetto.", "D'accordo."]], "filler": 14},
        ],
        "thread": "q",
        "question": "Qual è l'IP di Pi-hole e come si chiama il progetto?",
        "expect_all": ["192.168.1.53", "Orione"],
    }
    seen = {}

    def consolidate(messages, related, model=None):
        if "Pi-hole" in messages[0]["content"]:
            return [FactOperation(op="add", message=1, fact="Pi-hole ha l'IP 192.168.1.53")]
        return []

    def reader(prompt, *args, **kwargs):
        seen["prompt"] = prompt
        return RecallAnswer(answer="192.168.1.53, progetto Orione", found=True)

    with patch.object(memory_consolidation, "propose_operations", side_effect=consolidate) as consolidation, \
            patch.object(retrieve_memory, "_update_summary", return_value="Il progetto si chiama Orione.") as summarize, \
            patch("app.agent.llm_calls.call_llm_structured", side_effect=reader):
        outcome = suites.run_recall(case, "m")

    assert outcome.passed, outcome.detail
    assert consolidation.call_count == 3  # thread a in un blocco, il thread lungo (30 messaggi) in due
    assert len(summarize.call_args.args[1]) == 30 - 10  # thread lungo: la parte vecchia passa dal riassunto
    # il fatto consolidato porta la data del messaggio da cui viene
    assert "- [2026-08-15] Pi-hole ha l'IP 192.168.1.53" in seen["prompt"] and "Il progetto si chiama Orione." in seen["prompt"]
    assert len(thread_store.get_history("a")) == real_threads and facts.stats() == real_facts


def test_capture_counts_llm_calls_without_recording_a_turn():
    with capture_llm_calls("eval:test") as trace:
        record_llm_call(provider="llamacpp", model="m", duration_ms=40, prompt_tokens=100, completion_tokens=7)
    assert (trace.llm_calls, trace.prompt_tokens, trace.completion_tokens) == (1, 100, 7)
    assert store.select("SELECT * FROM turns WHERE turn_key = 'eval:test'") == []
    assert store.select("SELECT turn_key FROM llm_calls WHERE turn_key = 'eval:test'") == [{"turn_key": "eval:test"}]


def test_evaluate_model_report_and_compare(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "reports_dir", lambda: tmp_path)
    monkeypatch.setattr(suites, "load_cases", lambda suite: [{"id": "a"}, {"id": "b"}, {"id": "c"}])
    runner_cases = {"a": Outcome(True, "ok"), "b": Outcome(False, "modalità chat, attesa act"), "c": Outcome(False, "assente", skipped=True)}

    def fake_run(case, model):
        if case["id"] == "a" and model == "rotto":
            raise RuntimeError("timeout del server")
        return runner_cases[case["id"]]

    monkeypatch.setitem(runner.SUITES, "routing", fake_run)
    monkeypatch.setattr(runner, "load_cases", suites.load_cases)

    good = runner.evaluate_model("modello-a", ["routing"], repeat=2)
    summary = good["suites"]["routing"]
    assert (summary["cases"], summary["runs"], summary["passed"], summary["skipped"], summary["accuracy"]) == (3, 4, 2, 1, 50.0)
    broken = runner.evaluate_model("rotto", ["routing"])
    assert broken["suites"]["routing"]["results"][0]["runs"][0]["detail"] == "errore: timeout del server"

    path = runner.save_report(good)
    runner.save_report(broken)
    assert json.loads(path.read_text())["model"] == "modello-a"
    # Un'esecuzione parziale successiva aggiorna solo le sue suite
    runner.save_report({**good, "started_at": "2099-01-01T00:00:00+00:00", "suites": {"tools": good["suites"]["routing"]}})
    merged = {r["model"]: r for r in runner.latest_reports()}["modello-a"]
    assert set(merged["suites"]) == {"routing", "tools"} and merged["started_at"].startswith("2099")
    table = runner.compare_markdown(runner.latest_reports())
    assert "| routing | 50% (2/4)" in table
    assert "- `routing/b`: modalità chat, attesa act" in table
    assert "**rotto**: 2 casi falliti" in table


def test_rollback_plan_is_requested_without_reasoning():
    from app.agent.execution_log import ExecutionLog, generate_rollback_plan_with_llm

    with patch("app.agent.llm_calls.call_llm", return_value={"content": "1. release_ip"}) as llm:
        assert generate_rollback_plan_with_llm([ExecutionLog({"id": 1}, "proxmox-mcp__allocate_ip", {})], "t", "errore") == "1. release_ip"
    assert llm.call_args.kwargs.get("thinking", "off") == "off"
    # Le compensazioni dichiarate dei passi riusciti sono nel prompt
    assert "`proxmox-mcp__allocate_ip` → `proxmox-mcp__release_ip`" in llm.call_args.args[0]


def test_cli_requires_models():
    from app.evals.__main__ import main

    with pytest.raises(SystemExit):
        main(["run"])


def test_plan_structure_has_no_fabricated_fallback():
    from app.agent.nodes.plan import generate_plan_structure

    valid = {"content": '```json\n{"steps": [{"id": 1, "description": "Elenca", "tool": "proxmox-mcp__list_containers", "args": {}}]}\n``` testo dopo'}
    with patch("app.agent.llm_calls.call_llm", return_value=valid) as llm:
        assert generate_plan_structure("lista i container", "User Request: 'lista i container'")["steps"][0]["tool"] == "proxmox-mcp__list_containers"
    # Output vincolato ai tool del catalogo, senza ragionamento
    kwargs = llm.call_args.kwargs
    assert kwargs.get("thinking", "off") == "off"
    assert "web_search" in kwargs["json_schema"]["properties"]["steps"]["items"]["properties"]["tool"]["enum"]
    for content in ("non ho capito", '{"steps": []}', '{"steps": [{"id": 1}]}'):
        with patch("app.agent.llm_calls.call_llm", return_value={"content": content}):
            assert generate_plan_structure("crea un servizio", "User Request: 'crea un servizio'") is None


def test_plan_structure_translates_the_drafted_plan():
    from app.agent.nodes.plan import generate_plan_structure

    valid = {"content": '{"steps": [{"id": 1, "description": "Elenca", "tool": "proxmox-mcp__list_containers", "args": {}}]}'}
    with patch("app.agent.llm_calls.call_llm", return_value=valid) as llm:
        generate_plan_structure("lista i container", "User Request: 'lista i container'", plan_text="1. list_containers")
    prompt, system_prompt = llm.call_args.args[0], llm.call_args.kwargs["system_prompt"]
    assert prompt.endswith("Drafted plan:\n1. list_containers") and system_prompt.startswith("Convert the drafted plan")


MULTISTEP_CASE = {
    "id": "nextcloud", "input": "il container di nextcloud è acceso?",
    "tools": {
        "list_containers": [{"result": [{"vmid": 121, "name": "nextcloud-db"}, {"vmid": 122, "name": "nextcloud"}]}],
        "get_container_status": [{"when": {"vmid": 122}, "result": {"status": "running", "mem": "1.5 GB"}},
                                 {"result": {"error": "Container non trovato"}}],
    },
    "expect_calls": [{"tool": "proxmox-mcp__list_containers"}, {"tool": "proxmox-mcp__get_container_status", "args": {"vmid": 122}}],
    "expect_answer": [["1.5", "1,5"]],
    "max_calls": 4,
}
MULTISTEP_CATALOG = ["proxmox-mcp__list_containers", "proxmox-mcp__get_container_status"]


def _call(step, tool, args=None, **extra):
    return {"step_id": step, "tool_name": f"proxmox-mcp__{tool}", "args": args or {}, **extra}


def test_simulated_result_picks_the_first_matching_entry():
    assert suites.simulated_result(MULTISTEP_CASE, "proxmox-mcp__get_container_status", {"vmid": "122"})["status"] == "running"
    assert "error" in suites.simulated_result(MULTISTEP_CASE, "get_container_status", {"vmid": 121})
    assert "non disponibile" in suites.simulated_result(MULTISTEP_CASE, "proxmox-mcp__exec_lxc_command", {})["error"]


def test_simulated_tools_never_reach_the_real_registry():
    from app.registry.manager import get_registry_manager

    with suites.simulated_tools(MULTISTEP_CASE):
        manager = get_registry_manager()
        assert manager.execute_tool("proxmox-mcp__list_containers", {}, ["mcp"])[1]["vmid"] == 122
        assert manager.execute_tools_parallel([{"tool_name": "proxmox-mcp__get_container_status", "arguments": {"vmid": 122}}], ["mcp"])[0]["status"] == "running"


def test_grade_multistep():
    chain = [_call(1, "list_containers"), _call(2, "get_container_status", {"vmid": 122})]
    outcome = suites.grade_multistep(MULTISTEP_CASE, chain, "Sì, usa 1,5 GB", MULTISTEP_CATALOG)
    assert outcome.passed and outcome.metrics["steps"] == 2 and outcome.metrics["tool_calls"] == 2
    risky = chain + [_call(3, "start_container", {"vmid": 122})]
    assert suites.grade_multistep(MULTISTEP_CASE, risky, "1.5", MULTISTEP_CATALOG).metrics["unsafe_calls"] == 1
    # Una chiamata in più nel mezzo è ammessa, l'ordine no
    detour = [_call(1, "list_containers"), _call(2, "get_container_status", {"vmid": 121}), chain[1]]
    assert suites.grade_multistep(MULTISTEP_CASE, detour, "1.5 GB", MULTISTEP_CATALOG).passed
    assert "manca get_container_status" in suites.grade_multistep(MULTISTEP_CASE, chain[::-1], "1.5", MULTISTEP_CATALOG).detail
    assert "risposta senza 1.5 o 1,5" in suites.grade_multistep(MULTISTEP_CASE, chain, "acceso", MULTISTEP_CATALOG).detail
    blocked = chain + [_call(3, "list_containers", duplicate_blocked=True)]
    assert suites.grade_multistep(MULTISTEP_CASE, blocked, "1.5", MULTISTEP_CATALOG).metrics["duplicates_blocked"] == 1
    too_many = chain + [_call(3, "get_container_status", {"vmid": i}) for i in range(3)]
    assert "al massimo 4" in suites.grade_multistep(MULTISTEP_CASE, too_many, "1.5", MULTISTEP_CATALOG).detail
    assert suites.grade_multistep(MULTISTEP_CASE, chain, "1.5", ["calendar_list_events"]).skipped
    unordered = {**MULTISTEP_CASE, "expect_calls": [MULTISTEP_CASE["expect_calls"][0],
                                                    [{"tool": "get_container_status", "args": {"vmid": 122}},
                                                     {"tool": "get_container_status", "args": {"vmid": 121}}]]}
    both = [_call(1, "list_containers"), _call(2, "get_container_status", {"vmid": 122}), _call(2, "get_container_status", {"vmid": 121})]
    assert suites.grade_multistep(unordered, both, "1.5", MULTISTEP_CATALOG).passed
    assert not suites.grade_multistep(unordered, both[:2], "1.5", MULTISTEP_CATALOG).passed


def test_summary_averages_the_case_metrics():
    runs = [{"passed": True, "skipped": False, "duration_ms": 10, "prompt_tokens": 1, "completion_tokens": 100, "metrics": {"steps": 2.0}},
            {"passed": False, "skipped": False, "duration_ms": 20, "prompt_tokens": 1, "completion_tokens": 300, "metrics": {"steps": 4.0}}]
    summary = runner.summarize([{"id": "a", "runs": runs}])
    assert summary["metrics"] == {"steps": 3.0}
    text = runner.compare_markdown([{"model": "m [interleaved on]", "started_at": "2026-10-30T10:00", "suites": {"multistep": {**summary, "results": []}}}])
    assert "- m [interleaved on]: steps 3, token generati 200" in text
