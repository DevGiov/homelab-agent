"""Profili di ragionamento dei modelli, livelli per fase del turno e pensiero tra i passi dell'agent loop."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.agent import llm_calls
from app.agent.mode_policy import get_mode_policy
from app.core.config import settings
from app.llm.reasoning import LEVEL_BUDGETS, interleaved_for, profile_for, resolve


@pytest.mark.parametrize("alias, family, kind", [
    ("Qwen3.6-35B-HugeCtx", "Qwen3.6", "hybrid"),
    ("Qwen3.8-27B-GSQ-IQ3_S-64K", "Qwen3.8", "hybrid"),
    ("Qwen3.8-27B-Obliterated-IQ4", "Qwen3.8", "hybrid"),
    ("Gemma-4-26B-Vision-Q4", "Gemma 4", "hybrid"),
    ("Gemma-4-E4B", "Gemma 4", "hybrid"),
    ("LFM2.5-24B-A2B-Balanced", "LFM2.5", "always"),
    ("Phi-4-mini-Q8", "Phi-4", "none"),
    ("Emma-5", "sconosciuto", "unknown"),
])
def test_every_preset_alias_gets_its_family_profile(alias, family, kind):
    profile = profile_for(alias)
    assert (profile.family, profile.kind) == (family, kind)


def test_modes_think_only_in_the_phases_that_need_it():
    assert get_mode_policy("chat").thinking.model_dump() == {"answer": "off", "select": "off", "plan": "off"}
    assert get_mode_policy("ask").thinking.model_dump() == {"answer": "low", "select": "low", "plan": "off"}
    assert get_mode_policy("act").thinking.model_dump() == {"answer": "low", "select": "medium", "plan": "off"}
    assert get_mode_policy("plan").thinking.model_dump() == {"answer": "low", "select": "medium", "plan": "high"}


def test_unknown_models_keep_the_caller_temperature_and_get_explicit_controls():
    reasoning = resolve("modello-nuovo", "low", temperature=0.3)
    assert reasoning.enabled and reasoning.budget == LEVEL_BUDGETS["low"]
    assert reasoning.sampling.params() == {"temperature": 0.3}
    assert reasoning.payload()["chat_template_kwargs"] == {"enable_thinking": True}


def test_call_llm_adds_the_reasoning_budget_to_the_answer_length():
    provider = MagicMock(default_model="Qwen3.6-35B")
    provider.chat.return_value = {"content": "ok"}
    with patch.object(llm_calls, "get_provider", return_value=provider):
        llm_calls.call_llm("ciao", max_tokens=1000, thinking="medium", stream_mode="none")
        llm_calls.call_llm("ciao", max_tokens=1000, stream_mode="none")
    with_thinking, without = (c.kwargs for c in provider.chat.call_args_list)
    assert with_thinking["max_tokens"] == 1000 + LEVEL_BUDGETS["medium"] and with_thinking["reasoning"].enabled
    assert without["max_tokens"] == 1000 and not without["reasoning"].enabled


def test_agent_loop_selects_with_the_select_level_and_answers_with_the_answer_level():
    from app.agent.agent_loop import AgentLoop, ToolSelection

    seen = {}

    def structured(**kwargs):
        seen["select"] = kwargs["thinking"]
        return ToolSelection(tool_needed=False, tool_name=None, arguments={}, parallel_calls=None, confidence=1.0,
                             reasoning="niente da fare", final_answer=None)

    def text(prompt, system_prompt=None, thinking="off", reasoning_phase=None):
        seen["answer"] = thinking
        return {"content": "risposta"}

    with patch("app.agent.agent_loop.get_registry_manager") as manager:
        manager.return_value.get_tools_for_mode.return_value = [{"name": "proxmox-mcp__list_containers", "description": "", "parameters": {}}]
        AgentLoop("elenca i container", "act", None, text, structured, None, None, None, "normal").run()
    assert seen == {"select": "medium", "answer": "low"}


@pytest.mark.parametrize("alias, interleaved", [
    ("Qwen3.6-35B", True), ("Qwen3.8-27B-Fast", True), ("LFM2.5-24B-A2B-Balanced", True),
    ("Gemma-4-26B-Q4", False), ("Phi-4-mini-Q8", False), ("Emma-5", False),
])
def test_interleaved_follows_the_template_of_the_family(alias, interleaved):
    assert interleaved_for(alias) is interleaved


def test_interleaved_can_be_forced_for_comparisons():
    with patch.object(settings, "agent_interleaved_thinking", "off"):
        assert not interleaved_for("Qwen3.6-35B")
    with patch.object(settings, "agent_interleaved_thinking", "on"):
        assert interleaved_for("Gemma-4-26B-Q4")


def test_call_llm_sends_the_previous_steps_after_the_user_message():
    provider = MagicMock(default_model="Qwen3.6-35B")
    provider.chat.return_value = {"content": "{}"}
    steps = [{"role": "assistant", "content": "{}", "reasoning_content": "prima"}, {"role": "tool", "content": "risultato"}]
    with patch.object(llm_calls, "get_provider", return_value=provider):
        llm_calls.call_llm("richiesta", system_prompt="regole", history=steps, stream_mode="none")
    assert [m["role"] for m in provider.chat.call_args.args[0]] == ["system", "user", "assistant", "tool"]


def _two_step_loop(interleaved):
    from app.agent.agent_loop import AgentLoop, ToolSelection

    calls = []

    def structured(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            selection = ToolSelection(tool_needed=True, tool_name="proxmox-mcp__list_containers", arguments={}, parallel_calls=None,
                                      confidence=1.0, reasoning="servono i container", final_answer=None)
            selection.raw_thinking = "cerco prima i container"
            return selection
        return ToolSelection(tool_needed=False, tool_name=None, arguments={}, parallel_calls=None, confidence=1.0,
                             reasoning="fatto", final_answer="Ci sono due container attivi.")

    with patch("app.agent.agent_loop.get_registry_manager") as manager:
        manager.return_value.get_tools_for_mode.return_value = [{"name": "proxmox-mcp__list_containers", "description": "", "parameters": {}}]
        manager.return_value.execute_tool.return_value = [{"vmid": 100}, {"vmid": 101}]
        AgentLoop("elenca i container", "act", None, lambda *a, **k: {"content": ""}, structured, None, None, None, "normal",
                  interleaved).run()
    return calls


def test_interleaved_loop_sends_each_step_with_its_thinking_as_messages():
    first, second = _two_step_loop(interleaved=True)
    assert first["prompt"] == second["prompt"] and "History of actions" not in second["prompt"]
    assistant, tool = second["history"]
    assert assistant["reasoning_content"] == "cerco prima i container"
    assert json.loads(assistant["content"])["tool_name"] == "proxmox-mcp__list_containers"
    assert tool["role"] == "tool" and '"vmid": 100' in tool["content"]


def test_plain_loop_keeps_the_history_as_text_in_the_user_message():
    first, second = _two_step_loop(interleaved=False)
    assert "history" not in second and "History of actions" in second["prompt"]
    assert "list_containers" in second["prompt"] and "cerco prima" not in second["prompt"]
