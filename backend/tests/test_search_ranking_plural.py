"""Il filtro di rilevanza e il ranking tollerano il plurale semplice: «lab» e «labs»."""

from app.registry.search_ranking import (
    compute_relevance,
    filter_irrelevant_results,
    is_result_relevant,
    rank_search_results,
)


def test_singular_query_matches_plural_text_and_back():
    assert is_result_relevant("Nimbus Lab display", "Nimbus Labs Halo", "")
    assert is_result_relevant("Nimbus Labs display", "Nimbus Lab Halo", "")


def test_filter_keeps_the_plural_page():
    pages = [
        {"title": "Nimbus Labs Halo", "snippet": "hardware", "url": "https://example.com/a"},
        {"title": "Cedar Harbor", "snippet": "altro", "url": "https://example.com/b"},
    ]
    kept = filter_irrelevant_results("Nimbus Lab Halo", pages)
    assert [page["url"] for page in kept] == ["https://example.com/a"]


def test_ranking_counts_the_plural_title():
    pages = [
        {"title": "Cedar Harbor", "snippet": "", "url": "https://example.com/b"},
        {"title": "Nimbus Labs", "snippet": "", "url": "https://example.com/a"},
    ]
    assert rank_search_results("Nimbus Lab", pages)[0]["url"] == "https://example.com/a"


def test_relevance_score_sees_the_plural():
    assert compute_relevance("Nimbus Lab", "Nimbus Labs", "") == 1.0
    assert compute_relevance("Nimbus Labs", "Nimbus Lab", "") == 1.0


def test_no_stemming_beyond_a_plain_s():
    assert not is_result_relevant("Lab", "Labrador", "")
    assert not is_result_relevant("X2", "X2s", "")
