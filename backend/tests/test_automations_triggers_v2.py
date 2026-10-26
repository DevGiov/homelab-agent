"""Test unitari per le feature v2 avanzate:
1. Toggle slider di attivazione/disattivazione card
2. Endpoint Webhook HTTP token-based (unauthenticated X-API-Key)
3. Modifica diretta dei trigger (schedulazione e webhook)
4. Rigenerazione token webhook
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

import config
from automations import db as auto_db
from api import api


class TestAutomationsTriggersV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.test_dir, "test_triggers_v2.db")
        config.AUTOMATIONS_DB_PATH = cls.db_path
        auto_db.init_automations_db(cls.db_path)
        cls.client = TestClient(api)
        cls.headers = {"X-API-Key": config.API_SECRET_KEY} if config.API_SECRET_KEY else {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_toggle_automation_enabled(self):
        """Verifica il funzionamento dell'endpoint PATCH /v1/automations/{id}/toggle."""
        auto_payload = {
            "id": "auto_test_toggle",
            "name": "Test Toggle Auto",
            "version": 1,
            "enabled": True,
            "workflow": {
                "initial_step_id": "s1",
                "steps": [{"step_id": "s1", "name": "Step 1", "type": "deterministic_action"}]
            },
            "triggers": [{"id": "trg_1", "type": "cron", "cron_expression": "0 10 * * *"}]
        }
        res = self.client.post("/v1/automations", json=auto_payload, headers=self.headers)
        self.assertEqual(res.status_code, 201)

        # 1. Toggle to disabled (no body) -> inverts True to False
        res = self.client.patch("/v1/automations/auto_test_toggle/toggle", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["enabled"])

        # Check DB
        d = auto_db.get_definition("auto_test_toggle", db_path=self.db_path)
        self.assertFalse(d["enabled"])

        # 2. Toggle explicitly with payload -> set to True
        res = self.client.patch(
            "/v1/automations/auto_test_toggle/toggle",
            json={"enabled": True},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["enabled"])

        d = auto_db.get_definition("auto_test_toggle", db_path=self.db_path)
        self.assertTrue(d["enabled"])

    def test_update_triggers_directly(self):
        """Verifica l'endpoint PUT /v1/automations/{id}/triggers."""
        auto_payload = {
            "id": "auto_test_triggers_put",
            "name": "Test Triggers PUT",
            "version": 1,
            "enabled": True,
            "workflow": {
                "initial_step_id": "s1",
                "steps": [{"step_id": "s1", "name": "Step 1", "type": "deterministic_action"}]
            },
            "triggers": [{"id": "trg_1", "type": "cron", "cron_expression": "0 9 * * *"}]
        }
        self.client.post("/v1/automations", json=auto_payload, headers=self.headers)

        # Aggiornamento valido a ore 15:30
        new_triggers = [
            {"id": "trg_cron_main", "type": "cron", "cron_expression": "30 15 * * *", "timezone": "Europe/Rome"},
            {"id": "trg_wh_1", "type": "webhook", "webhook_token": "secret_wh_token_123"}
        ]
        res = self.client.put("/v1/automations/auto_test_triggers_put/triggers", json=new_triggers, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        saved_triggers = data["triggers"]
        self.assertEqual(len(saved_triggers), 2)
        self.assertEqual(saved_triggers[0]["cron_expression"], "30 15 * * *")
        self.assertEqual(saved_triggers[1]["webhook_token"], "secret_wh_token_123")

        # Test validazione cron non valida -> 400 Bad Request
        bad_triggers = [{"type": "cron", "cron_expression": "not a valid cron expression"}]
        res = self.client.put("/v1/automations/auto_test_triggers_put/triggers", json=bad_triggers, headers=self.headers)
        self.assertEqual(res.status_code, 400)

    def test_webhook_trigger_unauthenticated_and_payload(self):
        """Verifica che l'endpoint POST /v1/automations/{id}/webhook/{token} funzioni senza X-API-Key."""
        wh_token = "my_custom_webhook_secret_999"
        auto_payload = {
            "id": "auto_test_webhook_exec",
            "name": "Test Webhook Exec",
            "version": 1,
            "enabled": True,
            "workflow": {
                "initial_step_id": "s1",
                "steps": [{"step_id": "s1", "name": "Step 1", "type": "deterministic_action"}]
            },
            "triggers": [
                {"id": "trg_wh", "type": "webhook", "webhook_token": wh_token}
            ]
        }
        self.client.post("/v1/automations", json=auto_payload, headers=self.headers)

        # 1. Chiamata con token corretto SENZA header X-API-Key (simula client esterno)
        event_body = {
            "event": "alert_fired",
            "severity": "critical",
            "inputs": {"target_host": "192.168.1.50"}
        }
        res = self.client.post(
            f"/v1/automations/auto_test_webhook_exec/webhook/{wh_token}",
            json=event_body,
            headers={}  # Zero auth header!
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertTrue("run_id" in data)

        # Verifica che la run sia registrata con trigger_type webhook
        run_id = data["run_id"]
        run_res = self.client.get(f"/v1/automations/runs/{run_id}", headers=self.headers)
        self.assertEqual(run_res.status_code, 200)
        run_data = run_res.json()
        self.assertEqual(run_data["trigger_type"], "webhook")
        self.assertEqual(run_data["trigger_payload"]["source"], "webhook")
        self.assertEqual(run_data["trigger_payload"]["webhook_payload"]["event"], "alert_fired")

        # 2. Chiamata con token ERRATO -> 401 Unauthorized
        res = self.client.post(
            "/v1/automations/auto_test_webhook_exec/webhook/wrong_token",
            json=event_body,
            headers={}
        )
        self.assertEqual(res.status_code, 401)

        # 3. Chiamata quando l'automazione è DISABILITATA -> 403 Forbidden
        self.client.patch("/v1/automations/auto_test_webhook_exec/toggle", json={"enabled": False}, headers=self.headers)
        res = self.client.post(
            f"/v1/automations/auto_test_webhook_exec/webhook/{wh_token}",
            json=event_body,
            headers={}
        )
        self.assertEqual(res.status_code, 403)

    def test_webhook_regenerate_token(self):
        """Verifica POST /v1/automations/{id}/webhook-regenerate."""
        auto_payload = {
            "id": "auto_test_wh_regen",
            "name": "Test Webhook Regen",
            "version": 1,
            "enabled": True,
            "workflow": {
                "initial_step_id": "s1",
                "steps": [{"step_id": "s1", "name": "Step 1", "type": "deterministic_action"}]
            },
            "triggers": [
                {"id": "trg_wh", "type": "webhook", "webhook_token": "initial_token_111"}
            ]
        }
        self.client.post("/v1/automations", json=auto_payload, headers=self.headers)

        res = self.client.post("/v1/automations/auto_test_wh_regen/webhook-regenerate", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        new_tok = data["webhook_token"]
        self.assertNotEqual(new_tok, "initial_token_111")
        self.assertTrue(new_tok in data["webhook_path"])

        # Il vecchio token deve ora fallire
        res_old = self.client.post("/v1/automations/auto_test_wh_regen/webhook/initial_token_111", json={}, headers={})
        self.assertEqual(res_old.status_code, 401)

        # Il nuovo token deve funzionare
        res_new = self.client.post(f"/v1/automations/auto_test_wh_regen/webhook/{new_tok}", json={}, headers={})
        self.assertEqual(res_new.status_code, 200)


if __name__ == "__main__":
    unittest.main()
