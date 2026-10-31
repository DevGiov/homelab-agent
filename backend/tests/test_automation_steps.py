import os
import shutil
import tempfile
import unittest
import unittest.mock

import pytest

from app.automations.db import definitions as definitions_db
from app.automations.db.schema import init_automations_db
from app.automations.models import (
    AutomationDefinition,
    ExecutionPolicy,
    RunStatus,
    StepType,
    WorkflowSpec,
    WorkflowStepDefinition,
)
from app.automations.steps import agentic, approval, calendar_action, custom_code, select_handler, tool_action
from app.core.config import settings
from app.registry.automations_tool import AutomationRegistry


def _step(step_type, tool=None, requires_approval=False):
    return WorkflowStepDefinition(step_id="s", name="S", type=step_type, action_or_tool=tool,
                                  requires_approval=requires_approval)


@pytest.mark.parametrize("step, handler", [
    (_step(StepType.APPROVAL_GATE), approval.run),
    (_step(StepType.DETERMINISTIC_ACTION, "save_artifact", requires_approval=True), approval.run),
    (_step(StepType.CUSTOM_CODE), custom_code.run),
    (_step(StepType.DETERMINISTIC_ACTION, "scripts/report.py"), custom_code.run),
    (_step(StepType.CALENDAR), calendar_action.run),
    (_step(StepType.DETERMINISTIC_ACTION, "calendar_create_event"), calendar_action.run),
    (_step(StepType.DETERMINISTIC_ACTION, "save_artifact"), tool_action.run),
    (_step(StepType.AGENTIC_TASK), agentic.run),
])
def test_select_handler(step, handler):
    assert select_handler(step) is handler


def test_evaluation_gate_passes():
    outcome = select_handler(_step(StepType.EVALUATION_GATE))(None)
    assert outcome["status"] == RunStatus.COMPLETED and outcome["output"] == {"evaluation": "passed"}


class TestTriggerRunFromChat(unittest.TestCase):
    """Il tool `automations_trigger_run` usato dall'agente in chat crea la run e la esegue."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig_data_dir = settings.data_dir
        settings.data_dir = self.tmp_dir
        init_automations_db()
        definition = AutomationDefinition(
            id="auto_chat_trigger",
            name="Chat trigger",
            workflow=WorkflowSpec(initial_step_id="gate", steps=[
                WorkflowStepDefinition(step_id="gate", name="Gate", type=StepType.EVALUATION_GATE),
            ]),
            permission_policy=ExecutionPolicy(),
        )
        definitions_db.save_definition(definition.model_dump(), db_path=settings.automations_db_path)

    def tearDown(self):
        settings.data_dir = self.orig_data_dir
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_trigger_run_executes_the_automation(self):
        res = AutomationRegistry()._trigger_run("auto_chat_trigger", dry_run=True)

        self.assertNotIn("error", res)
        self.assertEqual(res["status"], RunStatus.COMPLETED.value)
        self.assertTrue(res["is_dry_run"])
        self.assertTrue(os.path.exists(settings.automations_db_path))


def _models(*loaded):
    provider = unittest.mock.MagicMock()
    provider.list_models_with_details.return_value = [
        {"id": "LFM2.5-24B-A2B-Fast", "is_loaded": "LFM2.5-24B-A2B-Fast" in loaded},
        {"id": "Qwen3.6-35B", "is_loaded": "Qwen3.6-35B" in loaded},
    ]
    return unittest.mock.patch("app.llm.providers.get_provider", return_value=provider)


def test_loaded_choice_resolves_to_the_loaded_model_or_the_default():
    from app.llm.providers import LOADED_MODEL, resolve_model

    with _models("Qwen3.6-35B"):
        assert resolve_model(LOADED_MODEL) == "Qwen3.6-35B"
        assert resolve_model("LFM2.5-24B-A2B-Fast") == "LFM2.5-24B-A2B-Fast"
        assert resolve_model(None) is None
    with _models():
        assert resolve_model(LOADED_MODEL) is None  # nessuno caricato: default del provider


@pytest.mark.parametrize("choice, loaded, expected", [
    ("loaded", ("Qwen3.6-35B",), "Qwen3.6-35B"),
    ("loaded", (), None),
    ("LFM2.5-24B-A2B-Fast", ("Qwen3.6-35B",), "LFM2.5-24B-A2B-Fast"),
    (None, ("Qwen3.6-35B",), None),
])
def test_agentic_step_uses_the_model_chosen_for_the_automation(choice, loaded, expected):
    from app.automations.steps.base import StepContext

    step = WorkflowStepDefinition(step_id="sintesi", name="Sintesi", type=StepType.AGENTIC_TASK, prompt_template="Riassumi")
    automation = AutomationDefinition(id="auto_model", name="Modello", model=choice,
                                      workflow=WorkflowSpec(initial_step_id="sintesi", steps=[step]))
    ctx = StepContext(step=step, automation=automation, run=unittest.mock.MagicMock(is_dry_run=False), data={},
                      registry_manager=unittest.mock.MagicMock())
    with _models(*loaded), unittest.mock.patch.object(agentic, "call_llm", return_value={"content": "Fatto."}) as llm, \
            unittest.mock.patch("app.agent.agent_loop.get_registry_manager"):
        outcome = agentic.run(ctx)
    assert llm.call_args.kwargs["model"] == expected
    assert outcome["output"] == {"text": "Fatto.", "model": expected}
