"""Tests for Visual Query Grounding and Image-Aware Web Prefetch."""

import unittest
from unittest.mock import MagicMock, patch

from graph import (
    formulate_visual_search_query,
    is_purely_visual_request,
    web_prefetch_node,
)


class TestVisualWebPrefetch(unittest.TestCase):
    def test_is_purely_visual_request_true(self):
        """Purely visual/perceptive tasks should not trigger external web prefetch."""
        self.assertTrue(is_purely_visual_request(""))
        self.assertTrue(is_purely_visual_request("   "))
        self.assertTrue(is_purely_visual_request("Cosa vedi in questa immagine?"))
        self.assertTrue(is_purely_visual_request("Descrivi l'immagine in dettaglio"))
        self.assertTrue(is_purely_visual_request("Cosa c'è nell'immagine?"))
        self.assertTrue(is_purely_visual_request("Analizza e descrivi cosa rappresenta"))
        self.assertTrue(is_purely_visual_request("Trascrivi il testo presente nella foto"))

    def test_is_purely_visual_request_false(self):
        """Tasks with search, pricing, technical or market intents must NOT be treated as purely visual."""
        self.assertFalse(is_purely_visual_request("Cerca informazioni e prezzo attuale di questo visore"))
        self.assertFalse(is_purely_visual_request("Quanto costa questo prodotto?"))
        self.assertFalse(is_purely_visual_request("Dammi informazioni su questo visore, specifiche, prezzo ecc"))
        self.assertFalse(is_purely_visual_request("Trova recensioni e specifiche tecniche"))
        self.assertFalse(is_purely_visual_request("È compatibile con le batterie 2S?"))
        self.assertFalse(is_purely_visual_request("Dove posso comprare questo componente?"))
        self.assertFalse(is_purely_visual_request("Cerca online il manuale d'uso"))

    @patch("graph._call_llm")
    def test_formulate_visual_search_query_success(self, mock_llm):
        """Micro-pass should extract subject from image and return a clean query."""
        mock_llm.return_value = {
            "content": '"Eachine EV800DM prezzo specifiche"\n'
        }
        query = formulate_visual_search_query(
            task="Cerca informazioni e prezzo attuale",
            images=["data:image/jpeg;base64,mock123"],
            model="gemini-2.5-flash"
        )
        self.assertEqual(query, "Eachine EV800DM prezzo specifiche")
        # Verify LLM was called with stream_mode='none' and reasoning_budget=0 for speed
        mock_llm.assert_called_once()
        _, kwargs = mock_llm.call_args
        self.assertEqual(kwargs.get("stream_mode"), "none")
        self.assertEqual(kwargs.get("reasoning_budget"), 0)
        self.assertEqual(kwargs.get("temperature"), 0.0)

    @patch("graph._call_llm")
    def test_formulate_visual_search_query_prefixes_cleaned(self, mock_llm):
        """Prefixed responses like 'Query: ...' should be cleanly stripped."""
        mock_llm.return_value = "Query: Apple iMac G4 specifiche tecniche"
        query = formulate_visual_search_query(
            task="Dimmi che computer è e le sue specifiche",
            images=["data:image/jpeg;base64,mock123"]
        )
        self.assertEqual(query, "Apple iMac G4 specifiche tecniche")

    @patch("graph._call_llm")
    def test_formulate_visual_search_query_failure_fallback(self, mock_llm):
        """If the vision micro-pass fails, it should gracefully fall back to original task."""
        mock_llm.side_effect = RuntimeError("API timeout")
        query = formulate_visual_search_query(
            task="Cerca prezzo visore",
            images=["data:image/jpeg;base64,mock123"]
        )
        self.assertEqual(query, "Cerca prezzo visore")

    @patch("registry.web_search_service.execute_search")
    def test_web_prefetch_skips_purely_visual(self, mock_search):
        """Purely visual request with image should skip prefetch entirely."""
        state = {
            "task": "Descrivi questa immagine",
            "web_search": True,
            "images": ["data:image/jpeg;base64,mock123"]
        }
        res_state = web_prefetch_node(state)
        mock_search.assert_not_called()
        self.assertNotIn("web_prefetch_data", res_state)

    @patch("graph.formulate_visual_search_query")
    @patch("registry.web_search_service.execute_search")
    def test_web_prefetch_executes_grounded_query(self, mock_search, mock_formulate):
        """Search-oriented request with image should ground query and search with it."""
        mock_formulate.return_value = "Eachine EV800DM prezzo specifiche"
        mock_search.return_value = {
            "query": "Eachine EV800DM prezzo specifiche",
            "success": True,
            "sources": [{"title": "Banggood", "url": "https://example.com/ev800dm"}],
            "summary_text": "Eachine EV800DM costa circa 85€",
            "provider_used": "SearXNG",
            "latency_ms": 350
        }

        state = {
            "task": "Cerca informazioni e prezzo attuale di questo visore",
            "web_search": True,
            "images": ["data:image/jpeg;base64,mock123"]
        }
        res_state = web_prefetch_node(state)

        mock_formulate.assert_called_once_with(
            "Cerca informazioni e prezzo attuale di questo visore",
            ["data:image/jpeg;base64,mock123"],
            model=None
        )
        mock_search.assert_called_once()
        _, search_kwargs = mock_search.call_args
        self.assertEqual(search_kwargs.get("query"), "Eachine EV800DM prezzo specifiche")

        self.assertIn("web_prefetch_data", res_state)
        self.assertEqual(res_state["web_prefetch_data"]["query"], "Eachine EV800DM prezzo specifiche")
        self.assertEqual(res_state["web_prefetch_metadata"]["query"], "Eachine EV800DM prezzo specifiche")


if __name__ == "__main__":
    unittest.main()
