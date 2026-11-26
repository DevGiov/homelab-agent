"""Ricerca degradata: il testo per il modello lo dice. Provider finti, nessuna rete."""

import unittest
from unittest.mock import patch

from app.registry.search_providers import (
    FAILURE_CAPTCHA,
    FAILURE_ENGINE,
    FAILURE_SUSPENDED,
    ProviderResults,
    classify_engine_failure,
    search_duckduckgo_html,
    search_searxng_api,
)
from app.registry.web_search import WebSearchRegistry
from app.registry.web_search_service import (
    _MAX_CONTENT_CHARS,
    _MAX_FETCH_PAGES,
    _MAX_TOTAL_CONTENT_CHARS,
    SearchOutcome,
    execute_search,
)


def _page(title: str, url: str, snippet: str) -> dict:
    return {"title": title, "url": url, "snippet": snippet}


class TestFailureModes(unittest.TestCase):
    def test_unresponsive_engines_map_to_generic_modes(self):
        self.assertEqual(classify_engine_failure(["northwind", "HTTP error"]), FAILURE_ENGINE)
        self.assertEqual(classify_engine_failure(["cedar", "Access denied"]), FAILURE_ENGINE)
        self.assertEqual(classify_engine_failure(["harbor", "Suspended: too many requests"]), FAILURE_SUSPENDED)
        self.assertEqual(classify_engine_failure(["maple", "CAPTCHA"]), FAILURE_CAPTCHA)
        self.assertEqual(classify_engine_failure(("maple", "CAPTCHA", False)), FAILURE_CAPTCHA)
        self.assertEqual(
            classify_engine_failure({"engine": "harbor", "error_type": "suspended", "suspended": True}),
            FAILURE_SUSPENDED,
        )

    def test_html_captcha_is_a_failure_mode(self):
        class Response:
            status_code = 200
            text = "<html>anomaly-modal Select all squares</html>"

        with patch("app.registry.search_providers.requests.get", return_value=Response()):
            found = search_duckduckgo_html("nimbus halo")
        self.assertEqual(list(found), [])
        self.assertIn(FAILURE_CAPTCHA, found.failures)

    def test_searxng_keeps_hits_and_records_modes_without_engine_names(self):
        class Response:
            status_code = 200

            def json(self):
                return {
                    "results": [{
                        "title": "Nimbus X2",
                        "url": "https://example.com/nimbus",
                        "content": "Nimbus X2 display",
                    }],
                    "unresponsive_engines": [
                        ["northwind", "HTTP error"],
                        ["harbor", "Suspended: too many requests"],
                        ["maple", "CAPTCHA"],
                        ["cedar", "Access denied"],
                    ],
                }

        with patch("app.registry.search_providers.get_searxng_url", return_value="http://search.example"), \
                patch("app.registry.search_providers.requests.get", return_value=Response()):
            found = search_searxng_api("Nimbus X2")
        self.assertEqual(found[0]["title"], "Nimbus X2")
        self.assertEqual(found.failures, {FAILURE_ENGINE, FAILURE_SUSPENDED, FAILURE_CAPTCHA})
        self.assertNotIn("northwind", str(found.failures))


