"""Test per il motore di esecuzione a stati finiti (Durable Step Runner)."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from automations import db as auto_db
from automations.models import (
    AutomationDefinition,
    ExecutionPolicy,
    Budget,
    RunStatus,
    StepType,
    TriggerType,
    WorkflowSpec,
    WorkflowStepDefinition,
)
from automations.runner import AutomationRunner


class TestAutomationRunner(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "runner_test.db")
        auto_db.init_automations_db(self.db_path)
        self.runner = AutomationRunner(db_path=self.db_path)
        self._orig_execute_tool = self.runner.registry_manager.execute_tool

    def tearDown(self):
        self.runner.registry_manager.execute_tool = self._orig_execute_tool
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_deterministic_multi_step_execution(self):
        """Verifica esecuzione sequenziale di step deterministici con passaggio dati."""
        auto_def = AutomationDefinition(
            id="auto_deter_test",
            name="Deterministic Pipeline",
            workflow=WorkflowSpec(
                initial_step_id="step_1",
                steps=[
                    WorkflowStepDefinition(
                        step_id="step_1",
                        name="Fetch Data",
                        type=StepType.DETERMINISTIC_ACTION,
                        action_or_tool="mock_tool_1",
                        parameters={"query": "test"}
                    ),
                    WorkflowStepDefinition(
                        step_id="step_2",
                        name="Process Data",
                        type=StepType.DETERMINISTIC_ACTION,
                        action_or_tool="mock_tool_2",
                        parameters={"data": "{{steps.step_1.output.value}}"}
                    ),
                ]
            ),
            permission_policy=ExecutionPolicy(
                allowed_tools=["mock_tool_1", "mock_tool_2"]
            )
        )
        auto_db.save_definition(auto_def.model_dump(), db_path=self.db_path)

        def mock_execute(tool_name, params, **kwargs):
            if tool_name == "mock_tool_1":
                return {"value": "hello_world"}
            if tool_name == "mock_tool_2":
                return {"processed": f"got_{params.get('data')}"}
            return {}

        self.runner.registry_manager.execute_tool = MagicMock(side_effect=mock_execute)

        run = self.runner.start_run("auto_deter_test")
        completed_run = self.runner.execute_run(run.run_id)

        self.assertEqual(completed_run.status, RunStatus.COMPLETED)
        self.assertEqual(len(completed_run.step_runs), 2)
        s1 = completed_run.step_runs[0]
        s2 = completed_run.step_runs[1]
        self.assertEqual(s1.status, RunStatus.COMPLETED)
        self.assertEqual(s1.output_payload, {"value": "hello_world"})
        self.assertEqual(s2.status, RunStatus.COMPLETED)
        self.assertEqual(s2.output_payload, {"processed": "got_hello_world"})

    def test_approval_gate_pause_and_resume(self):
        """Verifica che uno step con approval gate congeli la run in WAITING_APPROVAL e riprenda alla conferma."""
        auto_def = AutomationDefinition(
            id="auto_approval_test",
            name="Approval Gate Pipeline",
            workflow=WorkflowSpec(
                initial_step_id="s_prep",
                steps=[
                    WorkflowStepDefinition(
                        step_id="s_prep",
                        name="Prepare",
                        type=StepType.DETERMINISTIC_ACTION,
                        action_or_tool="tool_prep",
                    ),
                    WorkflowStepDefinition(
                        step_id="s_gate",
                        name="Sensitive Gate",
                        type=StepType.APPROVAL_GATE,
                    ),
                    WorkflowStepDefinition(
                        step_id="s_final",
                        name="Final Step",
                        type=StepType.DETERMINISTIC_ACTION,
                        action_or_tool="tool_final",
                    ),
                ]
            ),
            permission_policy=ExecutionPolicy(
                allowed_tools=["tool_prep", "tool_final"]
            )
        )
        auto_db.save_definition(auto_def.model_dump(), db_path=self.db_path)

        self.runner.registry_manager.execute_tool = MagicMock(return_value={"status": "ok"})

        run = self.runner.start_run("auto_approval_test")
        paused_run = self.runner.execute_run(run.run_id)

        # Deve essere in WAITING_APPROVAL
        self.assertEqual(paused_run.status, RunStatus.WAITING_APPROVAL)
        self.assertEqual(paused_run.current_step_id, "s_gate")
        self.assertIsNotNone(paused_run.pending_approval_id)

        # Verifichiamo che l'approvazione sia presente su DB
        apprs = auto_db.list_pending_approvals(run_id=run.run_id, db_path=self.db_path)
        self.assertEqual(len(apprs), 1)
        appr_id = apprs[0]["request_id"]

        # Ora approviamo
        resumed_run = self.runner.resume_run(run.run_id, appr_id, action="approve", resolved_by="test_admin")
        self.assertEqual(resumed_run.status, RunStatus.COMPLETED)
        self.assertEqual(len(resumed_run.step_runs), 3)

    def test_dry_run_mode(self):
        """In modalità dry-run, gli step non devono invocare tool reali ma registrare simulazioni."""
        auto_def = AutomationDefinition(
            id="auto_dry_test",
            name="Dry Run Pipeline",
            workflow=WorkflowSpec(
                initial_step_id="s1",
                steps=[
                    WorkflowStepDefinition(
                        step_id="s1",
                        name="Mutating Action",
                        type=StepType.DETERMINISTIC_ACTION,
                        action_or_tool="dangerous_tool",
                        parameters={"target": "100"}
                    )
                ]
            ),
            permission_policy=ExecutionPolicy(allowed_tools=["dangerous_tool"])
        )
        auto_db.save_definition(auto_def.model_dump(), db_path=self.db_path)
        self.runner.registry_manager.execute_tool = MagicMock()

        run = self.runner.start_run("auto_dry_test", dry_run=True)
        self.assertTrue(run.is_dry_run)
        completed_run = self.runner.execute_run(run.run_id)

        self.assertEqual(completed_run.status, RunStatus.COMPLETED)
        self.runner.registry_manager.execute_tool.assert_not_called()
        self.assertTrue(completed_run.step_runs[0].output_payload.get("dry_run"))

    def test_budget_token_exhaustion(self):
        """Verifica che il superamento del budget token interrompa il workflow in EXHAUSTED."""
        auto_def = AutomationDefinition(
            id="auto_budget_test",
            name="Budget Pipeline",
            budget=Budget(max_tokens=100),
            workflow=WorkflowSpec(
                initial_step_id="s1",
                steps=[
                    WorkflowStepDefinition(
                        step_id="s1",
                        name="Step 1",
                        type=StepType.DETERMINISTIC_ACTION,
                        action_or_tool="tool_1",
                    ),
                    WorkflowStepDefinition(
                        step_id="s2",
                        name="Step 2",
                        type=StepType.DETERMINISTIC_ACTION,
                        action_or_tool="tool_2",
                    ),
                ]
            ),
            permission_policy=ExecutionPolicy(allowed_tools=["tool_1", "tool_2"])
        )
        auto_db.save_definition(auto_def.model_dump(), db_path=self.db_path)

        # Simuliamo un output con molti token
        with patch.object(self.runner, "_execute_step") as mock_step:
            mock_step.return_value = {
                "status": RunStatus.COMPLETED,
                "output": {"ok": True},
                "tokens": 150  # Supera max_tokens=100
            }
            run = self.runner.start_run("auto_budget_test")
            exhausted_run = self.runner.execute_run(run.run_id)

            self.assertEqual(exhausted_run.status, RunStatus.EXHAUSTED)

    def test_xml_feed_parsing_and_content_extraction(self):
        """Verifica estrazione pulita e parsing di feed XML Atom/RSS."""
        from automations.runner import _extract_step_content, _parse_xml_feed_to_text

        sample_atom_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <title>ArXiv Query</title>
          <entry>
            <title>Advances in Multi-Agent Reasoning</title>
            <summary>This paper explores durable workflows and step runner patterns.</summary>
            <author><name>Alice Smith</name></author>
            <published>2026-09-20T10:00:00Z</published>
            <link href="http://arxiv.org/abs/2609.99999"/>
          </entry>
        </feed>"""

        parsed = _parse_xml_feed_to_text(sample_atom_xml)
        self.assertIsNotNone(parsed)
        self.assertIn("Advances in Multi-Agent Reasoning", parsed)
        self.assertIn("Alice Smith", parsed)
        self.assertIn("This paper explores durable workflows", parsed)

        ctx = {
            "steps": {
                "fetch": {"output": {"status": 200, "content": sample_atom_xml}},
                "agent": {"output": {"text": "Ecco la sintesi dei paper selezionati."}}
            }
        }

        extracted_fetch = _extract_step_content("step:fetch", ctx)
        self.assertIn("Advances in Multi-Agent Reasoning", extracted_fetch)

        extracted_agent = _extract_step_content("step:agent", ctx)
        self.assertEqual(extracted_agent, "Ecco la sintesi dei paper selezionati.")

    def test_input_source_and_content_source_resolution(self):
        """Verifica che _resolve_parameters popoli content/body e path da content_source e filename."""
        from automations.runner import _resolve_parameters

        ctx = {
            "steps": {
                "step_report": {"output": {"text": "# Report Finale\nOttimi risultati."}}
            }
        }

        params = {
            "content_source": "step:step_report",
            "filename": "/tmp/test_report.md",
            "title": "Report Test"
        }

        resolved = _resolve_parameters(params, ctx)
        self.assertEqual(resolved["content"], "# Report Finale\nOttimi risultati.")
        self.assertEqual(resolved["path"], "/tmp/test_report.md")


if __name__ == "__main__":
    unittest.main()
