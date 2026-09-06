import time
import unittest
import queue
from stream_session import StreamSession, create_session, get_session, remove_session

class TestStreamSession(unittest.TestCase):
    def setUp(self):
        self.thread_id = f"test_thread_{int(time.time()*1000)}"
        self.sess = create_session(self.thread_id, task="Spiega docker", mode="chat")

    def tearDown(self):
        remove_session(self.thread_id)

    def test_session_lifecycle_and_broadcasting(self):
        sub1 = self.sess.subscribe()
        sub2 = self.sess.subscribe()

        self.assertTrue(self.sess.is_active())
        self.assertFalse(self.sess.is_paused())
        self.assertFalse(self.sess.is_stopped())

        # Test reasoning token
        self.sess.put({"type": "reasoning", "delta": "Sto pensando..."})
        self.assertEqual(self.sess.reasoning_content, "Sto pensando...")

        ev1 = sub1.get_nowait()
        ev2 = sub2.get_nowait()
        self.assertEqual(ev1["type"], "reasoning")
        self.assertEqual(ev2["type"], "reasoning")

        # Test content token
        self.sess.put({"type": "content", "delta": "Ciao mondo"})
        self.assertEqual(self.sess.partial_content, "Ciao mondo")

        # Test metrics
        self.sess.put({"type": "metrics", "metrics": {"prompt_tokens": 10, "completion_tokens": 20}})
        metrics = self.sess.get_metrics()
        self.assertEqual(metrics["completion_tokens"], 20)

        # Test snapshot for late subscriber
        sub3 = self.sess.subscribe()
        snap = self.sess.get_snapshot()
        self.assertEqual(snap["type"], "sync")
        self.assertEqual(snap["reasoning_content"], "Sto pensando...")
        self.assertEqual(snap["content"], "Ciao mondo")
        self.assertEqual(snap["metrics"]["completion_tokens"], 20)

        # Test pause / resume
        self.sess.pause()
        self.assertTrue(self.sess.is_paused())
        self.sess.resume()
        self.assertFalse(self.sess.is_paused())

        # Test completion
        self.sess.put({"type": "final", "response": {"response": "Ciao mondo finale"}})
        self.assertFalse(self.sess.is_active())
        self.assertEqual(self.sess.status, "completed")

    def test_client_disconnect_does_not_abort_session(self):
        sub = self.sess.subscribe()
        # Simulate client disconnecting (unsubscribing)
        self.sess.unsubscribe(sub)
        self.assertEqual(len(self.sess.subscribers), 0)

        # Agent worker continues in background
        self.sess.put({"type": "content", "delta": " continua a lavorare"})
        self.assertTrue(self.sess.is_active())
        self.assertIn("continua a lavorare", self.sess.partial_content)

        # New client (or page reload) reconnects
        new_sub = self.sess.subscribe()
        snapshot = self.sess.get_snapshot()
        self.assertIn("continua a lavorare", snapshot["content"])

        # Agent completes
        self.sess.put({"type": "final", "response": {"response": "finito"}})
        self.assertFalse(self.sess.is_active())

    def test_explicit_stop(self):
        self.sess.stop()
        self.assertTrue(self.sess.is_stopped())
        self.assertFalse(self.sess.is_active())
        self.assertEqual(self.sess.status, "stopped")

if __name__ == '__main__':
    unittest.main()
