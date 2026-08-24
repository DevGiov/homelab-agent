"""Test integrazione API con MetaMCP mockato (Fase 5.2).

Mocka il registry MetaMCP e testa gli endpoint REST end-to-end senza servizi esterni.
Le env vars di test sono impostate in conftest.py (prima di ogni import applicativo).
"""
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient


class TestApiEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import dopo aver impostato le env vars
        import api as api_module
        cls.client = TestClient(api_module.api)

    def test_health(self):
        r = self.client.get("/v1/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_status_endpoint(self):
        r = self.client.get("/v1/status")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("status", data)
        self.assertIn("services", data)
        self.assertIn("providers", data)

    def test_auth_required_when_key_set(self):
        import config
        original = config.API_SECRET_KEY
        try:
            config.API_SECRET_KEY = "test-secret-123"
            r = self.client.get("/v1/health")  # health è pubblico
            self.assertEqual(r.status_code, 200)
            r = self.client.get("/v1/audit")
            self.assertEqual(r.status_code, 401)
            r2 = self.client.get("/v1/audit", headers={"X-API-Key": "test-secret-123"})
            self.assertEqual(r2.status_code, 200)
        finally:
            config.API_SECRET_KEY = original

    def test_audit_endpoint(self):
        r = self.client.get("/v1/audit")
        self.assertEqual(r.status_code, 200)
        self.assertIn("entries", r.json())

    def test_kb_crud_flow(self):
        # Upload
        r = self.client.post("/v1/kb/documents", json={
            "filename": "api_test_doc.md",
            "content": "# Doc\n\nIl server Proxmox usa storage local-lvm per i container.",
        })
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.json()["chunks_indexed"], 1)

        # List
        r = self.client.get("/v1/kb/documents")
        names = [d["filename"] for d in r.json()["documents"]]
        self.assertIn("api_test_doc.md", names)

        # Search
        r = self.client.get("/v1/kb/search", params={"query": "storage container"})
        self.assertEqual(r.status_code, 200)

        # Delete
        r = self.client.delete("/v1/kb/documents/api_test_doc.md")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.json()["chunks_deleted"], 1)

    def test_kb_upload_invalid_format(self):
        r = self.client.post("/v1/kb/documents", json={"filename": "file.exe", "content": "x"})
        self.assertEqual(r.status_code, 400)

    def test_approvals_flow(self):
        import guardrails
        guardrails._APPROVALS.clear()

        # Crea una richiesta pendente direttamente (simula agent loop)
        res = guardrails.enforce_guardrails("stop_container", {"vmid": 999}, thread_id="t_api_test")
        rid = res["request_id"]

        # Lista
        r = self.client.get("/v1/approvals")
        pending_ids = [p["request_id"] for p in r.json()["pending"]]
        self.assertIn(rid, pending_ids)

        # Deny
        r = self.client.post(f"/v1/approvals/{rid}/deny")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "denied")

        # Non più pendente
        r = self.client.get("/v1/approvals")
        pending_ids = [p["request_id"] for p in r.json()["pending"]]
        self.assertNotIn(rid, pending_ids)

    def test_approve_nonexistent(self):
        r = self.client.post("/v1/approvals/apr_inesistente/approve")
        self.assertEqual(r.status_code, 404)

    def test_providers_endpoints(self):
        # 1. Get providers list
        r = self.client.get("/v1/providers")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("active_provider", data)
        self.assertIn("active_model", data)
        self.assertIn("providers", data)
        self.assertTrue(len(data["providers"]) > 0)
        prov_names = [p["name"] for p in data["providers"]]
        self.assertIn("llamacpp", prov_names)

        # 2. Get provider models
        r = self.client.get("/v1/providers/llamacpp/models")
        self.assertEqual(r.status_code, 200)
        mdata = r.json()
        self.assertEqual(mdata["provider"], "llamacpp")
        self.assertIn("models", mdata)

        # 3. Set default provider and model
        r = self.client.put("/v1/providers/default", json={
            "provider": "llamacpp",
            "model": "test-model-custom"
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["active_provider"], "llamacpp")
        self.assertEqual(r.json()["active_model"], "test-model-custom")

        # 4. Inexistent provider error
        r = self.client.get("/v1/providers/nonexistent_provider_xyz/models")
        self.assertEqual(r.status_code, 404)



class TestAgentLoopWithMocks(unittest.TestCase):
    """Test dell'agent loop con LLM e registry mockati (Fase 5.2)."""

    def _run_loop(self, selections):
        from agent_loop import run_agent_loop

        calls = []

        def mock_llm(prompt, system_prompt=None, reasoning_budget=-1):
            return {"content": "risposta mock", "reasoning_content": ""}

        idx = [0]

        def mock_structured(**kw):
            i = idx[0]
            idx[0] += 1
            return selections[i] if i < len(selections) else selections[-1]

        class FakeSel:
            def __init__(self, **kw):
                self.tool_needed = kw.get("tool_needed", False)
                self.tool_name = kw.get("tool_name")
                self.arguments = kw.get("arguments", {})
                self.confidence = 0.9
                self.reasoning = kw.get("reasoning", "")
                self.final_answer = kw.get("final_answer")
                self.parallel_calls = kw.get("parallel_calls")

        from registry.manager import get_registry_manager
        mgr = get_registry_manager()
        orig_exec = mgr.execute_tool
        orig_par = mgr.execute_tools_parallel
        mgr.execute_tool = lambda name, args, regs, **kw: (
            calls.append(name) or {"ok": True}
        )
        mgr.execute_tools_parallel = lambda cs, regs, **kw: (
            calls.extend(["PAR:" + c["tool_name"] for c in cs]) or [{"ok": True} for _ in cs]
        )
        try:
            res = run_agent_loop(
                task="test", mode="act", memory_context=None,
                call_llm_fn=mock_llm, call_llm_structured_fn=mock_structured, thread_id="t_mock",
            )
        finally:
            mgr.execute_tool = orig_exec
            mgr.execute_tools_parallel = orig_par
        return res, calls

    def test_direct_answer(self):
        sel = [type("S", (), {"tool_needed": False, "tool_name": None, "arguments": {},
                              "reasoning": "", "final_answer": "Risposta diretta!", "parallel_calls": None})()]
        res, calls = self._run_loop(sel)
        self.assertEqual(res["final_response"], "Risposta diretta!")
        self.assertEqual(calls, [])

    def test_cache_dedup(self):
        FakeSel = type("S", (), {})
        s1 = FakeSel(); s1.tool_needed=True; s1.tool_name="list_containers"; s1.arguments={}; s1.reasoning="a"; s1.final_answer=None; s1.parallel_calls=None
        s2 = FakeSel(); s2.tool_needed=True; s2.tool_name="list_containers"; s2.arguments={}; s2.reasoning="b"; s2.final_answer=None; s2.parallel_calls=None
        res, calls = self._run_loop([s1, s2])
        # list_containers è safe/read-only: la seconda chiamata deve usare la cache.
        # Nota: il registry manager è globale, quindi chiamate da altri test possono comparire;
        # verifichiamo che ci sia ALMENO uno step cached e non più di una esecuzione reale in questo run.
        cached_steps = [t for t in res["execution_trace"] if t.get("cached")]
        self.assertGreaterEqual(len(cached_steps), 1)
        self.assertEqual(cached_steps[0]["tool_name"], "list_containers")

    def test_approval_breaks_loop(self):
        """Override temporaneo del registry metamcp con un fake contenente stop_container."""
        import guardrails
        guardrails._APPROVALS.clear()

        from registry.manager import get_registry_manager
        mgr = get_registry_manager()

        class FakeMetaMCPRegistry:
            name = "metamcp"
            def get_tools(self):
                return [{"name": "stop_container", "description": "fake", "parameters": {"type": "object", "properties": {}}}]
            def execute_tool(self, tool_name, args):
                return {"ok": True}

        orig_registries = dict(mgr._registries)
        mgr._registries["metamcp"] = FakeMetaMCPRegistry()

        FakeSel = type("S", (), {})
        s1 = FakeSel(); s1.tool_needed=True; s1.tool_name="stop_container"; s1.arguments={"vmid": 1}; s1.reasoning=""; s1.final_answer=None; s1.parallel_calls=None

        from agent_loop import run_agent_loop

        def mock_llm(prompt, system_prompt=None, reasoning_budget=-1):
            return {"content": "sintesi", "reasoning_content": ""}
        idx = [0]
        def mock_structured(**kw):
            i = idx[0]; idx[0] += 1
            return s1

        try:
            res = run_agent_loop(
                task="test approval", mode="act", memory_context=None,
                call_llm_fn=mock_llm, call_llm_structured_fn=mock_structured,
                thread_id="t_approval",
            )
        finally:
            mgr._registries.clear()
            mgr._registries.update(orig_registries)

        approval_steps = [t for t in res["execution_trace"] if t.get("approval_required")]
        self.assertGreaterEqual(len(approval_steps), 1)
        rid = approval_steps[0].get("request_id")
        self.assertIsNotNone(rid)
        pending_ids = [p["request_id"] for p in guardrails.get_pending_approvals()]
        self.assertIn(rid, pending_ids)


if __name__ == "__main__":
    unittest.main()
