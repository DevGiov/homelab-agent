import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock

import config
import thread_store


class TestThreadPersistence(unittest.TestCase):
    def setUp(self):
        # Usa un db temporaneo per isolare i test
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_db = os.path.join(self.tmp_dir.name, "test_checkpoints.db")
        config.CHECKPOINT_DB_PATH = self.tmp_db
        thread_store.init_db()

    def tearDown(self):
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

    def test_get_last_message_ignores_empty(self):
        thread_id = "test_thread_empty_assistant"
        thread_store.save_user_message(thread_id, "Prompt con assistente vuoto")
        # Simula assistente salvato con stringa vuota (es. durante thinking preliminare)
        thread_store.save_assistant_message(thread_id, {"response": "   ", "mode": "chat"})

        # Deve restituire il prompt dell'utente invece di una stringa vuota o None
        last = thread_store.get_last_message(thread_id)
        self.assertEqual(last, "Prompt con assistente vuoto")

    def test_backfill_from_interrupted_state_history(self):
        thread_id = "test_interrupted_thread"

        # Crea un mock di app_graph con snapshot non-terminale (next != ())
        class MockSnapshot:
            def __init__(self, next_nodes, values):
                self.next = next_nodes
                self.values = values

        mock_graph = MagicMock()
        # Simulazione: 2 snapshot non-terminali, interrotti su 'agent_loop'
        mock_graph.get_state_history.return_value = [
            MockSnapshot(
                next_nodes=("agent_loop",),
                values={
                    "task": "Calcola la traiettoria orbitale",
                    "mode": "act",
                    "final_response": None,
                    "reasoning_content": "Sto calcolando...",
                    "execution_trace": [{"step": 1, "reasoning": "Analisi iniziale"}]
                }
            ),
            MockSnapshot(
                next_nodes=("retrieve_memory",),
                values={"task": "Calcola la traiettoria orbitale"}
            )
        ]

        # Inizialmente thread_messages è vuoto
        self.assertEqual(thread_store.get_thread_messages(thread_id), [])

        # Esegue il backfill
        reconstructed = thread_store.backfill_from_state_history(thread_id, mock_graph)
        self.assertEqual(len(reconstructed), 2)

        # Messaggio utente recuperato
        self.assertEqual(reconstructed[0]["sender"], "user")
        self.assertEqual(reconstructed[0]["content"], "Calcola la traiettoria orbitale")

        # Messaggio assistente parziale recuperato
        self.assertEqual(reconstructed[1]["sender"], "assistant")
        self.assertIn("Esecuzione interrotta", reconstructed[1]["content"])
        self.assertEqual(reconstructed[1]["reasoning_content"], "Sto calcolando...")

        # get_last_message funziona
        last = thread_store.get_last_message(thread_id)
        self.assertIsNotNone(last)

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

    def test_backfill_preserves_images(self):
        thread_id = "test_backfill_with_images"
        fake_images = ["data:image/jpeg;base64,testdata123"]

        class MockSnapshot:
            def __init__(self, next_nodes, values):
                self.next = next_nodes
                self.values = values

        mock_graph = MagicMock()
        mock_graph.get_state_history.return_value = [
            MockSnapshot(
                next_nodes=(),
                values={
                    "task": "Analizza e descrivi l'immagine allegata.",
                    "mode": "chat",
                    "final_response": "Questa è una bella foto.",
                    "images": fake_images
                }
            )
        ]

        reconstructed = thread_store.backfill_from_state_history(thread_id, mock_graph)
        self.assertEqual(len(reconstructed), 2)
        self.assertEqual(reconstructed[0]["sender"], "user")
        self.assertEqual(reconstructed[0]["images"], fake_images)

        stored = thread_store.get_thread_messages(thread_id)
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[0]["images"], fake_images)


if __name__ == "__main__":
    unittest.main()
