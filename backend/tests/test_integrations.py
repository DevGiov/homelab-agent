"""Unit test per modulo Integrazioni, Cifratura Credenziali, Parametri e Tool Automazioni."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from automations.db import init_automations_db, get_definition
from automations.models import AutomationDefinition
from automations.runner import AutomationRunner, _render_template
from integrations.manager import (
    IntegrationManager,
    encrypt_secrets,
    decrypt_secrets,
    mask_secrets,
    get_integration_manager,
)
from registry.manager import get_registry_manager


class TestIntegrationsAndParameters(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_integrations.db")
        init_automations_db(self.db_path)
        self.mgr = IntegrationManager(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_encryption_and_decryption(self):
        secrets = {"imap_password": "MySuperSecretPassword123!", "api_token": "ghp_abc123"}
        encrypted = encrypt_secrets(secrets)
        self.assertNotEqual(encrypted, "{}")
        self.assertNotIn("MySuperSecretPassword123!", encrypted)

        decrypted = decrypt_secrets(encrypted)
        self.assertEqual(decrypted, secrets)

    def test_mask_secrets(self):
        secrets = {"imap_password": "Secret", "token": ""}
        masked = mask_secrets(secrets)
        self.assertEqual(masked["imap_password"], "••••••••")
        self.assertTrue(masked["has_imap_password"])
        self.assertEqual(masked["token"], "")
        self.assertFalse(masked["has_token"])

    def test_crud_integration(self):
        data = {
            "id": "email_fastmail",
            "service_type": "email",
            "name": "Fastmail Personale",
            "config": {"imap_host": "imap.fastmail.com", "imap_port": 993, "imap_user": "user@fastmail.com"},
            "secrets": {"imap_password": "app-specific-pwd"},
        }
        saved = self.mgr.save_integration(data)
        self.assertEqual(saved["id"], "email_fastmail")
        self.assertEqual(saved["secrets"]["imap_password"], "••••••••")
        self.assertTrue(saved["secrets"]["has_imap_password"])

        # Recupero con decrypt=True
        detail = self.mgr.get_integration("email_fastmail", decrypt=True)
        self.assertEqual(detail["secrets"]["imap_password"], "app-specific-pwd")

        # Verifica lista
        items = self.mgr.list_integrations()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], "email_fastmail")

        # Eliminazione
        del_res = self.mgr.delete_integration("email_fastmail")
        self.assertTrue(del_res)
        self.assertIsNone(self.mgr.get_integration("email_fastmail"))

    @patch("imaplib.IMAP4_SSL")
    def test_email_connection_test_success(self, mock_imap_ssl):
        # Mock IMAP
        mock_instance = MagicMock()
        mock_instance.select.return_value = ("OK", [b"42"])
        mock_imap_ssl.return_value = mock_instance

        self.mgr.save_integration({
            "id": "email_test_ok",
            "service_type": "email",
            "name": "Test IMAP",
            "config": {"imap_host": "mail.example.com", "imap_port": 993, "imap_user": "user@test.local"},
            "secrets": {"imap_password": "correct_password"},
        })

        res = self.mgr.test_connection("email_test_ok")
        self.assertTrue(res["success"])
        self.assertIn("INBOX contiene 42 messaggi", res["message"])

        # Verifica che lo stato sia stato aggiornato nel DB
        item = self.mgr.get_integration("email_test_ok")
        self.assertEqual(item["status"], "connected")

    def test_render_template_dynamic_variables_and_config(self):
        context = {
            "inputs": {"category": "cs.AI", "limit": 5},
            "config": {"category": "cs.AI"},
            "run_id": "run_12345",
            "steps": {"fetch": {"output": {"count": 10}}},
        }
        rendered = _render_template(
            "Cerca {{inputs.category}} con max {{inputs.limit}} su data {{date}} per run {{run_id}} e output {{steps.fetch.output.count}}.",
            context
        )
        self.assertIn("cs.AI", rendered)
        self.assertIn("max 5", rendered)
        self.assertIn("run_12345", rendered)
        self.assertIn("output 10", rendered)

        # Test shell date syntax normalization
        shell_path = "/homelab/reports/ai-papers-briefing-$(date +%Y-%m-%d).md"
        norm_path = _render_template(shell_path, context)
        self.assertNotIn("$(date", norm_path)
        self.assertTrue(norm_path.startswith("/homelab/reports/ai-papers-briefing-20"))

    def test_automation_definition_with_parameters(self):
        raw_def = {
            "id": "auto_test_params",
            "name": "Test Parameters",
            "parameters": {"email": "alert@homelab.local", "threshold": 80},
            "workflow": [
                {
                    "step_id": "step_1",
                    "action": "http_get",
                    "params": {"url": "https://example.com/api?th={{inputs.threshold}}"}
                }
            ]
        }
        auto_def = AutomationDefinition(**raw_def)
        self.assertEqual(auto_def.parameters["email"], "alert@homelab.local")
        self.assertEqual(auto_def.parameters["threshold"], 80)
        self.assertEqual(auto_def.workflow.steps[0].action_or_tool, "http_get")
        self.assertIn("http_get", auto_def.permission_policy.allowed_tools)

    def test_template_auto_expansion(self):
        # Quando un LLM passa un template come action
        raw_def = {
            "id": "auto_from_tpl_name",
            "name": "Briefing Mattutino Test",
            "workflow": [
                {
                    "name": "Genera Briefing",
                    "action": "daily_email_briefing"
                }
            ]
        }
        auto_def = AutomationDefinition(**raw_def)
        # Deve essere stato espanso nei 4 step reali del template
        self.assertGreaterEqual(len(auto_def.workflow.steps), 3)
        step_tools = [s.action_or_tool for s in auto_def.workflow.steps if s.action_or_tool]
        self.assertIn("email_fetch_unread", step_tools)

    def test_http_get_tool(self):
        reg_mgr = get_registry_manager()
        # Test con un endpoint mock o httpbin/arxiv
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.headers = {"Content-Type": "application/json"}
            mock_resp.read.return_value = b'{"status": "ok", "items": [1, 2, 3]}'
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            res = reg_mgr.execute_tool(
                "http_get",
                {"url": "https://export.arxiv.org/api/query"},
                allowed_registries=["web"]
            )
            self.assertEqual(res.get("status"), 200)
            self.assertEqual(res.get("data"), {"status": "ok", "items": [1, 2, 3]})


if __name__ == "__main__":
    unittest.main()
