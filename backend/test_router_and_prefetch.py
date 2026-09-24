import json
import unittest
from unittest.mock import MagicMock, patch

from graph import should_prefetch_web, web_prefetch_node
from router import get_dynamic_capabilities_summary, route_turn
from schemas import ChatRequest


class TestRouterAndPrefetch(unittest.TestCase):
    def test_router_deterministic_shortcuts_act(self):
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
        ]
        for q in act_queries:
            decision = route_turn(q)
            self.assertEqual(decision.mode, "act", f"Expected 'act' for query: '{q}', got: '{decision.mode}'")
            self.assertFalse(decision.web_search_needed, f"Expected web_search_needed=False for query: '{q}'")

    def test_router_deterministic_shortcuts_chat(self):
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
            decision = route_turn(q)
            self.assertEqual(decision.mode, "chat", f"Expected 'chat' for query: '{q}', got: '{decision.mode}'")
            self.assertFalse(decision.web_search_needed, f"Expected web_search_needed=False for query: '{q}'")

    def test_router_deterministic_shortcuts_plan(self):
        plan_queries = [
            "crea un piano per migrare il database",
            "pianifica l'aggiornamento di Proxmox",
            "plan the migration to debian 13",
            "sviluppa una strategia per il backup",
        ]
        for q in plan_queries:
            decision = route_turn(q)
            self.assertEqual(decision.mode, "plan", f"Expected 'plan' for query: '{q}', got: '{decision.mode}'")

    def test_mode_continuity_in_act_thread(self):
        """Verifica che un messaggio di follow-up in un thread 'act' mantenga la modalità 'act'."""
        follow_ups = [
            "Ok, la descrizione di esso deve contenere 'Test test'",
            "Ora eliminalo",
            "cambia l'orario alle 15:00",
            "e per la cartella /root?",
        ]
        # Con chiamata LLM mockata che rispetta la continuity
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "mode": "act",
                        "web_search_needed": False,
                        "web_search_query": None,
                        "reasoning": "Follow up in active action thread"
                    })
                }
            }]
        }
        with patch("requests.post", return_value=mock_response):
            for q in follow_ups:
                decision = route_turn(
                    user_input=q,
                    previous_mode="act",
                    last_tool_used="calendar_create_event",
                    conversation_context="User: Crea un evento\nAssistant: Evento creato con id 123"
                )
                self.assertEqual(decision.mode, "act", f"Expected 'act' continuity for follow-up: '{q}'")

    def test_router_model_json_parsing_and_leak_immunity(self):
        """Verifica la resilienza del parser a tag think, markdown fences e risposte complesse."""
        # 1. Risposta con tag <think> e json fence
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": "<think>Let's ponder: this is external question.</think>\n```json\n{\"mode\": \"ask\", \"web_search_needed\": true, \"web_search_query\": \"DLSS 5 features and release\", \"reasoning\": \"Hardware release inquiry\"}\n```"
                }
            }]
        }
        with patch("requests.post", return_value=mock_response):
            decision = route_turn("Parlami del DLSS 5")
            self.assertEqual(decision.mode, "ask")
            self.assertTrue(decision.web_search_needed)
            self.assertEqual(decision.web_search_query, "DLSS 5 features and release")

        # 2. Risposta raw non-JSON con think tag (fallback parsing resiliente)
        mock_raw = MagicMock()
        mock_raw.status_code = 200
        mock_raw.json.return_value = {
            "choices": [{
                "message": {
                    "content": "<think>Thinking about options: chat, ask, act, plan.</think> act"
                }
            }]
        }
        with patch("requests.post", return_value=mock_raw):
            decision = route_turn("qualcosa di anomalo 123")
            self.assertEqual(decision.mode, "act")

    def test_dynamic_capabilities_summary(self):
        """Verifica che il riassunto delle capabilities dinamiche sia popolato e utilizzi la cache."""
        summary1 = get_dynamic_capabilities_summary()
        self.assertIsInstance(summary1, str)
        self.assertIn("Calendar", summary1)
        self.assertIn("Automations", summary1)
        # Seconda chiamata immediata deve restituire la cache
        summary2 = get_dynamic_capabilities_summary()
        self.assertEqual(summary1, summary2)

    def test_should_prefetch_web_auto_mode(self):
        # 1. Deterministic local container ops -> False
        self.assertFalse(should_prefetch_web("elenca i file in /opt del container 125"))
        self.assertFalse(should_prefetch_web("stato container 125"))
        self.assertFalse(should_prefetch_web("stop ct 125"))
        self.assertFalse(should_prefetch_web("riavvia il container 125"))

        # 2. Greetings -> False
        self.assertFalse(should_prefetch_web("ciao come stai?"))

        # 3. External questions with mocked model -> True
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "mode": "ask",
                        "web_search_needed": True,
                        "web_search_query": "Claude 3.7 vs GPT-5 benchmarks",
                        "reasoning": "Comparison of external models"
                    })
                }
            }]
        }
        with patch("requests.post", return_value=mock_response):
            self.assertTrue(should_prefetch_web("Confronta Claude e GPT-5"))

    def test_web_prefetch_node_modes(self):
        mock_search_result = {
            "sources": [{"title": "Test", "url": "https://example.com", "snippet": "Sample"}],
            "raw_text": "Sample text",
            "mode": "live"
        }

        with patch("registry.web_search_service.execute_search", return_value=mock_search_result):
            # 1. Mode OFF: should skip
            s_off = {"task": "quali sono le novità di debian 13?", "web_search": "off"}
            res_off = web_prefetch_node(s_off)
            self.assertIsNone(res_off.get("web_prefetch_data"))

            # 2. Mode False (boolean): should skip
            s_false = {"task": "quali sono le novità di debian 13?", "web_search": False}
            res_false = web_prefetch_node(s_false)
            self.assertIsNone(res_false.get("web_prefetch_data"))

            # 3. Mode AUTO: with route_decision web_search_needed=False -> skip
            s_auto_skip = {
                "task": "spegni il container 125",
                "web_search": "auto",
                "route_decision": {"web_search_needed": False, "mode": "act"}
            }
            res_auto_skip = web_prefetch_node(s_auto_skip)
            self.assertIsNone(res_auto_skip.get("web_prefetch_data"))

            # 4. Mode AUTO: with route_decision web_search_needed=True -> execute with reformulated query
            s_auto_exec = {
                "task": "Parlami del DLSS 5",
                "web_search": "auto",
                "route_decision": {
                    "web_search_needed": True,
                    "web_search_query": "NVIDIA DLSS 5 announcement",
                    "mode": "ask"
                }
            }
            res_auto_exec = web_prefetch_node(s_auto_exec)
            self.assertIsNotNone(res_auto_exec.get("web_prefetch_data"))
            self.assertEqual(len(res_auto_exec["web_prefetch_data"]["sources"]), 1)
            self.assertEqual(res_auto_exec["web_prefetch_metadata"]["query"], "NVIDIA DLSS 5 announcement")

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
