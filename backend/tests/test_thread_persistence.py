import tempfile
import unittest

from app.core.config import settings
from app.memory import thread_store


class TestThreadPersistence(unittest.TestCase):
    def setUp(self):
        # Usa un db temporaneo per isolare i test
        self._orig_data_dir = settings.data_dir
        self.tmp_dir = tempfile.TemporaryDirectory()
        settings.data_dir = self.tmp_dir.name
        self.tmp_db = settings.checkpoint_db_path
        thread_store.init_db()

    def tearDown(self):
        settings.data_dir = self._orig_data_dir
        self.tmp_dir.cleanup()

    def test_save_user_message_immediate(self):
        thread_id = "test_thread_immediate"
        msg_id = thread_store.save_user_message(thread_id, "Ciao, spiegami l'effetto tunnel")
        self.assertTrue(msg_id.startswith("user_"))

        # Verifica che il messaggio sia presente
        messages = thread_store.get_thread_messages(thread_id)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["sender"], "user")
        self.assertEqual(messages[0]["content"], "Ciao, spiegami l'effetto tunnel")

        # Verifica che get_last_message restituisca il prompt utente se non c'è ancora la risposta
        last = thread_store.get_last_message(thread_id)
        self.assertEqual(last, "Ciao, spiegami l'effetto tunnel")

    def test_save_assistant_message(self):
        thread_id = "test_thread_assistant"
        thread_store.save_user_message(thread_id, "Qual è la capitale della Francia?")
        thread_store.save_assistant_message(thread_id, {
            "response": "La capitale della Francia è Parigi.",
            "mode": "chat",
            "tool_used": None,
            "reasoning_content": "Pensiero: domanda semplice di geografia."
        })

        messages = thread_store.get_thread_messages(thread_id)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[1]["sender"], "assistant")
        self.assertEqual(messages[1]["content"], "La capitale della Francia è Parigi.")
        self.assertEqual(messages[1]["reasoning_content"], "Pensiero: domanda semplice di geografia.")

        last = thread_store.get_last_message(thread_id)
        self.assertEqual(last, "La capitale della Francia è Parigi.")

    def test_metrics_persistence(self):
        thread_id = "test_thread_metrics_persisted"
        thread_store.save_user_message(thread_id, "Test metrics")
        thread_store.save_assistant_message(thread_id, {
            "response": "Risposta con statistiche",
            "mode": "chat",
            "metrics": {
                "prompt_tokens": 1500,
                "completion_tokens": 80,
                "total_tokens": 1580,
                "duration_s": 2.5,
                "llm_duration_s": 2.3,
                "tok_per_s": 34.8
            }
        })

        messages = thread_store.get_thread_messages(thread_id)
        self.assertEqual(len(messages), 2)
        self.assertIsNotNone(messages[1].get("metrics"))
        m = messages[1]["metrics"]
        self.assertEqual(m["prompt_tokens"], 1500)
        self.assertEqual(m["completion_tokens"], 80)
        self.assertEqual(m["total_tokens"], 1580)
        self.assertEqual(m["llm_duration_s"], 2.3)
        self.assertEqual(m["tok_per_s"], 34.8)

    def test_get_last_message_ignores_empty(self):
        thread_id = "test_thread_empty_assistant"
        thread_store.save_user_message(thread_id, "Prompt con assistente vuoto")
        # Simula assistente salvato con stringa vuota (es. durante thinking preliminare)
        thread_store.save_assistant_message(thread_id, {"response": "   ", "mode": "chat"})

        # Deve restituire il prompt dell'utente invece di una stringa vuota o None
        last = thread_store.get_last_message(thread_id)
        self.assertEqual(last, "Prompt con assistente vuoto")

    def test_save_user_message_with_empty_text_and_images(self):
        thread_id = "test_thread_images_no_text"
        fake_images = ["data:image/jpeg;base64,/9j/4AAQSkZJRg==", "data:image/png;base64,iVBORw0KGgo="]
        msg_id = thread_store.save_user_message(thread_id, "", images=fake_images)
        self.assertTrue(msg_id.startswith("user_"))

        messages = thread_store.get_thread_messages(thread_id)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["sender"], "user")
        self.assertEqual(messages[0]["content"], "")
        self.assertEqual(messages[0]["images"], fake_images)

    def test_web_prefetch_persistence(self):
        thread_id = "test_thread_web_prefetch_persisted"
        thread_store.save_user_message(thread_id, "Cos'è GPT Astra?")
        fake_prefetch = {
            "query": "Cos'è GPT Astra?",
            "provider_used": "SearXNG (it)",
            "latency_ms": 1250,
            "sources": [
                {
                    "title": "GPT Astra - Guida Completa",
                    "url": "https://example.com/astra",
                    "snippet": "Descrizione di GPT Astra..."
                }
            ]
        }
        thread_store.save_assistant_message(thread_id, {
            "response": "GPT Astra è un modello avanzato.",
            "mode": "ask",
            "web_prefetch": fake_prefetch
        })

        messages = thread_store.get_thread_messages(thread_id)
        self.assertEqual(len(messages), 2)
        ast_msg = messages[1]
        self.assertIsNotNone(ast_msg.get("web_prefetch"))
        self.assertEqual(ast_msg["web_prefetch"]["query"], "Cos'è GPT Astra?")
        self.assertEqual(ast_msg["web_prefetch"]["provider_used"], "SearXNG (it)")
        self.assertEqual(len(ast_msg["web_prefetch"]["sources"]), 1)
        self.assertEqual(ast_msg["web_prefetch"]["sources"][0]["url"], "https://example.com/astra")

if __name__ == "__main__":
    unittest.main()