class TestExecuteSearchHardening(unittest.TestCase):
    def test_tool_schema_stays_a_single_query(self):
        tool = next(item for item in WebSearchRegistry().get_tools() if item["name"] == "web_search")
        self.assertEqual(tool["parameters"]["required"], ["query"])
        self.assertEqual(set(tool["parameters"]["properties"]), {"query"})

    def test_budgets_stay_put(self):
        self.assertEqual(_MAX_FETCH_PAGES, 3)
        self.assertEqual(_MAX_CONTENT_CHARS, 2000)
        self.assertEqual(_MAX_TOTAL_CONTENT_CHARS, 8000)

    @patch("app.registry.web_search_service.is_safe_url", return_value=True)
    @patch("app.registry.web_search_service.fetch_webpage_content", return_value={"success": False})
    @patch("app.registry.web_search_service.search_with_fallback")
    def test_degraded_empty_is_not_a_miss_on_the_product(self, mock_fallback, _fetch, _safe):
        mock_fallback.return_value = SearchOutcome([], "None", {FAILURE_ENGINE, FAILURE_SUSPENDED, FAILURE_CAPTCHA})

        res = execute_search("Nimbus Halo display")

        self.assertFalse(res["success"])
        self.assertTrue(res["degraded"])
        self.assertEqual(res["sources"], [])
        text = res["summary_text"]
        self.assertIn("Ricerca degradata", text)
        self.assertIn("errore motore", text)
        self.assertIn("sospeso", text)
        self.assertIn("captcha", text)
        self.assertIn("non esista", text)
        self.assertNotIn("Nessun risultato trovato", text)
        self.assertIsInstance(res["query"], str)

    @patch("app.registry.web_search_service.is_safe_url", return_value=True)
    @patch("app.registry.web_search_service.fetch_webpage_content", return_value={"success": False})
    @patch("app.registry.web_search_service.search_with_fallback")
    def test_healthy_empty_still_says_nothing_found(self, mock_fallback, _fetch, _safe):
        mock_fallback.return_value = SearchOutcome([], "SearXNG (en)")

        res = execute_search("Nimbus Halo")

        self.assertFalse(res["success"])
        self.assertFalse(res["degraded"])
        self.assertIn("Nessun risultato trovato", res["summary_text"])
        self.assertNotIn("Ricerca degradata", res["summary_text"])
        self.assertEqual(mock_fallback.call_count, 1)

    @patch("app.registry.web_search_service.is_safe_url", return_value=True)
    @patch("app.registry.web_search_service.fetch_webpage_content", return_value={"success": False})
    @patch("app.registry.web_search_service.search_with_fallback")
    def test_partial_results_warn_that_a_missing_product_may_exist(self, mock_fallback, _fetch, _safe):
        mock_fallback.return_value = SearchOutcome(
            [_page("Nimbus X2", "https://example.com/nimbus", "Nimbus X2 scheda")],
            "SearXNG (en)",
            {FAILURE_SUSPENDED, FAILURE_CAPTCHA},
        )

        res = execute_search("Nimbus X2 specs")

        self.assertTrue(res["success"])
        self.assertTrue(res["degraded"])
        text = res["summary_text"]
        self.assertIn("Ricerca degradata", text)
        self.assertIn("sospeso", text)
        self.assertIn("captcha", text)
        self.assertIn("può esistere", text)
        self.assertIn("Nimbus X2", text)
        self.assertNotIn("errore motore", text)

    @patch("app.registry.web_search_service.fetch_webpage_content", return_value={"success": False})
    @patch("app.registry.web_search_service.is_safe_url", return_value=True)
    @patch("app.registry.web_search_service.search_duckduckgo_api", return_value=ProviderResults())
    @patch("app.registry.web_search_service.search_duckduckgo_html", return_value=ProviderResults([], {FAILURE_CAPTCHA}))
    @patch("app.registry.web_search_service.search_ddgs_library", return_value=ProviderResults())
    @patch("app.registry.web_search_service.search_searxng_api")
    @patch("app.registry.web_search_service.time.sleep")
    def test_chain_surfaces_engine_error_and_captcha(self, _sleep, mock_searx, _ddgs, _html, _api, _safe, _fetch):
        mock_searx.return_value = ProviderResults([], {FAILURE_ENGINE})

        res = execute_search("Nimbus Halo")

        self.assertFalse(res["success"])
        self.assertIn("errore motore", res["summary_text"])
        self.assertIn("captcha", res["summary_text"])
        self.assertNotIn("Nessun risultato trovato", res["summary_text"])
        self.assertNotIn("northwind", res["summary_text"])

    @patch("app.registry.web_search_service.fetch_webpage_content", return_value={"success": False})
    @patch("app.registry.web_search_service.is_safe_url", return_value=True)
    @patch("app.registry.web_search_service.search_searxng_api")
    def test_hits_from_one_engine_still_say_the_others_failed(self, mock_searx, _safe, _fetch):
        pages = [
            _page(f"Nimbus X2 pagina {i}", f"https://example.com/n{i}", "Nimbus X2 display")
            for i in range(4)
        ]
        mock_searx.return_value = ProviderResults(pages, {FAILURE_SUSPENDED, FAILURE_CAPTCHA})

        res = execute_search("Nimbus X2")

        self.assertTrue(res["success"])
        self.assertIn("Ricerca degradata", res["summary_text"])
        self.assertIn("sospeso", res["summary_text"])
        self.assertIn("captcha", res["summary_text"])
        self.assertIn("può esistere", res["summary_text"])
        self.assertGreaterEqual(len(res["sources"]), 3)
        mock_searx.assert_called()

    @patch("app.registry.web_search_service.fetch_webpage_content", return_value={"success": False})
    @patch("app.registry.web_search_service.is_safe_url", return_value=True)
    @patch("app.registry.web_search_service.search_with_fallback")
    def test_snippet_and_page_caps_are_unchanged(self, mock_fallback, _safe, mock_fetch):
        long_snippet = "Nimbus " + ("x" * 400)
        mock_fallback.return_value = SearchOutcome(
            [_page(f"Nimbus {i}", f"https://example.com/p{i}", long_snippet) for i in range(5)],
            "SearXNG (en)",
        )

        res = execute_search("Nimbus")

        self.assertEqual(len(res["sources"][0]["snippet"]), 250)
        self.assertEqual(mock_fetch.call_count, _MAX_FETCH_PAGES)


if __name__ == "__main__":
    unittest.main()
