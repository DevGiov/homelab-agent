import os
import shutil
import tempfile
import unittest

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
