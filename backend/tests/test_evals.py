"""Harness di valutazione dei modelli: casi, giudizi, esecuzione, report e piano strutturato senza ripieghi."""
import json
from unittest.mock import patch

import pytest

from app.evals import runner, suites
from app.evals.suites import Outcome, grade_memory, grade_plan, grade_rollback, grade_routing, grade_tool
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
    }[suite]
    assert all(required <= set(c) for c in cases)


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
    table = runner.compare_markdown(runner.latest_reports())
    assert "| routing | 50% (2/4)" in table
    assert "- `routing/b`: modalità chat, attesa act" in table
    assert "**rotto**: 2 casi falliti" in table


def test_cli_requires_models():
    from app.evals.__main__ import main

    with pytest.raises(SystemExit):
        main(["run"])


def test_plan_structure_has_no_fabricated_fallback():
    from app.agent.nodes.plan import generate_plan_structure

    valid = {"content": '```json\n{"steps": [{"id": 1, "description": "Elenca", "tool": "proxmox-mcp__list_containers", "args": {}}]}\n``` testo dopo'}
    with patch("app.agent.llm_calls.call_llm", return_value=valid):
        assert generate_plan_structure("lista i container", "User Request: 'lista i container'")["steps"][0]["tool"] == "proxmox-mcp__list_containers"
    for content in ("non ho capito", '{"steps": []}', '{"steps": [{"id": 1}]}'):
        with patch("app.agent.llm_calls.call_llm", return_value={"content": content}):
            assert generate_plan_structure("crea un servizio", "User Request: 'crea un servizio'") is None
