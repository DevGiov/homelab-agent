"""Test unitari per guardrails, audit log, vector store e knowledge base (Fasi 0-3)."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.automations.db import approvals as approvals_db
from app.automations.db.schema import init_automations_db
from app.core.config import settings
from app.security import approvals, policy


class TestGuardrailsClassification(unittest.TestCase):
    def test_safe_tools(self):
        self.assertEqual(policy.classify_tool("list_containers"), "safe")
        self.assertEqual(policy.classify_tool("web_search"), "safe")
        self.assertEqual(policy.classify_tool("recall_memory"), "safe")

    def test_risky_tools(self):
        self.assertEqual(policy.classify_tool("stop_container"), "risky")
        self.assertEqual(policy.classify_tool("delete_pihole_dns_record"), "risky")
        self.assertEqual(policy.classify_tool("exec_host_command"), "risky")

    def test_write_tools(self):
        self.assertEqual(policy.classify_tool("allocate_ip"), "risky")
        self.assertEqual(policy.classify_tool("create_npm_proxy_host"), "risky")
        self.assertEqual(policy.get_tool_metadata("allocate_ip")["action_type"], "execute")
        self.assertEqual(policy.get_tool_metadata("create_npm_proxy_host")["action_type"], "execute")


class TestShellGuard(unittest.TestCase):
    def test_allowed_commands(self):
        self.assertEqual(policy.analyze_command_safety("ls -la /etc/pve"), ("safe", None))
        self.assertEqual(policy.analyze_command_safety("systemctl status nginx"), ("safe", None))

    def test_blocked_commands(self):
        for cmd in [
            "rm -rf /usr",
            "mkfs.ext4 /dev/sda1",
            "dd if=/dev/zero of=/dev/sda",
            "shutdown -h now",
            "iptables -F",
        ]:
            level, reason = policy.analyze_command_safety(cmd)
            self.assertIn(level, ("blocked", "suspicious"), f"'{cmd}' non dovrebbe essere eseguibile senza conferma")
            self.assertTrue(reason)


class TestToolMetadata(unittest.TestCase):
    def test_metadata_structure(self):
        meta = policy.get_tool_metadata("rollback_lxc_snapshot")
        self.assertEqual(meta["risk"], "risky")
        self.assertTrue(meta["requires_approval"])
        self.assertFalse(meta["read_only"])
        self.assertIn("category", meta)
        self.assertIn("reversible", meta)

    def test_enrich_catalog(self):
        tools = [{"name": "list_containers"}, {"name": "stop_container"}]
        enriched = policy.enrich_catalog_with_metadata(tools)
        self.assertEqual(enriched[0]["metadata"]["risk"], "safe")
        self.assertEqual(enriched[1]["metadata"]["risk"], "risky")


class TestApprovalWorkflow(unittest.TestCase):
    def setUp(self):
        # Approvazioni pulite tra i test: in memoria e nel DB delle automazioni (dove vengono persistite)
        approvals._APPROVALS.clear()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.orig_data_dir = settings.data_dir
        settings.data_dir = self.tmp_dir.name
        init_automations_db()

    def tearDown(self):
        settings.data_dir = self.orig_data_dir
        self.tmp_dir.cleanup()

    def test_approval_required_for_risky(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 137}, thread_id="t", mode="act")
        self.assertIsNotNone(res)
        self.assertTrue(res.get("approval_required"))
        self.assertIn("request_id", res)

    def test_no_approval_for_safe(self):
        res = policy.enforce_guardrails("list_containers", {})
        self.assertIsNone(res)

    def test_blocked_shell_command(self):
        res = policy.enforce_guardrails("exec_host_command", {"command": "rm -rf /usr"})
        self.assertIsNotNone(res)
        self.assertTrue(res.get("blocked"))

    def test_resolve_approve(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 100})
        rid = res["request_id"]
        req = approvals.resolve_approval(rid, approved=True)
        self.assertEqual(req.status, "approved")

    def test_resolve_deny(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 100})
        req = approvals.resolve_approval(res["request_id"], approved=False)
        self.assertEqual(req.status, "denied")

    def test_expiry(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 100})
        approvals._APPROVALS[res["request_id"]].created_at -= (approvals.APPROVAL_TTL_SECONDS + 10)
        req = approvals.resolve_approval(res["request_id"], approved=True)
        self.assertEqual(req.status, "expired")
        stored = approvals_db.get_automation_approval(res["request_id"])
        self.assertEqual(stored["status"], "expired")
        self.assertIsNone(stored.get("resolution_action"))

    def _client(self) -> TestClient:
        from app.api.main import api
        return TestClient(api)

    def test_chat_ttl_is_thirty_minutes_and_runs_keep_a_day(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 15})
        req = approvals.get_approval_request(res["request_id"])
        self.assertEqual(approvals.APPROVAL_TTL_SECONDS, 1800)
        self.assertEqual(req.ttl_seconds, 1800)
        stored = approvals_db.get_automation_approval(res["request_id"])
        created = datetime.fromisoformat(stored["created_at"])
        expires = datetime.fromisoformat(res["expires_at"])
        self.assertAlmostEqual((expires - created).total_seconds(), 1800, delta=2)
        self.assertNotEqual(req.ttl_seconds, approvals.RUN_APPROVAL_TTL_SECONDS)

        approvals.bind_to_run(res["request_id"], "run_iss40", "sr_iss40")
        bound = approvals.get_approval_request(res["request_id"])
        self.assertEqual(bound.ttl_seconds, approvals.RUN_APPROVAL_TTL_SECONDS)
        bound_row = approvals_db.get_automation_approval(res["request_id"])
        remaining = (datetime.fromisoformat(bound_row["expires_at"]) - datetime.now(timezone.utc)).total_seconds()
        self.assertGreater(remaining, 23 * 3600)
        self.assertLess(remaining, 24 * 3600 + 5)

    def test_db_restore_after_deadline_expires_without_recording_deny(self):
        approvals_db.create_automation_approval({
            "request_id": "apr_restore_past",
            "run_id": "chat_session",
            "tool_name": "list_demo_widgets",
            "arguments": {"name": "demo"},
            "status": "pending",
            "created_at": "2020-01-01T00:00:00+00:00",
            "expires_at": "2020-01-01T00:30:00+00:00",
        })
        response = self._client().post(
            "/v1/approvals/apr_restore_past/resolve",
            json={"action": "deny", "resolved_by": "user"},
        )
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["detail"], "Richiesta scaduta")
        stored = approvals_db.get_automation_approval("apr_restore_past")
        self.assertEqual(stored["status"], "expired")
        self.assertIsNone(stored.get("resolution_action"))
        restored = approvals.get_approval_request("apr_restore_past")
        self.assertEqual(restored.status, "expired")
        self.assertLess(restored.created_at, 1600000000)

    def test_db_restore_before_deadline_records_the_click(self):
        approvals_db.create_automation_approval({
            "request_id": "apr_restore_open",
            "run_id": "chat_session",
            "tool_name": "list_demo_widgets",
            "arguments": {},
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
        })
        req = approvals.resolve_approval("apr_restore_open", action="deny", resolved_by="user")
        self.assertEqual(req.status, "denied")
        self.assertEqual(approvals_db.get_automation_approval("apr_restore_open")["status"], "denied")

    def test_missing_approval_is_404(self):
        response = self._client().post(
            "/v1/approvals/apr_missing_iss40/resolve",
            json={"action": "deny"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Richiesta 'apr_missing_iss40' non trovata")

    def test_already_denied_approval_is_409(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 11})
        request_id = res["request_id"]
        approvals.resolve_approval(request_id, action="deny", resolved_by="user")
        response = self._client().post(
            f"/v1/approvals/{request_id}/resolve",
            json={"action": "approve", "resolved_by": "user"},
        )
        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "already_resolved")
        self.assertEqual(detail["action"], "denied")
        self.assertIn("rifiutata", detail["message"])
        self.assertIn(request_id, detail["message"])
        self.assertEqual(approvals_db.get_automation_approval(request_id)["status"], "denied")

    def test_create_sweep_persists_expired(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 12})
        request_id = res["request_id"]
        approvals._APPROVALS[request_id].created_at -= approvals.APPROVAL_TTL_SECONDS + 5
        policy.enforce_guardrails("stop_container", {"vmid": 13})
        stored = approvals_db.get_automation_approval(request_id)
        self.assertEqual(stored["status"], "expired")
        self.assertIsNone(stored.get("resolution_action"))
        response = self._client().post(
            f"/v1/approvals/{request_id}/resolve",
            json={"action": "deny"},
        )
        self.assertEqual(response.status_code, 410)
        self.assertEqual(approvals_db.get_automation_approval(request_id)["status"], "expired")

    def test_pending_list_sweep_persists_expired(self):
        res = policy.enforce_guardrails("stop_container", {"vmid": 14})
        request_id = res["request_id"]
        approvals._APPROVALS[request_id].created_at -= approvals.APPROVAL_TTL_SECONDS + 5
        pending_ids = [item["request_id"] for item in approvals.get_pending_approvals()]
        self.assertNotIn(request_id, pending_ids)
        stored = approvals_db.get_automation_approval(request_id)
        self.assertEqual(stored["status"], "expired")
        self.assertIsNone(stored.get("resolution_action"))

    def test_pending_list_and_filter(self):
        policy.enforce_guardrails("stop_container", {"vmid": 1}, thread_id="thread_a")
        policy.enforce_guardrails("stop_container", {"vmid": 2}, thread_id="thread_b")
        all_pending = approvals.get_pending_approvals()
        filtered = approvals.get_pending_approvals(thread_id="thread_a")
        self.assertEqual(len(all_pending), 2)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["thread_id"], "thread_a")


if __name__ == "__main__":
    unittest.main()
