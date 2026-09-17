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

    def test_multistep_metrics_aggregation_without_compounding(self):
        sub = self.sess.subscribe()

        # Step 1: initial reasoning / tool selection
        m1 = {"prompt_tokens": 8000, "completion_tokens": 50, "total_tokens": 8050, "duration_s": 1.5}
        self.sess.put({"type": "metrics", "metrics": m1})
        ev1 = sub.get_nowait()
        self.assertEqual(ev1["type"], "metrics")
        self.assertEqual(ev1["metrics"]["completion_tokens"], 50)
        self.assertEqual(ev1["metrics"]["prompt_tokens"], 8000)
        self.assertEqual(ev1["metrics"]["total_tokens"], 8050)
        self.assertEqual(ev1["metrics"]["llm_duration_s"], 1.5)
        self.assertEqual(ev1["metrics"]["tok_per_s"], 33.3)

        # Step 2: intermediate observation processing
        m2 = {"prompt_tokens": 8500, "completion_tokens": 60, "total_tokens": 8560, "duration_s": 1.8}
        self.sess.put({"type": "metrics", "metrics": m2})
        ev2 = sub.get_nowait()
        self.assertEqual(ev2["metrics"]["completion_tokens"], 110)
        self.assertEqual(ev2["metrics"]["prompt_tokens"], 16500)
        self.assertEqual(ev2["metrics"]["total_tokens"], 16610)
        self.assertEqual(ev2["metrics"]["llm_duration_s"], 3.3)
        self.assertEqual(ev2["metrics"]["tok_per_s"], 33.3)

        # Step 3: final answer generation
        m3 = {"prompt_tokens": 9000, "completion_tokens": 76, "total_tokens": 9076, "duration_s": 2.0}
        self.sess.put({"type": "metrics", "metrics": m3})
        ev3 = sub.get_nowait()
        self.assertEqual(ev3["metrics"]["completion_tokens"], 186)
        self.assertEqual(ev3["metrics"]["prompt_tokens"], 25500)
        self.assertEqual(ev3["metrics"]["total_tokens"], 25686)
        self.assertEqual(ev3["metrics"]["llm_duration_s"], 5.3)
        self.assertEqual(ev3["metrics"]["tok_per_s"], 35.1)

        # Final get_metrics check
        final_metrics = self.sess.get_metrics()
        self.assertEqual(final_metrics["completion_tokens"], 186)
        self.assertEqual(final_metrics["prompt_tokens"], 25500)
        self.assertEqual(final_metrics["total_tokens"], 25686)
        self.assertEqual(final_metrics["llm_duration_s"], 5.3)
        self.assertEqual(final_metrics["tok_per_s"], 35.1)

if __name__ == '__main__':
    unittest.main()
