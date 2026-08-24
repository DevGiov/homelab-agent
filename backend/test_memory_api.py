"""Test automatici per endpoint di gestione memoria e modalità incognito."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Isola il DB in un file temporaneo PRIMA degli import
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_checkpoints_mem.db")
os.environ["CHECKPOINT_DB_PATH"] = _tmp_db
os.environ["ALLOW_INSECURE"] = "1"

from fastapi.testclient import TestClient
from api import api
import vector_store

class TestMemoryAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        vector_store.init_vector_db()
        cls.client = TestClient(api)

    def setUp(self):
        # Pulisci memorie prima di ogni test
        vector_store.clear_all_memories()

    def test_add_and_list_memory(self):
        # 1. Aggiungi fatto
        res = self.client.post("/v1/memory", json={
            "content": "L'utente preferisce Proxmox VE 9 per le VM",
            "kind": "fact",
            "thread_id": "test_t1"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("id", data)
        mem_id = data["id"]

        # 2. Elenca memorie
        list_res = self.client.get("/v1/memory?kind=fact")
        self.assertEqual(list_res.status_code, 200)
        list_data = list_res.json()
        self.assertEqual(list_data["total"], 1)
        self.assertEqual(list_data["memories"][0]["id"], mem_id)
        self.assertIn("Proxmox VE 9", list_data["memories"][0]["content"])

    def test_delete_single_memory(self):
        # Aggiungi
        res = self.client.post("/v1/memory", json={
            "content": "Fatto temporaneo da cancellare",
            "kind": "fact"
        })
        mem_id = res.json()["id"]

        # Elimina
        del_res = self.client.delete(f"/v1/memory/{mem_id}")
        self.assertEqual(del_res.status_code, 200)
        self.assertEqual(del_res.json()["status"], "deleted")

        # Verifica che sia vuoto
        list_res = self.client.get("/v1/memory")
        self.assertEqual(list_res.json()["total"], 0)

    def test_clear_all_memory(self):
        # Aggiungi multiple memorie
        self.client.post("/v1/memory", json={"content": "Fatto 1"})
        self.client.post("/v1/memory", json={"content": "Fatto 2"})
        self.assertEqual(self.client.get("/v1/memory").json()["total"], 2)

        # Svuota tutto
        clear_res = self.client.delete("/v1/memory")
        self.assertEqual(clear_res.status_code, 200)
        self.assertGreaterEqual(clear_res.json()["deleted_count"], 2)

        # Verifica totale 0
        self.assertEqual(self.client.get("/v1/memory").json()["total"], 0)

    def test_incognito_chat_does_not_save_facts(self):
        # Esegui una chat in incognito con mock dell'LLM
        with patch("graph._call_llm") as mock_llm:
            mock_llm.return_value = {
                "content": "Risposta di test in incognito",
                "reasoning_content": "Ragionamento isolato"
            }
            res = self.client.post("/v1/chat", json={
                "input": "Messaggio di prova in incognito",
                "thread_id": "thread_incognito_test",
                "incognito": True,
                "force_mode": "chat"
            })
            self.assertEqual(res.status_code, 200)

            # Verifica che NESSUN fatto sia stato salvato nel vector store
            list_res = self.client.get("/v1/memory")
            self.assertEqual(list_res.json()["total"], 0)


    def test_search_memory(self):
        self.client.post("/v1/memory", json={"content": "Il container LXC usa Debian 12", "kind": "fact"})
        self.client.post("/v1/memory", json={"content": "IP del gateway è 192.168.1.1", "kind": "fact"})

        search_res = self.client.get("/v1/memory/search?query=Debian&kind=fact")
        self.assertEqual(search_res.status_code, 200)
        results = search_res.json()["results"]
        self.assertGreater(len(results), 0)
        self.assertIn("Debian", results[0]["content"])


if __name__ == "__main__":
    unittest.main()

