"""Test di sicurezza e governance per Automations & Loops (Milestone M4).

Verifica:
- Correlazione tracciata in audit_log (automation_id, run_id, step_run_id)
- Scatto e sblocco del Circuit Breaker su fallimenti ripetuti
- Rate limiting orario del Circuit Breaker
- Blocco rigido di tool non autorizzati dalla permission policy
"""

import os
import tempfile
import time
import unittest
from unittest.mock import patch

import audit_log
from automations import db as auto_db
from automations.circuit_breaker import CircuitBreakerManager, CircuitState
from automations.models import AutomationDefinition, RunStatus, TriggerType
from automations.runner import AutomationRunner


class TestAutomationsGovernanceAndSecurity(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_gov.db")
        auto_db.init_automations_db(self.db_path)
        self.runner = AutomationRunner(db_path=self.db_path)
        self.cb = CircuitBreakerManager(db_path=self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_audit_log_correlation_fields(self):
        """Verifica che ogni tool invocato da un'automazione registri correlation IDs in audit_log."""
        auto_payload = {
            "id": "auto_audit_corr_test",
            "name": "Audit Correlation Test",
            "enabled": True,
            "triggers": [{"id": "trg_manual", "type": "manual"}],
            "workflow": {
                "initial_step_id": "step_fetch",
                "steps": [
                    {
                        "step_id": "step_fetch",
                        "name": "Fetch Emails",
                        "type": "deterministic_action",
                        "action_or_tool": "email_fetch_unread",
                        "parameters": {"max_emails": 2},
                    }
                ],
            },
            "permission_policy": {
                "allowed_tools": ["email_fetch_unread"],
                "allowed_registries": ["email"],
            },
        }
        auto_db.save_definition(auto_payload, db_path=self.db_path)

        # Esecuzione run
        run = self.runner.start_run("auto_audit_corr_test", trigger_type=TriggerType.MANUAL, dry_run=False)
        finished_run = self.runner.execute_run(run.run_id)
        self.assertEqual(finished_run.status, RunStatus.COMPLETED)

        # Ispezione audit_log
        recent_logs = audit_log.get_recent(limit=10, run_id=run.run_id)
        self.assertGreater(len(recent_logs), 0)

        corr_entry = recent_logs[0]
        self.assertEqual(corr_entry["tool_name"], "email_fetch_unread")
        self.assertEqual(corr_entry["automation_id"], "auto_audit_corr_test")
        self.assertEqual(corr_entry["run_id"], run.run_id)
        self.assertEqual(corr_entry["step_run_id"], f"sr_{run.run_id}_step_fetch")

    def test_circuit_breaker_trips_on_consecutive_failures(self):
        """Verifica che 3 fallimenti consecutivi facciano scattare il Circuit Breaker a OPEN."""
        auto_id = "auto_failing_service"
        auto_payload = {
            "id": auto_id,
            "name": "Failing Service Test",
            "enabled": True,
            "triggers": [{"id": "trg_m", "type": "manual"}],
            "workflow": {
                "initial_step_id": "step_bad",
                "steps": [
                    {
                        "step_id": "step_bad",
                        "name": "Step Errato",
                        "type": "deterministic_action",
                        "action_or_tool": "non_existent_tool_xyz",
                    }
                ],
            },
            "permission_policy": {
                "allowed_tools": ["non_existent_tool_xyz"],
                "allowed_registries": ["email"],
            },
        }
        auto_db.save_definition(auto_payload, db_path=self.db_path)

        # 3 esecuzioni consecutive fallite
        for i in range(3):
            run = self.runner.start_run(auto_id, trigger_type=TriggerType.MANUAL)
            self.assertEqual(run.status, RunStatus.PENDING)
            res = self.runner.execute_run(run.run_id)
            self.assertEqual(res.status, RunStatus.FAILED)

        # Verifica stato circuit breaker: deve essere OPEN
        cb_status = self.cb.get_status(auto_id)
        self.assertEqual(cb_status["state"], CircuitState.OPEN.value)
        self.assertEqual(cb_status["consecutive_failures"], 3)
        self.assertIsNotNone(cb_status["tripped_at"])

        # Il 4 tentativo deve essere bloccato istantaneamente in start_run (status BLOCKED)
        blocked_run = self.runner.start_run(auto_id, trigger_type=TriggerType.MANUAL)
        self.assertEqual(blocked_run.status, RunStatus.BLOCKED)
        self.assertIn("Circuit Breaker APERTO", blocked_run.error_message)

        # Reset manuale del circuit breaker
        self.cb.reset(auto_id)
        reset_status = self.cb.get_status(auto_id)
        self.assertEqual(reset_status["state"], CircuitState.CLOSED.value)
        self.assertEqual(reset_status["consecutive_failures"], 0)

        # Ora start_run torna a consentire la creazione in stato PENDING
        resumed_run = self.runner.start_run(auto_id, trigger_type=TriggerType.MANUAL)
        self.assertEqual(resumed_run.status, RunStatus.PENDING)

    def test_circuit_breaker_rate_limiting(self):
        """Verifica il blocco di sicurezza se si supera il tetto massimo di run/ora."""
        auto_id = "auto_rate_test"
        auto_payload = {
            "id": auto_id,
            "name": "Rate Limit Test",
            "enabled": True,
            "triggers": [{"id": "trg_m", "type": "manual"}],
            "workflow": {
                "initial_step_id": "step_1",
                "steps": [
                    {
                        "step_id": "step_1",
                        "name": "Nop Step",
                        "type": "deterministic_action",
                        "action_or_tool": "save_briefing_artifact",
                        "parameters": {"title": "Test"},
                    }
                ],
            },
            "permission_policy": {
                "allowed_tools": ["save_briefing_artifact"],
                "allowed_registries": ["email"],
            },
        }
        auto_db.save_definition(auto_payload, db_path=self.db_path)

        # Configura limite ridotto per il test (es. 2 run/ora)
        allowed, _ = self.cb.check_execution_allowed(auto_id, max_runs_per_hour=2)
        self.assertTrue(allowed)

        # Inserisce 2 run
        for _ in range(2):
            r = self.runner.start_run(auto_id, trigger_type=TriggerType.MANUAL)
            self.runner.execute_run(r.run_id)

        # Ora con soglia 2, una nuova esecuzione deve essere rifiutata per rate limit
        allowed_after, reason = self.cb.check_execution_allowed(auto_id, max_runs_per_hour=2)
        self.assertFalse(allowed_after)
        self.assertIn("Rate limit orario superato", reason)

    def test_unauthorized_tool_strictly_blocked(self):
        """Verifica che uno step che tenta di invocare un tool non in allowlist venga bloccato da policy."""
        auto_payload = {
            "id": "auto_security_policy_test",
            "name": "Security Policy Test",
            "enabled": True,
            "triggers": [{"id": "trg_manual", "type": "manual"}],
            "workflow": {
                "initial_step_id": "step_forbidden",
                "steps": [
                    {
                        "step_id": "step_forbidden",
                        "name": "Comando Pericoloso Non Autorizzato",
                        "type": "deterministic_action",
                        "action_or_tool": "exec_host_command",
                        "parameters": {"command": "reboot"},
                    }
                ],
            },
            "permission_policy": {
                # Solo save_briefing_artifact è concesso, exec_host_command NON è in allowlist
                "allowed_tools": ["save_briefing_artifact"],
                "allowed_registries": ["email"],
            },
        }
        auto_db.save_definition(auto_payload, db_path=self.db_path)

        run = self.runner.start_run("auto_security_policy_test", trigger_type=TriggerType.MANUAL)
        finished_run = self.runner.execute_run(run.run_id)

        # La run deve fallire con errore di autorizzazione
        self.assertEqual(finished_run.status, RunStatus.FAILED)
        self.assertIn("non autorizzato dalla policy dell'automazione", finished_run.error_message)


if __name__ == "__main__":
    unittest.main()
