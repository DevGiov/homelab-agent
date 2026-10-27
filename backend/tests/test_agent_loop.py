"""Percorsi dell'agent loop con registry e LLM finti: approvazione, chiamate parallele, validazione, sintesi."""
from unittest.mock import MagicMock, patch

import pytest

from app.agent.agent_loop import run_agent_loop
from app.agent.llm_calls import call_llm_structured
from app.agent.tool_schemas import ToolSelection
from app.core.config import settings
from app.llm.providers import LLMUnavailableError

TOOLS = [
    {"name": "list_containers", "description": "", "parameters": {"type": "object", "properties": {}}},
    {"name": "get_container_status", "description": "",
     "parameters": {"type": "object", "properties": {"vmid": {"type": "integer"}}, "required": ["vmid"]}},
    {"name": "stop_container", "description": "",
     "parameters": {"type": "object", "properties": {"vmid": {"type": "integer"}}, "required": ["vmid"]}},
]


@pytest.fixture
def manager():
    mgr = MagicMock()
    mgr.get_tools_for_mode.return_value = TOOLS
    with patch("app.agent.agent_loop.get_registry_manager", return_value=mgr):
        yield mgr


def _llm(content="sintesi finale"):
    return MagicMock(return_value={"content": content, "reasoning_content": ""})


def _selections(*items):
    return MagicMock(side_effect=list(items))


def _done(answer="Risposta finale abbastanza lunga per essere accettata."):
    return ToolSelection(tool_needed=False, final_answer=answer)


def test_approval_required_stops_the_turn(manager):
    manager.execute_tool.return_value = {
        "approval_required": True, "request_id": "req_1", "message": "Confermi lo stop?",
        "command_preview": "stop 101", "command_prefix": None, "risk_reason": "mutazione",
    }
    select = _selections(ToolSelection(tool_needed=True, tool_name="stop_container", arguments={"vmid": 101}, reasoning="fermo il CT"))

    res = run_agent_loop("ferma il CT 101", "act", call_llm_fn=_llm(), call_llm_structured_fn=select)

    assert res["approval_required"] and res["request_id"] == "req_1"
    assert res["final_response"] == "Confermi lo stop?"
    assert res["execution_trace"][-1]["approval_required"] is True
    assert select.call_count == 1


def test_parallel_read_only_calls_then_synthesis(manager):
    manager.execute_tools_parallel.return_value = [{"containers": [101]}, {"status": "running"}]
    parallel = [{"tool_name": "list_containers", "arguments": {}},
                {"tool_name": "get_container_status", "arguments": {"vmid": 101}}]
    select = _selections(ToolSelection(tool_needed=True, tool_name="list_containers", parallel_calls=parallel),
                         ToolSelection(tool_needed=False))
    llm = _llm("Il CT 101 è in esecuzione.")

    res = run_agent_loop("stato dei container", "act", call_llm_fn=llm, call_llm_structured_fn=select)

    assert [t["parallel_index"] for t in res["execution_trace"]] == [0, 1]
    manager.execute_tool.assert_not_called()
    assert res["final_response"] == "Il CT 101 è in esecuzione."
    assert "Sintesi Risultati Tool" == llm.call_args.kwargs["reasoning_phase"]


def test_invalid_arguments_are_reported_to_the_model(manager):
    select = _selections(ToolSelection(tool_needed=True, tool_name="get_container_status", arguments={"vmid": "abc"}), _done())

    res = run_agent_loop("stato del CT", "act", call_llm_fn=_llm(), call_llm_structured_fn=select)

    manager.execute_tool.assert_not_called()
    assert res["execution_trace"][0]["error"].startswith("Validazione fallita")
    assert "fallita la validazione" in select.call_args.kwargs["prompt"]
    assert res["final_response"].startswith("Risposta finale")


def test_read_only_results_are_cached_within_the_turn(manager):
    manager.execute_tool.return_value = {"containers": [101]}
    select = _selections(ToolSelection(tool_needed=True, tool_name="list_containers"), _done())

    res = run_agent_loop("elenca i container", "act", call_llm_fn=_llm(), call_llm_structured_fn=select)

    assert manager.execute_tool.call_count == 1
    assert res["execution_trace"][0]["cached"] is False


