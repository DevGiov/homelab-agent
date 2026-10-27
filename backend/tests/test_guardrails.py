"""Test unitari per guardrails, audit log, vector store e knowledge base (Fasi 0-3)."""
import tempfile
import unittest

from app.automations.db.schema import init_automations_db
from app.core.config import settings
from app.security import guardrails


class TestGuardrailsClassification(unittest.TestCase):
    def test_safe_tools(self):
        self.assertEqual(guardrails.classify_tool("list_containers"), "safe")
        self.assertEqual(guardrails.classify_tool("web_search"), "safe")
        self.assertEqual(guardrails.classify_tool("recall_memory"), "safe")

    def test_risky_tools(self):
        self.assertEqual(guardrails.classify_tool("stop_container"), "risky")
        self.assertEqual(guardrails.classify_tool("delete_pihole_dns_record"), "risky")
        self.assertEqual(guardrails.classify_tool("exec_host_command"), "risky")

    def test_write_tools(self):
        self.assertEqual(guardrails.classify_tool("allocate_ip"), "risky")
        self.assertEqual(guardrails.classify_tool("create_npm_proxy_host"), "risky")
        self.assertEqual(guardrails.get_tool_metadata("allocate_ip")["action_type"], "execute")
        self.assertEqual(guardrails.get_tool_metadata("create_npm_proxy_host")["action_type"], "execute")


class TestShellGuard(unittest.TestCase):
    def test_allowed_commands(self):
        ok, _ = guardrails.check_shell_command("ls -la /etc/pve")
        self.assertTrue(ok)
        ok, _ = guardrails.check_shell_command("systemctl status nginx")
        self.assertTrue(ok)

    def test_blocked_commands(self):
        for cmd in [
            "rm -rf /usr",
            "mkfs.ext4 /dev/sda1",
            "dd if=/dev/zero of=/dev/sda",
            "shutdown -h now",
            "iptables -F",
        ]:
            ok, reason = guardrails.check_shell_command(cmd)
            self.assertFalse(ok, f"'{cmd}' dovrebbe essere bloccato")
            self.assertIn("bloccato", reason)


class TestToolMetadata(unittest.TestCase):
    def test_metadata_structure(self):
        meta = guardrails.get_tool_metadata("rollback_lxc_snapshot")
        self.assertEqual(meta["risk"], "risky")
        self.assertTrue(meta["requires_approval"])
        self.assertFalse(meta["read_only"])
        self.assertIn("category", meta)
        self.assertIn("reversible", meta)

    def test_enrich_catalog(self):
        tools = [{"name": "list_containers"}, {"name": "stop_container"}]
        enriched = guardrails.enrich_catalog_with_metadata(tools)
        self.assertEqual(enriched[0]["metadata"]["risk"], "safe")
        self.assertEqual(enriched[1]["metadata"]["risk"], "risky")


class TestApprovalWorkflow(unittest.TestCase):
    def setUp(self):
        # Approvazioni pulite tra i test: in memoria e nel DB delle automazioni (dove vengono persistite)
        guardrails._APPROVALS.clear()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.orig_data_dir = settings.data_dir
        settings.data_dir = self.tmp_dir.name
        init_automations_db()

    def tearDown(self):
        settings.data_dir = self.orig_data_dir
        self.tmp_dir.cleanup()

    def test_approval_required_for_risky(self):
        res = guardrails.enforce_guardrails("stop_container", {"vmid": 137}, thread_id="t", mode="act")
        self.assertIsNotNone(res)
        self.assertTrue(res.get("approval_required"))
        self.assertIn("request_id", res)

    def test_no_approval_for_safe(self):
        res = guardrails.enforce_guardrails("list_containers", {})
        self.assertIsNone(res)

    def test_blocked_shell_command(self):
        res = guardrails.enforce_guardrails("exec_host_command", {"command": "rm -rf /usr"})
        self.assertIsNotNone(res)
        self.assertTrue(res.get("blocked"))

    def test_resolve_approve(self):
        res = guardrails.enforce_guardrails("stop_container", {"vmid": 100})
        rid = res["request_id"]
        req = guardrails.resolve_approval(rid, approved=True)
        self.assertEqual(req.status, "approved")

    def test_resolve_deny(self):
        res = guardrails.enforce_guardrails("stop_container", {"vmid": 100})
        req = guardrails.resolve_approval(res["request_id"], approved=False)
        self.assertEqual(req.status, "denied")

    def test_expiry(self):
        res = guardrails.enforce_guardrails("stop_container", {"vmid": 100})
        guardrails._APPROVALS[res["request_id"]].created_at -= (guardrails.APPROVAL_TTL_SECONDS + 10)
        req = guardrails.resolve_approval(res["request_id"], approved=True)
        self.assertEqual(req.status, "expired")

    def test_pending_list_and_filter(self):
        guardrails.enforce_guardrails("stop_container", {"vmid": 1}, thread_id="thread_a")
        guardrails.enforce_guardrails("stop_container", {"vmid": 2}, thread_id="thread_b")
        all_pending = guardrails.get_pending_approvals()
        filtered = guardrails.get_pending_approvals(thread_id="thread_a")
        self.assertEqual(len(all_pending), 2)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["thread_id"], "thread_a")


if __name__ == "__main__":
    unittest.main()
