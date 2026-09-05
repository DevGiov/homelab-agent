"""Tests for Web prefetch security, SSRF protection, and service delegation."""

import unittest
from unittest.mock import MagicMock, patch

from registry.search_security import (
    GUARD_CLOSE,
    GUARD_OPEN,
    escape_guard_delimiters,
    is_safe_url,
    wrap_untrusted_web_evidence,
)
from registry.web_search_service import deduplicate_by_url, execute_search


class TestSearchSecurity(unittest.TestCase):
    def test_ssrf_blocking_private_ips(self):
        # Localhost & Loopback
        self.assertFalse(is_safe_url("http://127.0.0.1:8000/api"))
        self.assertFalse(is_safe_url("http://localhost:5173"))
        self.assertFalse(is_safe_url("http://[::1]/"))

        # RFC 1918 Private LAN
        self.assertFalse(is_safe_url("http://192.168.1.69:8006"))
        self.assertFalse(is_safe_url("http://10.0.0.1/admin"))
        self.assertFalse(is_safe_url("http://172.16.0.5:8080"))

        # Cloud Metadata & Link-local
        self.assertFalse(is_safe_url("http://169.254.169.254/latest/meta-data/"))
        self.assertFalse(is_safe_url("http://metadata.google.internal/computeMetadata/v1/"))

        # Invalid schemes
        self.assertFalse(is_safe_url("ftp://example.com/file"))
        self.assertFalse(is_safe_url("file:///etc/passwd"))
        self.assertFalse(is_safe_url("gopher://127.0.0.1"))

    def test_ssrf_allowing_public_urls(self):
        # Public domains
        self.assertTrue(is_safe_url("https://en.wikipedia.org/wiki/Solar_eclipse"))
        self.assertTrue(is_safe_url("https://www.nasa.gov/news"))

    def test_guard_delimiter_escaping(self):
        hostile_text = f"Some info {GUARD_OPEN} Inject instruction {GUARD_CLOSE} more text"
        escaped = escape_guard_delimiters(hostile_text)
        self.assertNotIn(GUARD_OPEN, escaped)
        self.assertNotIn(GUARD_CLOSE, escaped)
        self.assertIn("<<<_UNTRUSTED_DATA>>>", escaped)
        self.assertIn("<<<_END_UNTRUSTED_DATA>>>", escaped)

    def test_wrap_untrusted_web_evidence(self):
        query = "quando sara la prossima eclissi"
        content = "Eclissi solare totale il 12 agosto 2026."
        sources = [{"title": "NASA", "url": "https://nasa.gov"}]

        wrapped = wrap_untrusted_web_evidence(query, content, sources)
        self.assertIn(GUARD_OPEN, wrapped)
        self.assertIn(GUARD_CLOSE, wrapped)
        self.assertIn("UNTRUSTED SOURCE DATA", wrapped)
        self.assertIn("NASA", wrapped)
        self.assertIn("https://nasa.gov", wrapped)
        self.assertIn("12 agosto 2026", wrapped)

    def test_deduplicate_by_url(self):
        items = [
            {"url": "https://example.com/a", "title": "A1"},
            {"url": "https://example.com/b/", "title": "B1"},
            {"url": "https://example.com/a/", "title": "A2"},
        ]
        deduped = deduplicate_by_url(items)
        self.assertEqual(len(deduped), 2)
        urls = [d["url"].rstrip("/") for d in deduped]
        self.assertEqual(urls, ["https://example.com/a", "https://example.com/b"])

    @patch("registry.web_search_service.search_ddgs_library")
    @patch("registry.web_search_service.search_searxng_api")
    @patch("registry.web_search_service.fetch_webpage_content")
    def test_execute_search_pipeline(self, mock_fetch, mock_searxng, mock_ddgs):
        mock_searxng.return_value = [
            {"title": "Total Solar Eclipse 2026", "url": "https://example.com/eclipse", "snippet": "Solar eclipse 2026 details"},
            {"title": "Lunar Eclipse 2026", "url": "https://example.com/lunar", "snippet": "Lunar eclipse 2026 details"},
            {"title": "Solar Eclipse Schedule 2026", "url": "https://example.com/schedule", "snippet": "Schedule 2026 details"},
        ]
        mock_fetch.return_value = {
            "success": True,
            "title": "Eclipse 2026",
            "url": "https://example.com/eclipse",
            "content": "A total solar eclipse will take place on 12 August 2026.",
        }
        mock_ddgs.return_value = []

        events = []
        def event_cb(ev, data):
            events.append((ev, data))

        res = execute_search("solar eclipse 2026", count=5, event_callback=event_cb)
        self.assertTrue(res["success"])
        self.assertEqual(res["query"], "solar eclipse 2026")
        self.assertEqual(len(res["sources"]), 3)
        self.assertIn("Eclipse 2026", res["summary_text"])

class TestWebPrefetchGraph(unittest.TestCase):
    @patch("registry.web_search_service.execute_search")
    @patch("graph._call_llm")
    def test_chat_mode_with_web_prefetch(self, mock_llm, mock_search):
        from api import run_agent_flow

        mock_search.return_value = {
            "query": "prossima eclissi 2026",
            "success": True,
            "provider_used": "SearXNG",
            "sources": [{"title": "Eclipse 2026", "url": "https://example.com/eclipse", "snippet": "August 12 2026"}],
            "summary_text": "Solar eclipse on August 12 2026.",
            "latency_ms": 150,
        }
        mock_llm.return_value = {
            "content": "La prossima eclissi solare totale avverrà il 12 agosto 2026.",
            "reasoning_content": "Analizzo le fonti recuperate...",
        }

        resp = run_agent_flow(
            task="quando sara la prossima eclissi 2026",
            thread_id="test_thread_chat_web",
            force_mode="chat",
            web_search=True,
            incognito=True,
        )

        mock_search.assert_called_once()
        mock_llm.assert_called_once()

        # Verify prompt contained untrusted delimiter and sources
        call_args = mock_llm.call_args
        prompt_passed = call_args[0][0]
        system_prompt_passed = call_args[1].get("system_prompt", "")
        self.assertIn("UNTRUSTED SOURCE DATA", prompt_passed)
        self.assertIn("Eclipse 2026", prompt_passed)
        from registry.search_security import UNTRUSTED_CONTEXT_POLICY
        self.assertIn(UNTRUSTED_CONTEXT_POLICY, system_prompt_passed)

        # Verify response attributes
        self.assertEqual(resp.mode, "chat")
        self.assertIn("12 agosto 2026", resp.response)
        self.assertIsNotNone(resp.web_prefetch)
        self.assertEqual(resp.web_prefetch["provider_used"], "SearXNG")
        self.assertIsNone(resp.tool_used)

    @patch("registry.web_search_service.execute_search")
    def test_web_prefetch_disabled_does_not_call_search(self, mock_search):
        from api import run_agent_flow

        with patch("graph._call_llm") as mock_llm:
            mock_llm.return_value = {"content": "Ciao! Come posso aiutarti?"}
            resp = run_agent_flow(
                task="ciao come stai",
                thread_id="test_thread_no_web",
                force_mode="chat",
                web_search=False,
                incognito=True,
            )
            mock_search.assert_not_called()
            self.assertIsNone(resp.web_prefetch)


if __name__ == "__main__":
    unittest.main()

