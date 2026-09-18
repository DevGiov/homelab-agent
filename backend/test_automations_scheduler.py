"""Test unitari e di integrazione per AutomationScheduler ed EmailRegistry (Milestone M2)."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automations import db as auto_db
from automations.models import AutomationDefinition, RunStatus, TriggerType
from automations.runner import AutomationRunner
from automations.scheduler import AutomationScheduler
from registry.email_tool import EmailRegistry
from registry.manager import ToolRegistryManager


class TestAutomationsSchedulerAndEmail(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_scheduler.db")
        auto_db.init_automations_db(self.db_path)
        self.runner = AutomationRunner(db_path=self.db_path)
        self.scheduler = AutomationScheduler(db_path=self.db_path)

    def tearDown(self):
        if self.scheduler.is_running:
            self.scheduler.stop()
        self.tmp_dir.cleanup()

    def test_email_registry_tools(self):
        """Verifica le operazioni del registry email: fetch, draft e salvataggio artefatto."""
        reg = EmailRegistry()
        self.assertEqual(reg.name, "email")
        tools = reg.get_tools()
        tool_names = [t["name"] for t in tools]
        self.assertIn("email_fetch_unread", tool_names)
        self.assertIn("email_create_draft", tool_names)
        self.assertIn("save_briefing_artifact", tool_names)

        # 1. Fetch unread
        fetch_res = reg.execute_tool("email_fetch_unread", {"max_emails": 5})
        self.assertIn("emails", fetch_res)
        self.assertGreater(len(fetch_res["emails"]), 0)
        self.assertEqual(fetch_res["emails"][0]["unread"], True)

        # 2. Create draft (strict no auto-send)
        draft_res = reg.execute_tool(
            "email_create_draft",
            {
                "to": "admin@homelab.local",
                "subject": "Re: Proxmox Alert",
                "body": "Controllo effettuato, spazio ZFS verificato.",
            },
        )
        self.assertEqual(draft_res["status"], "draft_saved")
        self.assertIn("warning", draft_res)
        self.assertIn("auto-send categoricamente disabilitato", draft_res["warning"])

        # 3. Save briefing artifact
        art_res = reg.execute_tool(
            "save_briefing_artifact",
            {
                "title": "Daily Homelab Report",
                "content": "# Report Giornaliero\nTutto regolare.",
            },
        )
        self.assertEqual(art_res["status"], "saved")
        self.assertEqual(art_res["title"], "Daily Homelab Report")

    def test_scheduler_lifecycle_and_job_sync(self):
        """Verifica avvio, sincronizzazione trigger da DB e spegnimento dello scheduler."""
        # Creazione di un'automazione con trigger cron
        auto_payload = {
            "id": "auto_cron_briefing",
            "name": "Briefing Notturno",
            "enabled": True,
            "triggers": [
                {
                    "id": "trg_cron_1",
                    "type": "cron",
                    "cron_expression": "0 2 * * *",
                    "timezone": "Europe/Rome",
                    "enabled": True,
                }
            ],
            "workflow": {
                "initial_step_id": "step_1",
                "steps": [
                    {
                        "step_id": "step_1",
                        "name": "Lettura Mail",
                        "type": "deterministic_action",
                        "action_or_tool": "email_fetch_unread",
                        "parameters": {"max_emails": 5},
                    }
                ],
            },
        }
        auto_db.save_definition(auto_payload, db_path=self.db_path)

        # Avvio scheduler
        self.scheduler.start()
        self.assertTrue(self.scheduler.is_running)

        jobs = self.scheduler.get_scheduled_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["job_id"], "auto_job_auto_cron_briefing_trg_cron_1")
        self.assertIn("Briefing Notturno", jobs[0]["name"])

        # Disabilitazione automazione e re-sync
        auto_payload["enabled"] = False
        auto_db.save_definition(auto_payload, db_path=self.db_path)
        self.scheduler.sync_triggers()

        jobs_after = self.scheduler.get_scheduled_jobs()
        self.assertEqual(len(jobs_after), 0)

        # Arresto
        self.scheduler.stop()
        self.assertFalse(self.scheduler.is_running)

    def test_daily_email_briefing_template_dry_run(self):
        """Verifica il template Daily Email Briefing in modalità dry-run completo."""
        template_file = (
            Path(__file__).parent / "automations" / "templates" / "daily_email_briefing.json"
        )
        self.assertTrue(template_file.exists(), f"File {template_file} non trovato")

        with open(template_file, "r", encoding="utf-8") as f:
            tpl_data = json.load(f)

        # Salva definizione template nel DB di test
        auto_db.save_definition(tpl_data, db_path=self.db_path)

        # Inizia run in modalità dry-run
        run = self.runner.start_run(
            automation_id=tpl_data["id"],
            trigger_type=TriggerType.MANUAL,
            dry_run=True,
        )
        self.assertEqual(run.status, RunStatus.PENDING)
        self.assertTrue(run.is_dry_run)

        # Esecuzione completa del workflow
        finished_run = self.runner.execute_run(run.run_id)
        self.assertEqual(finished_run.status, RunStatus.COMPLETED)
        self.assertIsNone(finished_run.error_message)

        # Verifica che tutti e 4 gli step siano stati eseguiti con successo
        step_runs = auto_db.list_step_runs(run.run_id, db_path=self.db_path)
        self.assertEqual(len(step_runs), 4)

        step_ids = [sr["step_id"] for sr in step_runs]
        self.assertEqual(
            step_ids,
            ["fetch_emails", "triage_emails", "prepare_drafts", "generate_report_artifact"],
        )

        for sr in step_runs:
            self.assertEqual(sr["status"], RunStatus.COMPLETED.value)


if __name__ == "__main__":
    unittest.main()
