import unittest
from unittest.mock import MagicMock, patch

from app.agent.agent_loop import (
    _normalize_call_signature,
    _query_jaccard_similarity,
    run_agent_loop,
)
from app.agent.tool_schemas import ToolSelection
from app.registry.search_ranking import is_result_relevant


class TestEntityRelevance(unittest.TestCase):
    def test_generic_terms_rejected_when_specific_entity_present(self):
        query = "GPT Astra vs GPT 5.6 Sol"
        # Generic ChatGPT page matching only 'GPT' or 'ChatGPT' or 'modello'
        generic_title = "ChatGPT Online Gratis: Prova il modello AI"
        generic_snippet = "Usa ChatGPT gratis online senza registrazione per interagire con l'intelligenza artificiale."
        self.assertFalse(is_result_relevant(query, generic_title, generic_snippet))

    def test_specific_entity_accepted(self):
        query = "GPT Astra vs GPT 5.6 Sol"
        # Title matching specific entity 'Astra'
        valid_title = "OpenAI reveals GPT-6 Astra and GPT-5.6 Sol details"
        valid_snippet = "The new model Astra introduces autonomous computing and reasoning capabilities."
        self.assertTrue(is_result_relevant(query, valid_title, valid_snippet))

    def test_generic_query_not_blocked(self):
        query = "confronto modelli ai"
        title = "Confronto tra i principali modelli di intelligenza artificiale"
        snippet = "Guida completa sui migliori modelli AI del 2026."
        self.assertTrue(is_result_relevant(query, title, snippet))


class TestAntiLoop(unittest.TestCase):
    def test_call_signature_and_jaccard(self):
        sig1 = _normalize_call_signature("web_search", {"query": ' "GPT Astra vs GPT 5.6 Sol" '})
        sig2 = _normalize_call_signature("web_search", {"query": "gpt astra vs gpt 5.6 sol"})
        self.assertEqual(sig1, sig2)

        sim = _query_jaccard_similarity("GPT Astra vs GPT 5.6 Sol", "GPT-6 Astra vs GPT 5.6 Sol")
        self.assertGreater(sim, 0.70)

    def test_agent_loop_breaks_on_repeated_calls(self):
        # Mock structured call to return the SAME web_search call repeatedly
        mock_selection = ToolSelection(
            tool_needed=True,
            tool_name="web_search",
            arguments={"query": "GPT Astra vs GPT 5.6 Sol"},
            reasoning="Cerco ancora"
        )
        mock_call_structured = MagicMock(return_value=mock_selection)
        mock_call_llm = MagicMock(return_value={"content": "Risposta finale sintetizzata", "reasoning_content": "CoT finale"})

        with patch("app.agent.agent_loop.get_registry_manager") as mock_mgr_getter:
            mock_mgr = MagicMock()
            mock_mgr.get_tools_for_mode.return_value = [
                {"name": "web_search", "description": "search web", "parameters": {}}
            ]
            mock_mgr.execute_tool.return_value = {"results": [{"title": "GPT Astra vs Sol", "snippet": "info"}]}
            mock_mgr_getter.return_value = mock_mgr

            # Run in 'ask' mode (which allows max_tool_calls > 1)
            res = run_agent_loop(
                task="Confronta GPT Astra e GPT 5.6 Sol",
                mode="ask",
                call_llm_fn=mock_call_llm,
                call_llm_structured_fn=mock_call_structured,
            )

            # Verification:
            # 1. execute_tool should only be called ONCE (the second attempt is stopped by anti-loop)
            self.assertEqual(mock_mgr.execute_tool.call_count, 1)

            # 2. Final response should be produced via synthesis
            self.assertEqual(res["final_response"], "Risposta finale sintetizzata")

            # 3. Execution trace should record the duplicate block
            duplicate_blocks = [t for t in res["execution_trace"] if t.get("duplicate_blocked")]
            self.assertTrue(len(duplicate_blocks) >= 1)


class TestSamplingPayload(unittest.TestCase):
    def test_sampling_comes_from_the_model_profile(self):
        from app.llm.providers import OpenAICompatProvider
        from app.llm.reasoning import resolve

        provider = OpenAICompatProvider(base_url="http://mock:8080/v1", default_model="Qwen3.6-35B-HugeCtx")
        payload = provider._build_payload([{"role": "user", "content": "hello"}], "Qwen3.6-35B-HugeCtx", 100,
                                          resolve("Qwen3.6-35B-HugeCtx", "medium"))
        self.assertEqual((payload["temperature"], payload["top_p"], payload["top_k"], payload["presence_penalty"]), (0.6, 0.95, 20, 0.0))
        self.assertNotIn("frequency_penalty", payload)


if __name__ == "__main__":
    unittest.main()
