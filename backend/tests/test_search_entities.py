"""Una ricerca per prodotto, e il tentativo con il solo nome (ISS-38). Provider finti, nessuna rete."""

import re
from unittest.mock import patch

import pytest

from app.registry.search_entities import (
    MAX_SEARCHES,
    bare_name,
    entity_queries,
    interleave,
    name_in_results,
)
from app.registry.search_providers import ProviderResults
from app.registry.web_search_service import SearchOutcome, execute_search

QUESTION = "Confronta i display di Nimbus X2 e X3, Cedar GO3 (scritto «Cedr»), Rokk, Lumen Halo e Harbor-Ban Meta"


def _page(title, url, snippet=""):
    return {"title": title, "url": url, "snippet": snippet or title}


def _names(query):
    return [plan.name for plan in entity_queries(query)]


class TestSplit:
    def test_one_query_per_named_product(self):
        plans = entity_queries(QUESTION)
        assert [plan.name for plan in plans] == [
            "Nimbus X2", "Nimbus X3", "Cedar GO3", "Rokk", "Lumen Halo", "Harbor-Ban Meta",
        ]
        assert plans[0].query == "Nimbus X2 display"
        assert plans[4].query == "Lumen Halo display"

    def test_the_misspelling_hint_is_not_a_product(self):
        assert "Cedr" not in " ".join(plan.query for plan in entity_queries(QUESTION))

    def test_a_bare_code_takes_the_brand_before_it(self):
        assert _names("display di Nimbus X2, X3") == ["Nimbus X2", "Nimbus X3"]
        assert _names("Python 3.13 vs 3.12 novità") == ["Python 3.13", "Python 3.12"]

    def test_two_products_with_a_conjunction_or_vs(self):
        assert _names("differenza tra Docker e Podman") == ["Docker", "Podman"]
        assert _names("Python vs Rust performance") == ["Python", "Rust"]

    @pytest.mark.parametrize("question", [
        "Come installare Docker su Ubuntu 24.04",
        "prezzo iPhone 16 Pro Max",
        "Ciao Marco, che tempo fa a Torino",
        "Chi ha scritto Il nome della rosa e quando",
        "Perché il cielo è blu e il tramonto rosso?",
        "Cosa è cambiato in Python 3.13 rispetto a 3.12",
        "tutorial su 3,5 pollici e 4,2 pollici",
        "quando sara la prossima eclissi e dove si vede",
    ])
    def test_a_single_subject_is_not_split(self, question):
        assert entity_queries(question) == []

    def test_the_number_of_products_is_capped(self):
        many = ", ".join(f"Prod{chr(65 + i)} A{i}" for i in range(12))
        assert len(entity_queries(many)) == MAX_SEARCHES

    def test_every_query_uses_only_words_of_the_question(self):
        words = set(re.findall(r"\w+", QUESTION.lower()))
        for plan in entity_queries(QUESTION):
            assert set(re.findall(r"\w+", plan.query.lower())) <= words


def test_bare_name_of_a_single_subject():
    assert bare_name("Lumen Halo display specifications") == "Lumen Halo"
    assert bare_name("prezzo iPhone 16 Pro Max") == "iPhone 16 Pro Max"
    assert bare_name("Lumen Halo") is None
    assert bare_name("Come installare Docker su Ubuntu 24.04") is None


def test_name_in_results_needs_every_word_in_one_source():
    pages = [_page("Lumen Labs", "https://example.com/a"), _page("Halo", "https://example.com/b")]
    assert not name_in_results("Lumen Halo", pages)
    assert name_in_results("Lumen Lab", pages)
    assert name_in_results("Lumen Halo", [_page("x", "https://docs.example.com/lumen-halo/hardware")])


def test_interleave_takes_one_from_each_group_in_turn():
    groups = [
        [_page("a1", "https://e.com/a1"), _page("a2", "https://e.com/a2")],
        [_page("b1", "https://e.com/b1")],
        [_page("a1 again", "https://e.com/a1/")],
    ]
    assert [item["title"] for item in interleave(groups)] == ["a1", "b1", "a2"]


@pytest.fixture
def pipeline():
    with patch("app.registry.web_search_service.is_safe_url", return_value=True), \
            patch("app.registry.web_search_service.fetch_webpage_content", return_value={"success": False}), \
            patch("app.registry.web_search_service.search_with_fallback") as fallback:
        yield fallback


def _engine(answers, calls, failures=()):
    def fake(query, count=8, time_filter=None, event_callback=None):
        calls.append(query)
        found = answers(query)
        return SearchOutcome(found, "SearXNG (en)" if found else "None", failures)

    return fake


