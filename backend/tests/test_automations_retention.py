"""Test di retention e cancellazione massiva delle run (DB, scheduler, API REST)."""

import os
import shutil
import tempfile
import unittest

from fastapi.testclient import TestClient

from app.api.main import api
from app.automations.db import connection as connection_db
from app.automations.db import definitions as definitions_db
from app.automations.db import runs as runs_db
from app.automations.db import schema as schema_db
from app.automations.scheduler import AutomationScheduler
from app.core import config


def _make_definition(auto_id: str, retention_days=None) -> dict:
    return {
        "id": auto_id,
        "name": f"Retention {auto_id}",
        "version": 1,
        "enabled": True,
        "retention_days": retention_days,
        "workflow": {
            "initial_step_id": "s1",
            "steps": [{"step_id": "s1", "name": "Step 1", "type": "deterministic_action"}],
        },
    }


def _make_run(db_path: str, run_id: str, auto_id: str, age_days: int, status: str = "succeeded",
              preserved: bool = False, favorite: bool = False) -> None:
    runs_db.create_run({
        "run_id": run_id,
        "automation_id": auto_id,
        "status": status,
        "is_preserved": preserved,
        "is_favorite": favorite,
    }, db_path=db_path)
    # create_run usa sempre "adesso": retrodatiamo per simulare run storiche
    conn = connection_db.get_db_connection(db_path)
    try:
        conn.execute(
            "UPDATE automation_runs SET started_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now', ?) WHERE run_id = ?",
            (f"-{age_days} days", run_id),
        )
        conn.commit()
    finally:
        conn.close()


def _run_ids(db_path: str) -> set:
    return {r["run_id"] for r in runs_db.list_runs(limit=1000, db_path=db_path)}


class TestBulkDeleteRunsRetention(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "retention.db")
        schema_db.init_automations_db(self.db_path)
        definitions_db.save_definition(_make_definition("auto_a"), db_path=self.db_path)
        definitions_db.save_definition(_make_definition("auto_b"), db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_older_than_days_deletes_only_expired(self):
        _make_run(self.db_path, "run_old", "auto_a", age_days=30)
        _make_run(self.db_path, "run_new", "auto_a", age_days=1)

        deleted = runs_db.bulk_delete_runs(older_than_days=14, db_path=self.db_path)

        self.assertEqual(deleted, 1)
        self.assertEqual(_run_ids(self.db_path), {"run_new"})

    def test_older_than_days_preserves_protected_runs(self):
        _make_run(self.db_path, "run_old", "auto_a", age_days=30)
        _make_run(self.db_path, "run_old_preserved", "auto_a", age_days=30, preserved=True)
        _make_run(self.db_path, "run_old_favorite", "auto_a", age_days=30, favorite=True)

        deleted = runs_db.bulk_delete_runs(older_than_days=14, db_path=self.db_path)

        self.assertEqual(deleted, 1)
        self.assertEqual(_run_ids(self.db_path), {"run_old_preserved", "run_old_favorite"})

    def test_older_than_days_scoped_to_automation(self):
        _make_run(self.db_path, "run_a_old", "auto_a", age_days=30)
        _make_run(self.db_path, "run_b_old", "auto_b", age_days=30)

        deleted = runs_db.bulk_delete_runs(older_than_days=14, automation_id="auto_a", db_path=self.db_path)

        self.assertEqual(deleted, 1)
        self.assertEqual(_run_ids(self.db_path), {"run_b_old"})

    def test_scheduler_prune_respects_per_automation_retention(self):
        definitions_db.save_definition(_make_definition("auto_short", retention_days=3), db_path=self.db_path)
        _make_run(self.db_path, "run_short_5d", "auto_short", age_days=5)
        _make_run(self.db_path, "run_short_1d", "auto_short", age_days=1)
        _make_run(self.db_path, "run_default_5d", "auto_a", age_days=5)
        _make_run(self.db_path, "run_default_20d", "auto_a", age_days=20)

        deleted = AutomationScheduler(db_path=self.db_path)._prune_expired_runs()

        self.assertEqual(deleted, 2)
        self.assertEqual(_run_ids(self.db_path), {"run_short_1d", "run_default_5d"})


class TestBulkDeleteRunsAPI(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "retention_api.db")
        self._orig_db_path = config.AUTOMATIONS_DB_PATH
        config.AUTOMATIONS_DB_PATH = self.db_path
        schema_db.init_automations_db(self.db_path)
        definitions_db.save_definition(_make_definition("auto_a"), db_path=self.db_path)
        _make_run(self.db_path, "run_old", "auto_a", age_days=30)
        _make_run(self.db_path, "run_new", "auto_a", age_days=1)
        self.client = TestClient(api)
        self.headers = {"X-API-Key": config.API_SECRET_KEY} if config.API_SECRET_KEY else {}

    def tearDown(self):
        config.AUTOMATIONS_DB_PATH = self._orig_db_path
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_delete_runs_with_older_than_days(self):
        res = self.client.delete("/v1/automations/runs", params={"older_than_days": 14}, headers=self.headers)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["deleted_count"], 1)
        self.assertEqual(_run_ids(self.db_path), {"run_new"})

    def test_delete_batch_with_older_than_days(self):
        res = self.client.post(
            "/v1/automations/runs/delete-batch",
            json={"older_than_days": 14},
            headers=self.headers,
        )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["deleted_count"], 1)
        self.assertEqual(_run_ids(self.db_path), {"run_new"})

    def test_delete_batch_by_run_ids(self):
        res = self.client.post(
            "/v1/automations/runs/delete-batch",
            json={"run_ids": ["run_new"]},
            headers=self.headers,
        )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["deleted_count"], 1)
        self.assertEqual(_run_ids(self.db_path), {"run_old"})


if __name__ == "__main__":
    unittest.main()
