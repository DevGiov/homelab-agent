import json
import queue
import unittest
from unittest.mock import MagicMock, patch

from graph import _call_llm, _call_llm_structured, stream_queue, stream_reasoning_phase_count
from tool_schemas import ToolSelection


class TestStreamingIsolation(unittest.TestCase):

    def setUp(self):
        self.q = queue.Queue()
        stream_queue.set(self.q)
        stream_reasoning_phase_count.set(0)

    def tearDown(self):
        stream_queue.set(None)
        stream_reasoning_phase_count.set(0)

    @patch("graph.get_provider")
    def test_reasoning_only_filters_out_content_events(self, mock_get_provider):
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        def fake_chat(messages, **kwargs):
            cb = kwargs.get("stream_callback")
            self.assertIsNotNone(cb)
            cb({"type": "reasoning", "delta": "Sto analizzando se servono tool..."})
            cb({"type": "content", "delta": '{"tool_needed": false, "final_answer": "test"}'})
            return {"content": '{"tool_needed": false, "final_answer": "test"}', "reasoning_content": "Sto analizzando"}

        mock_provider.chat.side_effect = fake_chat

        res = _call_llm("prompt", stream_mode="reasoning_only", reasoning_phase="Analisi Tool")
        self.assertIn("content", res)

        events = []
        while not self.q.empty():
            events.append(self.q.get_nowait())

        # Deve esserci l'header di fase e il reasoning delta
        types = [e["type"] for e in events]
        self.assertIn("reasoning", types)
        # NON deve MAI esserci alcun evento content
        self.assertNotIn("content", types)

        deltas = [e["delta"] for e in events]
        full_reasoning = "".join(deltas)
        self.assertIn("#### 🔍 Analisi Tool", full_reasoning)
        self.assertIn("Sto analizzando se servono tool...", full_reasoning)
        self.assertNotIn("tool_needed", full_reasoning)

    @patch("graph.get_provider")
    def test_stream_mode_none_suppresses_all_events(self, mock_get_provider):
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        def fake_chat(messages, **kwargs):
            cb = kwargs.get("stream_callback")
            self.assertIsNone(cb, "stream_callback deve essere None quando stream_mode='none'")
            return {"content": "fatto 1\nfatto 2", "reasoning_content": "pensiero interno"}

        mock_provider.chat.side_effect = fake_chat

        res = _call_llm("prompt", stream_mode="none")
        self.assertTrue(self.q.empty(), "La coda stream deve rimanere completamente vuota")

    @patch("graph.get_provider")
    def test_structured_output_sets_raw_thinking_and_isolates_content(self, mock_get_provider):
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        json_body = json.dumps({
            "tool_needed": False,
            "tool_name": None,
            "arguments": {},
            "reasoning": "Prefetch sufficiente",
            "final_answer": "Ecco la risposta all'utente."
        })

        def fake_chat(messages, **kwargs):
            cb = kwargs.get("stream_callback")
            if cb:
                cb({"type": "reasoning", "delta": "pensiero nativo"})
                cb({"type": "content", "delta": json_body})
            return {"content": json_body, "reasoning_content": "pensiero nativo"}

        mock_provider.chat.side_effect = fake_chat

        selection = _call_llm_structured("prompt", "sys", ToolSelection, reasoning_phase="Analisi e Selezione Tool")
        self.assertIsNotNone(selection)
        self.assertFalse(selection.tool_needed)
        self.assertEqual(selection.raw_thinking, "pensiero nativo")

        # Verifica eventi in coda
        events = []
        while not self.q.empty():
            events.append(self.q.get_nowait())

        types = [e["type"] for e in events]
        self.assertNotIn("content", types, "Nessun JSON grezzo deve essere emesso su content")
        self.assertIn("reasoning", types)

    @patch("graph.get_provider")
    def test_multi_phase_reasoning_headers(self, mock_get_provider):
        mock_provider = MagicMock()
        mock_get_provider.return_value = mock_provider

        def fake_chat_1(messages, **kwargs):
            cb = kwargs.get("stream_callback")
            cb({"type": "reasoning", "delta": "fase 1 thinking"})
            return {"content": "step 1", "reasoning_content": "fase 1 thinking"}

        def fake_chat_2(messages, **kwargs):
            cb = kwargs.get("stream_callback")
            cb({"type": "reasoning", "delta": "fase 2 thinking"})
            return {"content": "step 2", "reasoning_content": "fase 2 thinking"}

        mock_provider.chat.side_effect = fake_chat_1
        _call_llm("prompt 1", stream_mode="reasoning_only", reasoning_phase="Analisi Tool")

        mock_provider.chat.side_effect = fake_chat_2
        _call_llm("prompt 2", stream_mode="all", reasoning_phase="Elaborazione Risposta")

        events = []
        while not self.q.empty():
            events.append(self.q.get_nowait())

        all_reasoning = "".join(e["delta"] for e in events if e["type"] == "reasoning")
        self.assertIn("#### 🔍 Analisi Tool", all_reasoning)
        self.assertIn("fase 1 thinking", all_reasoning)
        self.assertIn("#### 💡 Elaborazione Risposta", all_reasoning)
        self.assertIn("fase 2 thinking", all_reasoning)
        self.assertIn("---", all_reasoning)


if __name__ == "__main__":
    unittest.main()
