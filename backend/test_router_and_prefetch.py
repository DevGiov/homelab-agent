import unittest
from unittest.mock import patch, MagicMock
import router
from graph import should_prefetch_web, web_prefetch_node
from schemas import ChatRequest

class TestRouterAndPrefetch(unittest.TestCase):
    def test_router_rule_classification_act(self):
        act_queries = [
            "dimmi i file in /opt",
            "what files are in /opt",
            "cosa c'è nella cartella /opt del 125",
            "spegni ct 125",
            "riavvia il container 125",
            "reboot lxc 125",
            "exec hostname",
            "mostrami i container",
            "list containers",
            "controlla lo stato del container 125",
            "check status of ct 125",
            "fai un backup del ct 125",
            "run ls -la inside container 125",
        ]
        for q in act_queries:
            mode = router.classify_mode(q)
            self.assertEqual(mode, "act", f"Expected 'act' for query: '{q}', got: '{mode}'")

    def test_router_rule_classification_ask(self):
        ask_queries = [
            "cosa è un container lxc?",
            "what is a container in proxmox?",
            "differenza tra container e vm",
            "spiegami come funziona ZFS",
            "what is proxmox ve",
            "come funziona il protocollo HTTP",
            "chi ha inventato linux?",
        ]
        for q in ask_queries:
            mode = router.classify_mode(q)
            self.assertEqual(mode, "ask", f"Expected 'ask' for query: '{q}', got: '{mode}'")

    def test_router_rule_classification_chat(self):
        chat_queries = [
            "ciao",
            "hello",
            "buongiorno",
            "who are you?",
            "chi sei?",
            "grazie mille",
            "thanks!",
        ]
        for q in chat_queries:
            mode = router.classify_mode(q)
            self.assertEqual(mode, "chat", f"Expected 'chat' for query: '{q}', got: '{mode}'")

    def test_router_rule_classification_plan(self):
        plan_queries = [
            "crea un piano per migrare il database",
            "pianifica l'aggiornamento di Proxmox",
            "plan the migration to debian 13",
            "sviluppa una strategia per il backup",
        ]
        for q in plan_queries:
            mode = router.classify_mode(q)
            self.assertEqual(mode, "plan", f"Expected 'plan' for query: '{q}', got: '{mode}'")

    def test_router_reasoning_leak_immunity(self):
        # Even if query falls to neural router, <think> tokens shouldn't mislead classification
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "<think>Options: chat, ask, act, plan. Let's think: user asks something tricky. Maybe chat? No, definitely act.</think> act"}}]
        }
        with patch("requests.post", return_value=mock_response):
            mode = router.classify_mode("qualcosa di assolutamente sconosciuto xyz123")
            self.assertEqual(mode, "act")

    def test_should_prefetch_web_auto_mode(self):
        # General knowledge -> True
        self.assertTrue(should_prefetch_web("quali sono le novità di debian 13?"))
        self.assertTrue(should_prefetch_web("who won the 2024 world cup?"))
        self.assertTrue(should_prefetch_web("spiegami cosa è l'algoritmo Raft"))

        # Pure homelab / container ops -> False
        self.assertFalse(should_prefetch_web("elenca i file in /opt del container 125"))
        self.assertFalse(should_prefetch_web("stato container 125"))
        self.assertFalse(should_prefetch_web("stop ct 125"))
        self.assertFalse(should_prefetch_web("riavvia il servizio nginx su ct 137"))
        self.assertFalse(should_prefetch_web("exec_lxc_command vmid 125 command ls"))

        # Mixed homelab + external info -> True
        self.assertTrue(should_prefetch_web(
            "cerca sul web l'ultima release di immich e aggiorna il container 125"
        ))
        self.assertTrue(should_prefetch_web(
            "search online for nginx reverse proxy configuration for jellyfin and check ct 125"
        ))

        # Greetings -> False
        self.assertFalse(should_prefetch_web("ciao come stai?"))

    def test_web_prefetch_node_modes(self):
        mock_search_result = {
            "sources": [{"title": "Test", "url": "https://example.com", "snippet": "Sample"}],
            "raw_text": "Sample text",
            "mode": "live"
        }

        with patch("registry.web_search_service.execute_search", return_value=mock_search_result):
            # 1. Mode OFF: should skip even for general queries
            s_off = {"task": "quali sono le novità di debian 13?", "web_search": "off"}
            res_off = web_prefetch_node(s_off)
            self.assertIsNone(res_off.get("web_prefetch_data"))

            # 2. Mode False (boolean): should skip
            s_false = {"task": "quali sono le novità di debian 13?", "web_search": False}
            res_false = web_prefetch_node(s_false)
            self.assertIsNone(res_false.get("web_prefetch_data"))

            # 3. Mode AUTO: skips for container commands
            s_auto_cmd = {"task": "spegni il container 125", "web_search": "auto"}
            res_auto_cmd = web_prefetch_node(s_auto_cmd)
            self.assertIsNone(res_auto_cmd.get("web_prefetch_data"))

            # 4. Mode AUTO: executes for general questions
            s_auto_q = {"task": "chi ha scritto la Divina Commedia?", "web_search": "auto"}
            res_auto_q = web_prefetch_node(s_auto_q)
            self.assertIsNotNone(res_auto_q.get("web_prefetch_data"))

            # 5. Mode ON: executes even for container commands
            s_on = {"task": "spegni il container 125", "web_search": "on"}
            res_on = web_prefetch_node(s_on)
            self.assertIsNotNone(res_on.get("web_prefetch_data"))

    def test_chat_request_schema_normalization(self):
        r1 = ChatRequest(input="test", web_search="auto")
        self.assertEqual(r1.web_search, "auto")

        r2 = ChatRequest(input="test", web_search="on")
        self.assertEqual(r2.web_search, "on")

        r3 = ChatRequest(input="test", web_search="off")
        self.assertEqual(r3.web_search, "off")

        r4 = ChatRequest(input="test", web_search=True)
        self.assertEqual(r4.web_search, "on")

        r5 = ChatRequest(input="test", web_search=False)
        self.assertEqual(r5.web_search, "off")

        r6 = ChatRequest(input="test")
        self.assertEqual(r6.web_search, "auto")

if __name__ == "__main__":
    unittest.main()
