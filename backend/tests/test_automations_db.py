"""Test di persistenza, concorrenza e transazioni per automations.db."""

import os
import shutil
import tempfile
import threading
import time
import unittest

from automations import db as auto_db


class TestAutomationsDB(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_automations.db")
        auto_db.init_automations_db(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_pragmas_and_wal_mode(self):
        """Verifica che la connessione imposti WAL mode e busy_timeout adeguato."""
        conn = auto_db.get_db_connection(self.db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode;")
        row = cur.fetchone()
        journal_mode = row[0] if row else ""
        self.assertEqual(journal_mode.lower(), "wal")

        cur.execute("PRAGMA busy_timeout;")
        row = cur.fetchone()
        busy_timeout = row[0] if row else 0
        self.assertEqual(busy_timeout, 30000)
        conn.close()

    def test_definition_crud(self):
        """Verifica salvataggio, lettura, toggle e cancellazione di definizioni."""
        auto_data = {
            "id": "auto_test_1",
            "name": "Test Routine",
            "description": "Descrizione di prova",
            "version": 1,
            "enabled": True,
            "workflow": {
                "initial_step_id": "s1",
                "steps": [{"step_id": "s1", "name": "Step 1", "type": "deterministic_action"}]
            },
            "created_by": "tester"
        }
        saved = auto_db.save_definition(auto_data, db_path=self.db_path)
        self.assertEqual(saved["id"], "auto_test_1")

        loaded = auto_db.get_definition("auto_test_1", db_path=self.db_path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["name"], "Test Routine")
        self.assertTrue(loaded["enabled"])

        # Toggle enabled
        auto_db.set_definition_enabled("auto_test_1", False, db_path=self.db_path)
        updated = auto_db.get_definition("auto_test_1", db_path=self.db_path)
        self.assertFalse(updated["enabled"])

        # List
        all_defs = auto_db.list_definitions(db_path=self.db_path)
        self.assertEqual(len(all_defs), 1)

        # Delete
        del_res = auto_db.delete_definition("auto_test_1", db_path=self.db_path)
        self.assertTrue(del_res)
        self.assertIsNone(auto_db.get_definition("auto_test_1", db_path=self.db_path))

    def test_run_and_step_run_lifecycle(self):
        """Verifica creazione run, aggiornamento stato, tracciamento step e artefatti."""
        # Creiamo prima una definizione genitore
        auto_db.save_definition({
            "id": "auto_parent",
            "name": "Parent",
            "workflow": {"steps": []}
        }, db_path=self.db_path)

        run_data = {
            "run_id": "run_001",
            "automation_id": "auto_parent",
            "version_applied": 1,
            "trigger_type": "manual",
            "trigger_payload": {"key": "val"},
            "status": "pending",
            "idempotency_key": "idemp_test_001",
            "is_dry_run": False
        }
        auto_db.create_run(run_data, db_path=self.db_path)

        # Idempotency check
        dup_run = auto_db.get_run_by_idempotency_key("idemp_test_001", db_path=self.db_path)
        self.assertIsNotNone(dup_run)
        self.assertEqual(dup_run["run_id"], "run_001")

        # Step 1
        auto_db.save_step_run({
            "step_run_id": "sr_1",
            "run_id": "run_001",
            "step_id": "step_fetch",
            "status": "completed",
            "started_at": "2026-09-18T00:00:00Z",
            "completed_at": "2026-09-18T00:00:02Z",
            "input_payload": {"limit": 10},
            "output_payload": {"items": [1, 2, 3]},
            "tokens_consumed": 150
        }, db_path=self.db_path)

        # Artifact
        auto_db.save_artifact({
            "artifact_id": "art_1",
            "run_id": "run_001",
            "step_run_id": "sr_1",
            "name": "report.md",
            "type": "report",
            "storage_uri": "/data/artifacts/run_001/report.md",
            "checksum_sha256": "abc123"
        }, db_path=self.db_path)

        # Update run status
        auto_db.update_run_status("run_001", "completed", total_tokens=150, total_duration_ms=2000, db_path=self.db_path)

        # Verifica stato completo del run
        full_run = auto_db.get_run("run_001", db_path=self.db_path)
        self.assertIsNotNone(full_run)
        self.assertEqual(full_run["status"], "completed")
        self.assertEqual(len(full_run["step_runs"]), 1)
        self.assertEqual(full_run["step_runs"][0]["step_id"], "step_fetch")
        self.assertEqual(len(full_run["artifacts"]), 1)
        self.assertEqual(full_run["artifacts"][0]["name"], "report.md")
        self.assertEqual(full_run["artifacts"][0]["title"], "report.md")

        # Verifica salvataggio resiliente senza run pre-esistente (nessuna violazione FK)
        standalone_art = auto_db.save_artifact({
            "artifact_id": "art_standalone",
            "run_id": "manual_or_direct",
            "name": "manual_report.md",
            "storage_uri": "/tmp/test.md"
        }, db_path=self.db_path)
        self.assertEqual(standalone_art["artifact_id"], "art_standalone")
        saved_art = auto_db.get_artifact("art_standalone", db_path=self.db_path)
        self.assertIsNotNone(saved_art)
        self.assertEqual(saved_art["title"], "manual_report.md")

    def test_approval_persistence_and_resolution(self):
        """Verifica creazione, query e risoluzione delle approvazioni persistenti."""
        from datetime import datetime, timedelta, timezone
        appr_data = {
            "request_id": "apr_test_persist",
            "run_id": "run_999",
            "step_run_id": "sr_999",
            "tool_name": "exec_lxc_command",
            "arguments": {"command": "systemctl restart nginx"},
            "command_preview": "systemctl restart nginx",
            "command_prefix": "systemctl restart",
            "risk_reason": "Comando di sistema",
            "status": "pending",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        }
        auto_db.create_automation_approval(appr_data, db_path=self.db_path)

        # Query pending
        pendings = auto_db.list_pending_approvals(db_path=self.db_path)
        self.assertEqual(len(pendings), 1)
        self.assertEqual(pendings[0]["request_id"], "apr_test_persist")

        # Resolve approve
        resolved = auto_db.resolve_automation_approval("apr_test_persist", "approve", resolved_by="admin", db_path=self.db_path)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["status"], "approved")
        self.assertEqual(resolved["resolved_by"], "admin")

        # Query pending di nuovo: deve essere vuota
        pendings_after = auto_db.list_pending_approvals(db_path=self.db_path)
        self.assertEqual(len(pendings_after), 0)

    def test_concurrent_multithreaded_writes(self):
        """Verifica che 10 thread simultanei possano scrivere su SQLite in WAL mode senza collisioni."""
        auto_db.save_definition({
            "id": "auto_concurrent",
            "name": "Concurrent Parent",
            "workflow": {"steps": []}
        }, db_path=self.db_path)

        errors = []

        def worker(thread_idx: int):
            try:
                run_id = f"run_thread_{thread_idx}"
                auto_db.create_run({
                    "run_id": run_id,
                    "automation_id": "auto_concurrent",
                    "status": "running",
                    "idempotency_key": f"key_{thread_idx}"
                }, db_path=self.db_path)

                for step_idx in range(5):
                    auto_db.save_step_run({
                        "step_run_id": f"sr_{thread_idx}_{step_idx}",
                        "run_id": run_id,
                        "step_id": f"step_{step_idx}",
                        "status": "completed",
                        "tokens_consumed": 10
                    }, db_path=self.db_path)
                    time.sleep(0.01)

                auto_db.update_run_status(run_id, "completed", total_tokens=50, db_path=self.db_path)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Errori di concorrenza rilevati: {errors}")
        runs = auto_db.list_runs(automation_id="auto_concurrent", limit=100, db_path=self.db_path)
        self.assertEqual(len(runs), 10)


if __name__ == "__main__":
    unittest.main()
