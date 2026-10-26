import time
import threading
import unittest
from fastapi.testclient import TestClient

from stream_session import (
    StreamSession,
    create_session,
    get_session,
    remove_session,
    current_session_var,
    _active_sessions,
    _sessions_lock,
)
from api import api as app


class TestStreamControls(unittest.TestCase):

    def setUp(self):
        with _sessions_lock:
            _active_sessions.clear()

    def tearDown(self):
        with _sessions_lock:
            _active_sessions.clear()

    def test_session_lifecycle_and_metrics(self):
        sess = create_session("thread_test_1")
        self.assertEqual(get_session("thread_test_1"), sess)

        # Token accumulation
        sess.record_metrics({"prompt_tokens": 60, "completion_tokens": 40, "total_tokens": 100})
        
        # Artificial sleep to ensure duration > 0
        time.sleep(0.05)
        
        metrics = sess.get_metrics()
        self.assertEqual(metrics["prompt_tokens"], 60)
        self.assertEqual(metrics["completion_tokens"], 40)
        self.assertEqual(metrics["total_tokens"], 100)
        self.assertGreater(metrics["duration_s"], 0)
        self.assertGreater(metrics["tok_per_s"], 0)

        remove_session("thread_test_1")
        self.assertIsNone(get_session("thread_test_1"))

    def test_pause_and_resume_events(self):
        sess = create_session("thread_pause_test")

        # Initially not paused
        self.assertFalse(sess.is_paused())
        self.assertTrue(sess.pause_event.is_set())

        # Pause
        sess.pause()
        self.assertTrue(sess.is_paused())
        self.assertFalse(sess.pause_event.is_set())

        # Thread unblocking on resume
        resumed = threading.Event()

        def worker():
            sess.pause_event.wait(timeout=5)
            resumed.set()

        t = threading.Thread(target=worker)
        t.start()

        # Wait a tiny bit and verify worker is blocked
        time.sleep(0.05)
        self.assertFalse(resumed.is_set())

        # Resume
        sess.resume()
        t.join(timeout=1.0)
        self.assertTrue(resumed.is_set())

        remove_session("thread_pause_test")

    def test_stop_event(self):
        sess = create_session("thread_stop_test")

        self.assertFalse(sess.is_stopped())
        sess.stop()
        self.assertTrue(sess.is_stopped())
        # Stopping also unblocks any pause wait
        self.assertTrue(sess.pause_event.is_set())

        remove_session("thread_stop_test")

    def test_api_endpoints_stop_pause_resume(self):
        import config
        headers = {"X-API-Key": config.get_settings().api_secret_key} if config.get_settings().api_secret_key else {}
        client = TestClient(app, headers=headers)

        # Register a test session
        sess = create_session("thread_api_test")

        # Test pause
        res_pause = client.post("/v1/chat/pause", json={"thread_id": "thread_api_test"})
        self.assertEqual(res_pause.status_code, 200)
        self.assertEqual(res_pause.json()["status"], "ok")
        self.assertFalse(sess.pause_event.is_set())

        # Test resume
        res_resume = client.post("/v1/chat/resume", json={"thread_id": "thread_api_test"})
        self.assertEqual(res_resume.status_code, 200)
        self.assertEqual(res_resume.json()["status"], "ok")
        self.assertTrue(sess.pause_event.is_set())

        # Test stop
        res_stop = client.post("/v1/chat/stop", json={"thread_id": "thread_api_test"})
        self.assertEqual(res_stop.status_code, 200)
        self.assertEqual(res_stop.json()["status"], "ok")
        self.assertTrue(sess.is_stopped())

        # Test non-existent thread
        res_none = client.post("/v1/chat/stop", json={"thread_id": "non_existent"})
        self.assertEqual(res_none.status_code, 200)
        self.assertEqual(res_none.json()["status"], "not_found")


if __name__ == "__main__":
    unittest.main()
