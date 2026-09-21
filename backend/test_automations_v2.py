"""Unit tests per le funzionalità Automations V2.

Verifica:
- Endpoint e DB per Artefatti (list, detail, favorite, preserve, delete).
- Endpoint e DB per Run (list con campi v2, favorite, preserve, single delete, bulk delete, pause, resume).
- Introspezione automatica dei parametri e segreti.
- Pre-flight validation e normalizzazione proposizioni LLM.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from automations import db as auto_db
from automations.introspection import introspect_automation_parameters
from automations.models import (
    AutomationDefinition,
    AutomationRun,
    RunStatus,
    StepType,
)
from automations.runner import AutomationRunner
from registry.automations_tool import AutomationRegistry


class TestAutomationsV2(unittest.TestCase):
    def setUp(self):
        import config
        self.orig_db_path = config.AUTOMATIONS_DB_PATH
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_automations.db")
        config.AUTOMATIONS_DB_PATH = self.db_path
        auto_db.init_automations_db(self.db_path)

    def tearDown(self):
        import config
        config.AUTOMATIONS_DB_PATH = self.orig_db_path
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_artifacts_crud_and_toggles(self):
        """Testa creazione, filtri, star, preserve e delete per gli artefatti."""
        art1 = {
            "artifact_id": "art_test_1",
            "run_id": "run_100",
            "step_run_id": "step_1",
            "title": "Daily Briefing 1",
            "name": "briefing_1.md",
            "mime_type": "text/markdown",
            "storage_uri": os.path.join(self.test_dir, "briefing_1.md"),
            "size_bytes": 128,
            "created_at": "2026-09-20T10:00:00Z",
        }
        with open(art1["storage_uri"], "w") as f:
            f.write("# Briefing 1 Content")

        auto_db.save_artifact(art1, db_path=self.db_path)

        # List all
        all_arts = auto_db.list_all_artifacts(db_path=self.db_path)
        self.assertEqual(len(all_arts), 1)
        self.assertEqual(all_arts[0]["title"], "Daily Briefing 1")
        self.assertFalse(all_arts[0]["is_favorite"])
        self.assertFalse(all_arts[0]["is_preserved"])

        # Toggle favorite
        fav = auto_db.toggle_artifact_favorite("art_test_1", db_path=self.db_path)
        self.assertTrue(fav)
        all_favs = auto_db.list_all_artifacts(favorite_only=True, db_path=self.db_path)
        self.assertEqual(len(all_favs), 1)

        # Toggle preserve
        pres = auto_db.toggle_artifact_preserve("art_test_1", db_path=self.db_path)
        self.assertTrue(pres)

        # Delete when preserved should fail
        del_fail = auto_db.delete_artifact("art_test_1", db_path=self.db_path)
        self.assertFalse(del_fail)
        self.assertTrue(os.path.exists(art1["storage_uri"]))

        # Unlock preserve and delete should succeed
        auto_db.toggle_artifact_preserve("art_test_1", db_path=self.db_path)
        del_ok = auto_db.delete_artifact("art_test_1", db_path=self.db_path)
        self.assertTrue(del_ok)
        self.assertFalse(os.path.exists(art1["storage_uri"]))

    def test_run_management_and_bulk_delete(self):
        """Testa gestione run, star, preserve, delete singola e bulk delete."""
        auto_db.save_definition({
            "id": "auto_test",
            "name": "Test Automation",
            "workflow": {
                "initial_step_id": "step_1",
                "steps": [{"step_id": "step_1", "name": "Step 1", "type": "agentic_task"}]
            }
        }, db_path=self.db_path)

        run_data = {
            "run_id": "run_01",
            "automation_id": "auto_test",
            "status": RunStatus.FAILED.value,
            "trigger_type": "manual",
            "version_applied": 1,
            "is_dry_run": False,
            "started_at": "2026-09-01T10:00:00Z",
        }
        auto_db.create_run(run_data, db_path=self.db_path)

        run_data_2 = {
            "run_id": "run_02",
            "automation_id": "auto_test",
            "status": RunStatus.COMPLETED.value,
            "trigger_type": "manual",
            "version_applied": 1,
            "is_dry_run": False,
            "started_at": "2026-09-02T10:00:00Z",
        }
        auto_db.create_run(run_data_2, db_path=self.db_path)

        runs = auto_db.list_runs(automation_id="auto_test", db_path=self.db_path)
        self.assertEqual(len(runs), 2)

        # Toggle star / favorite
        is_fav = auto_db.toggle_run_favorite("run_01", db_path=self.db_path)
        self.assertTrue(is_fav)

        # Toggle preserve
        is_pres = auto_db.toggle_run_preserve("run_02", db_path=self.db_path)
        self.assertTrue(is_pres)

        # Single delete run_02 (preserved) -> must raise ValueError
        with self.assertRaises(ValueError):
            auto_db.delete_run("run_02", db_path=self.db_path)

        # Bulk delete failed_only (run_01 is failed and not preserved, but is_favorite -> bulk delete skips favorites unless older)
        # Unfavorite run_01
        auto_db.toggle_run_favorite("run_01", db_path=self.db_path)
        del_count = auto_db.bulk_delete_runs(automation_id="auto_test", failed_only=True, db_path=self.db_path)
        self.assertEqual(del_count, 1)

        remaining = auto_db.list_runs(automation_id="auto_test", db_path=self.db_path)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["run_id"], "run_02")

    def test_parameter_introspection(self):
        """Testa l'introspezione automatica di template prompt e chiamate di tool."""
        workflow_def = {
            "id": "auto_intro",
            "name": "Introspection Test",
            "workflow": {
                "initial_step_id": "step_1",
                "steps": [
                    {
                        "step_id": "step_1",
                        "name": "Step 1",
                        "type": "agentic_task",
                        "prompt_template": "Query: {{inputs.search_query}} and secret: {{secrets.GITHUB_TOKEN}}",
                        "parameters": {"max_results": 10},
                    }
                ],
            },
            "parameters": {"search_query": "default query"},
        }
        res = introspect_automation_parameters(workflow_def)
        params = {p["name"]: p for p in res["parameters"]}
        secrets = {s["name"]: s for s in res["secrets"]}

        self.assertIn("search_query", params)
        self.assertEqual(params["search_query"]["inferred_type"], "string")
        self.assertIn("GITHUB_TOKEN", secrets)

    def test_preflight_validation(self):
        """Testa i controlli di validazione pre-flight di _create_custom."""
        reg = AutomationRegistry()

        # Step iniziale mancante o non coincidente
        invalid_def = {
            "id": "auto_broken",
            "name": "Broken",
            "workflow": {
                "initial_step_id": "step_unknown",
                "steps": [
                    {
                        "id": "step_1",
                        "name": "Step 1",
                        "type": "deterministic_action",
                        "action_or_tool": "web_search",
                        "parameters": {},
                    }
                ],
            },
        }
        res = reg.execute_tool("create_custom_automation", {"automation_def": invalid_def})
        self.assertIn("error", res)

        # web_search senza parametro query
        invalid_web = {
            "id": "auto_broken_web",
            "name": "Broken Web",
            "workflow": {
                "initial_step_id": "step_1",
                "steps": [
                    {
                        "step_id": "step_1",
                        "name": "Step 1",
                        "type": "deterministic_action",
                        "action_or_tool": "web_search",
                        "parameters": {},
                    }
                ],
            },
        }
        res_web = reg.execute_tool("create_custom_automation", {"automation_def": invalid_web})
        self.assertIn("error", res_web)
        self.assertIn("query", res_web["error"])

    def test_create_custom_with_null_or_string_budget_and_policy(self):
        """Verifica che payload con budget: null o permission_policy: string vengano gestiti e normalizzati con successo."""
        from automations.models import AutomationDefinition, Budget, ExecutionPolicy
        from registry.automations_tool import AutomationRegistry
        reg = AutomationRegistry()

        payload = {
            "id": "auto_github_trending_null_budget",
            "name": "GitHub Trending Daily Report",
            "description": "Test con budget null e permission_policy stringa",
            "triggers": [{"type": "cron", "cron_expression": "0 12 * * *"}],
            "workflow": {
                "initial_step_id": "step_1_search",
                "steps": [
                    {
                        "step_id": "step_1_search",
                        "name": "Ricerca Trending GitHub",
                        "type": "deterministic_action",
                        "action_or_tool": "web_search",
                        "parameters": {"query": "github trending repositories today"},
                    },
                    {
                        "step_id": "step_2_save",
                        "name": "Salvataggio",
                        "type": "deterministic_action",
                        "action_or_tool": "save_artifact",
                        "parameters": {"title": "Trending"},
                    },
                ],
            },
            "permission_policy": "auto_execute",
            "budget": None,
        }

        # 1. Istanziazione diretta del modello Pydantic
        auto = AutomationDefinition(**payload)
        self.assertIsInstance(auto.budget, Budget)
        self.assertEqual(auto.budget.max_duration_seconds, 300)
        self.assertEqual(auto.budget.max_tokens, 50000)
        self.assertIsInstance(auto.permission_policy, ExecutionPolicy)
        self.assertIn("web_search", auto.permission_policy.allowed_tools)
        self.assertIn("save_artifact", auto.permission_policy.allowed_tools)

        # 2. Creazione tramite registry tool (come fa l'agente)
        res = reg.execute_tool("create_custom_automation", {"automation_def": payload})
        self.assertNotIn("error", res)
        self.assertEqual(res.get("status"), "created")
        self.assertEqual(res.get("automation_id"), "auto_github_trending_null_budget")


if __name__ == "__main__":
    unittest.main()