class TestExecuteSearch:
    def test_each_product_gets_its_own_search_and_a_miss_is_retried_by_name_alone(self, pipeline):
        calls = []

        def answers(query):
            if query == "Lumen Halo":
                return [_page("Lumen Halo hardware", "https://docs.example.com/halo")]
            if query.startswith("Lumen Halo"):
                return [_page("Catalogo altro", "https://example.com/catalog")]
            return [_page(query, f"https://example.com/{len(calls)}")]

        pipeline.side_effect = _engine(answers, calls)
        res = execute_search(QUESTION)

        assert QUESTION not in calls
        assert calls == [
            "Nimbus X2 display", "Nimbus X3 display", "Cedar GO3 display", "Rokk display",
            "Lumen Halo display", "Harbor-Ban Meta display", "Lumen Halo",
        ]
        assert res["success"] is True
        assert any("docs.example.com/halo" in source["url"] for source in res["sources"])
        assert "Ricerche eseguite" in res["summary_text"]
        assert "Nessuna fonte trovata" not in res["summary_text"]

    def test_a_name_still_missing_after_the_retry_is_said(self, pipeline):
        calls = []

        def answers(query):
            if "Lumen" in query:
                return []
            return [_page(query, f"https://example.com/{len(calls)}")]

        pipeline.side_effect = _engine(answers, calls, failures={"suspended"})
        res = execute_search(QUESTION)

        assert calls.count("Lumen Halo") == 1
        text = res["summary_text"]
        assert "Nessuna fonte trovata per: Lumen Halo" in text
        assert "Ricerca degradata" in text

    def test_the_ranking_does_not_put_the_first_brand_on_top(self, pipeline):
        calls = []
        pipeline.side_effect = _engine(
            lambda q: [_page(f"{q} {n}", f"https://example.com/{q.replace(' ', '-')}-{n}") for n in range(3)],
            calls,
        )
        res = execute_search("Confronta Nimbus X2, Cedar GO3, Lumen Halo")
        assert [source["title"].rsplit(" ", 1)[0] for source in res["sources"][:3]] == [
            "Nimbus X2", "Cedar GO3", "Lumen Halo",
        ]

    def test_no_turn_makes_more_searches_than_the_cap(self, pipeline):
        calls = []
        many = ", ".join(f"Prod{chr(65 + i)} A{i}" for i in range(12))
        pipeline.side_effect = _engine(lambda q: [], calls)
        execute_search(f"Confronta {many} display")
        assert len(calls) <= MAX_SEARCHES

    def test_a_single_subject_with_no_match_is_retried_by_name_alone(self, pipeline):
        calls = []

        def answers(query):
            if query == "Lumen Halo":
                return [_page("Lumen Halo", "https://docs.example.com/halo")]
            return [_page("Catalogo altro", "https://example.com/catalog")]

        pipeline.side_effect = _engine(answers, calls)
        res = execute_search("Lumen Halo display specifications")

        assert calls == ["Lumen Halo display specifications", "Lumen Halo"]
        assert {source["url"] for source in res["sources"]} == {
            "https://example.com/catalog", "https://docs.example.com/halo",
        }

    def test_a_single_subject_that_matches_is_searched_once(self, pipeline):
        calls = []
        pipeline.side_effect = _engine(
            lambda q: [_page("Lumen Halo display", "https://docs.example.com/halo")], calls)
        execute_search("Lumen Halo display specifications")
        assert len(calls) == 1

    def test_a_plain_question_is_searched_once_even_with_no_results(self, pipeline):
        calls = []
        pipeline.side_effect = _engine(lambda q: [], calls)
        res = execute_search("quando sara la prossima eclissi e dove si vede")
        assert len(calls) == 1
        assert res["success"] is False

    def test_every_search_goes_through_the_providers_chain(self):
        # Nessun mock di search_with_fallback: le query dei prodotti arrivano ai provider veri, che qui sono finti.
        seen = []

        def searx(query, count=8, time_filter=None, language=None):
            seen.append(query)
            return ProviderResults([_page(query, f"https://example.com/{len(seen)}")])

        with patch("app.registry.web_search_service.search_searxng_api", side_effect=searx), \
                patch("app.registry.web_search_service.is_safe_url", return_value=True), \
                patch("app.registry.web_search_service.fetch_webpage_content", return_value={"success": False}):
            execute_search("Confronta Nimbus X2, Cedar GO3")
        assert set(seen) == {"Nimbus X2", "Cedar GO3"}
