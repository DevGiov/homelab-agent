"""Test per gli endpoint REST FastAPI di Automations & Loops."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import config
from automations import db as auto_db
from api import api


class TestAutomationsAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.test_dir, "api_test.db")
        config.AUTOMATIONS_DB_PATH = cls.db_path
        auto_db.init_automations_db(cls.db_path)
        cls.client = TestClient(api)
        cls.headers = {"X-API-Key": config.API_SECRET_KEY} if config.API_SECRET_KEY else {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_crud_and_run_endpoints(self):
        """Test completo: Creazione automazione -> Trigger run -> Query run details."""
        auto_payload = {
            "id": "auto_api_demo",
            "name": "API Demo Automation",
            "description": "Test via REST API",
            "version": 1,
            "enabled": True,
            "workflow": {
                "initial_step_id": "step_main",
                "steps": [
                    {
                        "step_id": "step_main",
                        "name": "Main Step",
                        "type": "deterministic_action",
                        "action_or_tool": "test_echo",
                        "parameters": {"msg": "hello"}
                    }
                ]
            },
            "permission_policy": {
                "allowed_tools": ["test_echo"],
                "security_mode": "normal"
            }
        }

        # 1. Creazione
        res_post = self.client.post("/v1/automations", json=auto_payload, headers=self.headers)
        self.assertEqual(res_post.status_code, 201)
        self.assertEqual(res_post.json()["id"], "auto_api_demo")

        # 2. Elenco
        res_list = self.client.get("/v1/automations", headers=self.headers)
        self.assertEqual(res_list.status_code, 200)
        items = res_list.json()
        self.assertTrue(any(x["id"] == "auto_api_demo" for x in items))

        # 3. Dettaglio
        res_get = self.client.get("/v1/automations/auto_api_demo", headers=self.headers)
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.json()["name"], "API Demo Automation")

        # 4. Trigger Run (Sincrono per test)
        with patch("automations.runner.get_registry_manager") as mock_mgr_factory:
            mock_mgr = MagicMock()
            mock_mgr.execute_tool.return_value = {"reply": "echoed_hello"}
            mock_mgr_factory.return_value = mock_mgr

            res_run = self.client.post(
                "/v1/automations/auto_api_demo/run?sync=true",
                json={"dry_run": False},
                headers=self.headers
            )
            self.assertEqual(res_run.status_code, 202)
            run_data = res_run.json()
            run_id = run_data["run_id"]
            self.assertEqual(run_data["status"], "completed")

        # 5. Query Runs
        res_runs = self.client.get(f"/v1/automations/runs?automation_id=auto_api_demo", headers=self.headers)
        self.assertEqual(res_runs.status_code, 200)
        self.assertTrue(len(res_runs.json()) >= 1)

        # 6. Dettaglio Run
        res_detail = self.client.get(f"/v1/automations/runs/{run_id}", headers=self.headers)
        self.assertEqual(res_detail.status_code, 200)
        detail_data = res_detail.json()
        self.assertEqual(detail_data["status"], "completed")
        self.assertEqual(len(detail_data["step_runs"]), 1)
        self.assertEqual(detail_data["step_runs"][0]["step_id"], "step_main")

    def test_templates_catalog_endpoint(self):
        """Verifica che l'endpoint templates ritorni una lista (anche se vuota o con template)."""
        res = self.client.get("/v1/automations/templates", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json(), list)

    def test_chat_session_approval_resolution_and_deletion(self):
        """Verifica che un'approvazione da chat thread (es. run_id='t_safest') possa essere risolta o eliminata senza errore 400."""
        from datetime import datetime, timedelta, timezone

        # 1. Inserisci approvazione originata da chat (senza run_id reale su automations.db)
        auto_db.create_automation_approval({
            "request_id": "apr_test_chat_1",
            "run_id": "t_safest",
            "tool_name": "exec_lxc_command",
            "arguments": {"vmid": 125, "command": "echo test"},
            "command_preview": "echo test",
            "risk_reason": "Guardrail require approval",
            "status": "pending",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        }, db_path=self.db_path)

        # Risolvi tramite endpoint delle automazioni
        with patch("guardrails.resolve_approval") as mock_resolve:
            mock_resolve.return_value = MagicMock(status="approved")
            res_resolve = self.client.post(
                "/v1/automations/runs/t_safest/approvals/apr_test_chat_1/resolve",
                json={"action": "approve", "resolved_by": "user"},
                headers=self.headers
            )
            self.assertEqual(res_resolve.status_code, 200)
            data = res_resolve.json()
            self.assertIn(data["status"], ["resolved", "approved"])

        # Verifica stato aggiornato su DB
        appr = auto_db.get_automation_approval("apr_test_chat_1", db_path=self.db_path)
        self.assertEqual(appr["status"], "approved")

        # 2. Test eliminazione esplicita
        auto_db.create_automation_approval({
            "request_id": "apr_test_chat_2",
            "run_id": "t_safest",
            "tool_name": "exec_lxc_command",
            "arguments": {"vmid": 125, "command": "echo delete me"},
            "command_preview": "echo delete me",
            "status": "pending",
        }, db_path=self.db_path)

        res_del = self.client.delete("/v1/automations/approvals/apr_test_chat_2", headers=self.headers)
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(res_del.json()["status"], "deleted")
        self.assertIsNone(auto_db.get_automation_approval("apr_test_chat_2", db_path=self.db_path))

    def test_clear_expired_approvals_endpoint(self):
        """Verifica la pulizia massiva delle richieste scadute."""
        auto_db.create_automation_approval({
            "request_id": "apr_past_expired",
            "run_id": "t_chat_past",
            "tool_name": "exec_lxc_command",
            "arguments": {},
            "status": "pending",
            "expires_at": "2020-01-01T00:00:00+00:00",
        }, db_path=self.db_path)

        res_clear = self.client.post("/v1/automations/approvals/clear-expired", headers=self.headers)
        self.assertEqual(res_clear.status_code, 200)
        self.assertGreaterEqual(res_clear.json()["cleared_count"], 1)

        appr = auto_db.get_automation_approval("apr_past_expired", db_path=self.db_path)
        self.assertEqual(appr["status"], "expired")

    def test_automations_registry_tools(self):
        """Verifica che l'AutomationRegistry esponga i tool e ritorni i template canonici."""
        from registry.automations_tool import AutomationRegistry
        reg = AutomationRegistry()
        tools = reg.get_tools()
        tool_names = [t["name"] for t in tools]
        self.assertIn("list_automation_templates", tool_names)
        self.assertIn("list_automations", tool_names)
        self.assertIn("get_automation_details", tool_names)
        self.assertIn("create_automation_from_template", tool_names)

        # Test esecuzione list_automation_templates
        templates = reg.execute_tool("list_automation_templates", {})
        self.assertIsInstance(templates, list)
        tpl_ids = [t["id"] for t in templates]
        self.assertIn("tpl-daily-email-briefing", tpl_ids)
        self.assertIn("tpl-github-issue-repair", tpl_ids)

        # Test alias matching in get_automation_details
        details = reg.execute_tool("get_automation_details", {"automation_id": "tpl_email_briefing"})
        self.assertEqual(details.get("id"), "tpl-daily-email-briefing")

    def test_resolve_approval_create_automation_from_template(self):
        """Verifica che la risoluzione di un'approvazione per create_automation_from_template crei l'automazione senza errore di registry."""
        import guardrails
        req = guardrails.ApprovalRequest(
            request_id="apr_test_tpl_create",
            tool_name="create_automation_from_template",
            arguments={
                "template_id": "tpl-daily-email-briefing",
                "custom_name": "Test Daily Briefing Auto",
                "custom_cron": "0 9 * * *",
                "enabled": True
            },
            thread_id="thread_test_create",
            mode="plan"
        )
        guardrails._APPROVALS[req.request_id] = req

        res = self.client.post(
            f"/v1/approvals/{req.request_id}/resolve",
            json={"action": "approve", "resolved_by": "user"},
            headers=self.headers
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "approved")
        self.assertNotIn("error", data.get("result", {}))
        self.assertEqual(data["result"].get("status"), "created")


if __name__ == "__main__":
    unittest.main()
