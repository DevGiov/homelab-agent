"""ISS-40: scadenza vera delle approvazioni e le tre risposte di una richiesta che non si può più decidere.

404 id sconosciuto, 409 già risolta (con l'azione registrata), 410 scaduta. Un click tardivo non viene mai
registrato come approvazione o rifiuto, né in chat né su una run.
"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.automations.db import approvals as approvals_db
from app.automations.db.schema import init_automations_db
from app.core.config import settings
from app.security import approvals, policy


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


def _row(request_id: str, *, run_id: str = "chat_session", status: str = "pending",
         created: timedelta = timedelta(minutes=-1), expires: timedelta = timedelta(minutes=29)) -> None:
    approvals_db.create_automation_approval({
        "request_id": request_id,
        "run_id": run_id,
        "tool_name": "list_demo_widgets",
        "arguments": {"name": "demo"},
        "status": status,
        "created_at": _iso(created),
        "expires_at": _iso(expires),
    })


class _Base(unittest.TestCase):
    def setUp(self):
        approvals._APPROVALS.clear()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.orig_data_dir = settings.data_dir
        settings.data_dir = self.tmp_dir.name
        init_automations_db()
        from app.api.main import api
        self.client = TestClient(api)
        self.headers = {"X-API-Key": settings.api_secret_key} if settings.api_secret_key else {}

    def tearDown(self):
        approvals._APPROVALS.clear()
        settings.data_dir = self.orig_data_dir
        self.tmp_dir.cleanup()

    def resolve(self, request_id: str, action: str = "deny"):
        return self.client.post(f"/v1/approvals/{request_id}/resolve",
                                json={"action": action, "resolved_by": "user"}, headers=self.headers)

    def restart(self):
        """Il processo perde le richieste in memoria: resta solo automations.db."""
        approvals._APPROVALS.clear()


class TestChatTtl(_Base):
    def test_chat_ttl_is_thirty_minutes_and_the_response_carries_it(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 15})
        req = approvals.get_approval_request(res["request_id"])
        self.assertEqual(approvals.APPROVAL_TTL_SECONDS, 1800)
        self.assertEqual(req.ttl_seconds, 1800)
        stored = approvals_db.get_automation_approval(res["request_id"])
        created = datetime.fromisoformat(stored["created_at"])
        expires = datetime.fromisoformat(stored["expires_at"])
        self.assertAlmostEqual((expires - created).total_seconds(), 1800, delta=1)
        # La scheda riceve la stessa scadenza, al secondo e con il fuso
        self.assertRegex(res["expires_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        self.assertAlmostEqual((datetime.fromisoformat(res["expires_at"]) - expires).total_seconds(), 0, delta=1)

    def test_bind_to_run_extends_to_a_day(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 16})
        approvals.bind_to_run(res["request_id"], "run_iss40", "sr_iss40")
        bound = approvals.get_approval_request(res["request_id"])
        self.assertEqual(bound.ttl_seconds, approvals.RUN_APPROVAL_TTL_SECONDS)
        remaining = (datetime.fromisoformat(approvals_db.get_automation_approval(res["request_id"])["expires_at"])
                     - datetime.now(timezone.utc)).total_seconds()
        self.assertGreater(remaining, 23.9 * 3600)
        # La memoria e la riga hanno la stessa scadenza: 24 ore dal legame, non dalla creazione
        bound.created_at -= 600
        approvals.bind_to_run(res["request_id"], "run_iss40", "sr_iss40")
        row_deadline = datetime.fromisoformat(approvals_db.get_automation_approval(res["request_id"])["expires_at"]).timestamp()
        self.assertAlmostEqual(bound.created_at + bound.ttl_seconds, row_deadline, delta=1)
        # Anche in memoria: un click alla 25a ora della run sarebbe scaduto, alla 2a no
        bound.created_at -= 3600
        self.assertEqual(approvals.resolve_approval(res["request_id"], action="approve").status, "approved")


class TestRestoreUsesTheRealDeadline(_Base):
    def test_restore_after_deadline_is_410_and_records_nothing(self):
        _row("apr_restore_past", created=timedelta(minutes=-40), expires=timedelta(minutes=-10))
        response = self.resolve("apr_restore_past", "deny")
        self.assertEqual(response.status_code, 410)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "expired")
        self.assertIn("scaduta", detail["message"])
        stored = approvals_db.get_automation_approval("apr_restore_past")
        self.assertEqual(stored["status"], "expired")
        self.assertIsNone(stored["resolution_action"])
        self.assertIsNone(stored["resolved_by"])
        self.assertEqual(detail["expires_at"], datetime.fromisoformat(stored["expires_at"]).isoformat(timespec="seconds"))

    def test_restore_uses_the_row_ttl_not_the_current_one(self):
        # Il caso di apr_fdedb771433c: creata con i vecchi 300 s, cliccata 14 minuti dopo un riavvio
        _row("apr_old_ttl", created=timedelta(minutes=-14), expires=timedelta(minutes=-9))
        self.assertEqual(self.resolve("apr_old_ttl", "deny").status_code, 410)
        self.assertEqual(approvals_db.get_automation_approval("apr_old_ttl")["status"], "expired")

    def test_restore_copies_created_at_and_expires_at(self):
        _row("apr_restore_copy", created=timedelta(minutes=-5), expires=timedelta(minutes=25))
        stored = approvals_db.get_automation_approval("apr_restore_copy")
        req = approvals.resolve_approval("apr_restore_copy", action="approve")
        self.assertEqual(req.status, "approved")
        self.assertAlmostEqual(req.created_at, datetime.fromisoformat(stored["created_at"]).timestamp(), delta=0.01)
        self.assertAlmostEqual(req.created_at + req.ttl_seconds, datetime.fromisoformat(stored["expires_at"]).timestamp(), delta=1)

    def test_restore_before_deadline_records_the_click(self):
        _row("apr_restore_open", expires=timedelta(minutes=20))
        req = approvals.resolve_approval("apr_restore_open", action="deny", resolved_by="user")
        self.assertEqual(req.status, "denied")
        self.assertEqual(approvals_db.get_automation_approval("apr_restore_open")["status"], "denied")

    def test_sqlite_timestamp_without_zone_is_utc(self):
        self.assertEqual(approvals._parse_utc("2026-11-18 22:38:31"),
                         datetime(2026, 11, 18, 22, 38, 31, tzinfo=timezone.utc).timestamp())
        self.assertEqual(approvals._parse_utc("2026-11-18T22:38:31Z"),
                         datetime(2026, 11, 18, 22, 38, 31, tzinfo=timezone.utc).timestamp())
        self.assertIsNone(approvals._parse_utc("ieri"))


class TestThreeAnswers(_Base):
    def test_unknown_id_is_404(self):
        response = self.resolve("apr_missing_iss40")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], {
            "code": "not_found", "message": "Richiesta 'apr_missing_iss40' non trovata"})

    def test_second_click_is_409_with_the_recorded_action(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 11})
        rid = res["request_id"]
        self.assertEqual(self.resolve(rid, "deny").status_code, 200)
        response = self.resolve(rid, "approve")
        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertEqual((detail["code"], detail["action"], detail["resolved_by"]), ("already_resolved", "denied", "user"))
        self.assertEqual(detail["message"], f"Richiesta '{rid}' già risolta: rifiutata")
        self.assertEqual(approvals_db.get_automation_approval(rid)["status"], "denied")

    def test_409_after_a_restart_reads_the_row(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 12})
        approvals.resolve_approval(res["request_id"], action="approve", resolved_by="telegram")
        self.restart()
        response = self.resolve(res["request_id"], "deny")
        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertEqual((detail["action"], detail["resolved_by"]), ("approved", "telegram"))
        self.assertIn("approvata", detail["message"])

    def test_expired_in_memory_is_410(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 13})
        approvals._APPROVALS[res["request_id"]].created_at -= approvals.APPROVAL_TTL_SECONDS + 5
        first = self.resolve(res["request_id"], "approve")
        self.assertEqual(first.status_code, 410)
        # Il secondo click resta 410, non 404 né 409
        self.assertEqual(self.resolve(res["request_id"], "approve").status_code, 410)
        self.assertEqual(approvals_db.get_automation_approval(res["request_id"])["status"], "expired")

    def test_410_drops_the_suspended_turn_and_404_409_do_not(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 14})
        approvals._APPROVALS[res["request_id"]].created_at -= approvals.APPROVAL_TTL_SECONDS + 5
        with patch("app.agent.turn_checkpoints.load", return_value=None), \
                patch("app.agent.turn_checkpoints.delete") as delete:
            self.assertEqual(self.resolve(res["request_id"]).status_code, 410)
            delete.assert_called_once_with(res["request_id"])
            delete.reset_mock()
            self.assertEqual(self.resolve("apr_nobody").status_code, 404)
            other = policy.enforce_guardrails("stop_container", {"vmid": 15})["request_id"]
            approvals.resolve_approval(other, action="deny")
            self.assertEqual(self.resolve(other).status_code, 409)
            delete.assert_not_called()


class TestCleanupWritesExpired(_Base):
    def test_create_sweep_persists_expired_and_a_late_click_gets_410(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 12})
        rid = res["request_id"]
        approvals._APPROVALS[rid].created_at -= approvals.APPROVAL_TTL_SECONDS + 5
        policy.enforce_guardrails("stop_container", {"vmid": 13})
        stored = approvals_db.get_automation_approval(rid)
        self.assertEqual(stored["status"], "expired")
        self.assertIsNone(stored["resolution_action"])
        self.restart()
        self.assertEqual(self.resolve(rid).status_code, 410)

    def test_pending_list_sweep_persists_expired(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 14})
        rid = res["request_id"]
        approvals._APPROVALS[rid].created_at -= approvals.APPROVAL_TTL_SECONDS + 5
        self.assertNotIn(rid, [item["request_id"] for item in approvals.get_pending_approvals()])
        self.assertEqual(approvals_db.get_automation_approval(rid)["status"], "expired")
        self.restart()
        self.assertEqual(self.resolve(rid).status_code, 410)

    def test_db_resolution_refuses_an_overdue_row(self):
        _row("apr_db_overdue", expires=timedelta(seconds=-1))
        self.assertIsNone(approvals_db.resolve_automation_approval("apr_db_overdue", "approve"))
        stored = approvals_db.get_automation_approval("apr_db_overdue")
        self.assertEqual(stored["status"], "expired")
        self.assertIsNone(stored["resolution_action"])
        _row("apr_db_open")
        self.assertEqual(approvals_db.resolve_automation_approval("apr_db_open", "approve")["status"], "approved")


class TestRunApprovals(_Base):
    """Una richiesta di una run passa dalla stessa route: deve dare le stesse tre risposte, e non riprendere la run."""

    def _resolve_run(self, request_id: str):
        runner = MagicMock()
        with patch("app.automations.db.runs.get_run", return_value={"run_id": "run_iss40"}), \
                patch("app.automations.routes.common.get_runner", return_value=runner), \
                patch("app.api.routes.approvals.threading.Thread") as thread:
            response = self.resolve(request_id, "approve")
        return response, thread

    def test_open_run_approval_resumes_the_run(self):
        _row("apr_run_open", run_id="run_iss40", expires=timedelta(hours=20))
        response, thread = self._resolve_run("apr_run_open")
        self.assertEqual(response.status_code, 200)
        thread.assert_called_once()

    def test_overdue_run_approval_is_410_and_does_not_resume(self):
        _row("apr_run_late", run_id="run_iss40", created=timedelta(hours=-25), expires=timedelta(hours=-1))
        response, thread = self._resolve_run("apr_run_late")
        self.assertEqual(response.status_code, 410)
        thread.assert_not_called()
        self.assertEqual(approvals_db.get_automation_approval("apr_run_late")["status"], "expired")

    def test_resolved_run_approval_is_409_and_does_not_resume(self):
        _row("apr_run_done", run_id="run_iss40")
        approvals_db.resolve_automation_approval("apr_run_done", "deny")
        response, thread = self._resolve_run("apr_run_done")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["action"], "denied")
        thread.assert_not_called()


class TestAutomationsRouteChatBranch(_Base):
    """La scheda delle automazioni risolve anche le richieste di chat: stessa scadenza, stesse risposte."""

    def _resolve(self, request_id: str, action: str = "approve"):
        with patch("app.registry.manager.get_registry_manager") as manager:
            response = self.client.post(f"/v1/automations/runs/chat_session/approvals/{request_id}/resolve",
                                        json={"action": action, "resolved_by": "user"}, headers=self.headers)
        return response, manager.return_value.execute_approved_tool

    def test_overdue_chat_approval_is_410_and_the_tool_does_not_run(self):
        _row("apr_auto_late", created=timedelta(minutes=-40), expires=timedelta(minutes=-10))
        response, execute = self._resolve("apr_auto_late")
        self.assertEqual(response.status_code, 410)
        execute.assert_not_called()
        stored = approvals_db.get_automation_approval("apr_auto_late")
        self.assertEqual((stored["status"], stored["resolution_action"]), ("expired", None))

    def test_approve_thread_is_recorded_as_approved(self):
        _row("apr_auto_thread")
        response, _ = self._resolve("apr_auto_thread", "approve_thread")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(approvals_db.get_automation_approval("apr_auto_thread")["status"], "approved")

    def test_unknown_chat_approval_is_404(self):
        response, execute = self._resolve("apr_auto_missing")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "not_found")
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