def test_step_limit_ends_with_final_synthesis(manager):
    manager.execute_tool.side_effect = lambda name, args, *a, **kw: {"vmid": args["vmid"], "status": "running"}
    # ask consente 5 chiamate: una diversa per passo, mai una risposta finale
    select = MagicMock(side_effect=[ToolSelection(tool_needed=True, tool_name="get_container_status", arguments={"vmid": i})
                                    for i in range(1, 6)])
    llm = _llm("Tutti i container sono attivi.")

    res = run_agent_loop("controlla i container", "ask", call_llm_fn=llm, call_llm_structured_fn=select)

    assert manager.execute_tool.call_count == 5
    assert res["final_response"] == "Tutti i container sono attivi."
    assert llm.call_args.kwargs["reasoning_phase"] == "Sintesi Risultati Finali"


def test_without_structured_llm_answers_directly(manager):
    llm = _llm("risposta diretta")

    res = run_agent_loop("riassumi", "act", call_llm_fn=llm, call_llm_structured_fn=None)

    assert res["final_response"] == "risposta diretta"
    assert llm.call_args.kwargs["reasoning_phase"] == "Elaborazione Risposta Finale"
    manager.execute_tool.assert_not_called()


def test_chat_mode_never_selects_tools(manager):
    select = MagicMock()

    res = run_agent_loop("ciao", "chat", call_llm_fn=_llm("Ciao!"), call_llm_structured_fn=select)

    assert res["final_response"] == "Ciao!"
    select.assert_not_called()


def test_null_arguments_mean_no_arguments():
    # LFM2.5 scrive `"arguments": null` per i tool senza parametri: prima la selezione veniva scartata
    selection = ToolSelection.model_validate({"tool_needed": True, "tool_name": "list_containers", "arguments": None, "reasoning": None})
    assert selection.arguments == {} and selection.reasoning == ""


def test_selection_system_prompt_is_stable_and_history_comes_last(manager):
    # Prefisso identico tra i passi: llama.cpp riusa la parte già elaborata
    manager.execute_tool.return_value = {"containers": [101]}
    select = _selections(ToolSelection(tool_needed=True, tool_name="list_containers"), _done())

    run_agent_loop("elenca i container", "act", memory_context="ricordo X", call_llm_fn=_llm(), call_llm_structured_fn=select)

    first, second = (c.kwargs for c in select.call_args_list)
    assert first["system_prompt"] == second["system_prompt"]
    assert "ricordo X" not in first["system_prompt"] and "Date and Time" not in first["system_prompt"]
    assert second["prompt"].startswith(first["prompt"].rsplit("\n", 1)[0])
    assert second["prompt"].rstrip().endswith('{"containers": [101]}')


def test_long_results_are_shortened_for_selection_but_complete_for_synthesis(manager, monkeypatch):
    monkeypatch.setattr(settings, "agent_observation_limit", 50)
    manager.execute_tool.return_value = {"containers": list(range(500))}
    select = _selections(ToolSelection(tool_needed=True, tool_name="list_containers"), _done("Risposta su dati parziali, da scartare."))
    llm = _llm("Sintesi sui dati completi.")

    res = run_agent_loop("elenca i container", "act", call_llm_fn=llm, call_llm_structured_fn=select)

    assert "result truncated to 50" in select.call_args.kwargs["prompt"]
    assert "499" not in select.call_args.kwargs["prompt"]
    # La final_answer della selezione vedeva dati troncati: si sintetizza sui risultati interi
    assert res["final_response"] == "Sintesi sui dati completi."
    assert "499" in llm.call_args.args[0]


def test_unavailable_model_ends_the_turn_without_more_requests(manager):
    select = MagicMock(side_effect=LLMUnavailableError("timeout"))
    llm = _llm()

    res = run_agent_loop("elenca i container", "act", call_llm_fn=llm, call_llm_structured_fn=select)

    assert "timeout" in res["final_response"]
    assert select.call_count == 1
    llm.assert_not_called()


def test_structured_call_does_not_retry_a_failed_request():
    provider = MagicMock()
    provider.chat.return_value = {"content": "", "reasoning_content": "", "metrics": {}, "error": "timeout"}
    with patch("app.agent.llm_calls.get_provider", return_value=provider), pytest.raises(LLMUnavailableError):
        call_llm_structured("prompt", "sys", ToolSelection, max_retries=3)
    assert provider.chat.call_count == 1
