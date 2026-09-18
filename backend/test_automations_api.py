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


if __name__ == "__main__":
    unittest.main()
