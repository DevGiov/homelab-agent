import time
import unittest
from fastapi.testclient import TestClient
import config
from api import api
from stream_session import create_session, remove_session

class TestStreamApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api)
        self.headers = {"X-API-Key": config.API_SECRET_KEY} if config.API_SECRET_KEY else {}
        self.thread_id = f"test_api_thread_{int(time.time()*1000)}"

    def tearDown(self):
        remove_session(self.thread_id)

    def test_get_thread_active_session_synthesis(self):
        # Create active session for thread
        sess = create_session(self.thread_id, task="Spiega kubernetes", mode="ask")
        sess.put({"type": "reasoning", "delta": "Sto elaborando la spiegazione..."})
        sess.put({"type": "content", "delta": "Kubernetes è un orchestratore..."})

        # Fetch thread details
        res = self.client.get(f"/v1/threads/{self.thread_id}", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("is_active"))
        self.assertFalse(data.get("is_paused"))
        self.assertIn("active_snapshot", data)
        self.assertEqual(data["active_snapshot"]["content"], "Kubernetes è un orchestratore...")

        # Messages list should synthesize in-progress assistant message
        msgs = data.get("messages", [])
        self.assertTrue(len(msgs) >= 1)
        last_msg = msgs[-1]
        self.assertEqual(last_msg["sender"], "assistant")
        self.assertTrue(last_msg.get("isRunning"))
        self.assertIn("Kubernetes", last_msg.get("content"))
        self.assertIn("elaborando", last_msg.get("reasoning_content"))

    def test_list_threads_includes_active_session(self):
        sess = create_session(self.thread_id, task="Test active listing", mode="plan")
        res = self.client.get("/v1/threads", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        items = res.json()
        matching = [item for item in items if item["thread_id"] == self.thread_id]
        self.assertTrue(len(matching) >= 1)
        self.assertTrue(matching[0]["is_active"])

    def test_reconnect_stream_endpoint(self):
        import threading
        sess = create_session(self.thread_id, task="Test SSE stream", mode="act")
        sess.put({"type": "reasoning", "delta": "Analisi in corso"})
        sess.put({"type": "content", "delta": "Output parziale"})

        def delayed_close():
            time.sleep(0.05)
            sess.put(None)

        threading.Thread(target=delayed_close).start()

        with self.client.stream("GET", f"/v1/threads/{self.thread_id}/stream", headers=self.headers) as response:
            self.assertEqual(response.status_code, 200)
            lines = []
            for line in response.iter_lines():
                if line:
                    lines.append(line)
            self.assertTrue(any("sync" in l for l in lines))

if __name__ == '__main__':
    unittest.main()
