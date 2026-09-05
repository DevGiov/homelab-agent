"""Web search orchestration service.

Handles:
- Provider fallback chain (SearXNG en -> SearXNG it -> DDGS -> DDG HTML -> DDG API)
- Deduplication, ranking, and concurrent safe page fetching
- Formatting structured results for both backend prefetch and agent tool execution
- Event notifications for real-time observability
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from registry.search_content import (
    extract_key_points,
    fetch_webpage_content,
    get_tldr,
)
from registry.search_providers import (
    search_ddgs_library,
    search_duckduckgo_api,
    search_duckduckgo_html,
    search_searxng_api,
)
from registry.search_ranking import (
    filter_irrelevant_results,
    rank_search_results,
)
from registry.search_security import is_safe_url

logger = logging.getLogger("web_search_service")

_MAX_FETCH_PAGES = 4
_MAX_CONTENT_CHARS = 3000
_MAX_WORKERS = 4
_MIN_SATISFACTORY_RESULTS = 3

_PRIMARY_LANG = os.environ.get("SEARCH_PRIMARY_LANG", "en")
_FALLBACK_LANG = os.environ.get("SEARCH_FALLBACK_LANG", "it")


def deduplicate_by_url(results: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    unique = []
    for r in results:
        u = r.get("url", "").rstrip("/")
        if u and u not in seen:
            seen.add(u)
            unique.append(r)
    return unique


def search_with_fallback(
    query: str,
    count: int = 8,
    time_filter: Optional[str] = None,
    event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> tuple[List[Dict[str, str]], str]:
    """Execute multi-tier search with fallback and provider tracking.

    Returns:
        (results, provider_name)
    """
    accumulated: List[Dict[str, str]] = []
    provider_used = "None"

    # 1. Primary SearXNG
    if event_callback:
        event_callback("web_prefetch.provider_attempt", {"provider": f"SearXNG ({_PRIMARY_LANG})", "query": query})
    logger.info(f"Trying SearXNG ({_PRIMARY_LANG}) for: {query}")
    results = search_searxng_api(query, count=count, time_filter=time_filter, language=_PRIMARY_LANG)
    if results:
        relevant = filter_irrelevant_results(query, results)
        if len(relevant) >= _MIN_SATISFACTORY_RESULTS:
            return relevant, f"SearXNG ({_PRIMARY_LANG})"
        accumulated.extend(relevant)
        provider_used = f"SearXNG ({_PRIMARY_LANG})"

    # 2. Retry SearXNG fallback language
    if _FALLBACK_LANG and _FALLBACK_LANG != _PRIMARY_LANG:
        time.sleep(0.2)
        if event_callback:
            event_callback("web_prefetch.provider_attempt", {"provider": f"SearXNG ({_FALLBACK_LANG})", "query": query})
        logger.info(f"Trying SearXNG ({_FALLBACK_LANG}) for: {query}")
        results = search_searxng_api(query, count=count, time_filter=time_filter, language=_FALLBACK_LANG)
        if results:
            relevant = filter_irrelevant_results(query, results)
            accumulated.extend(relevant)
            accumulated = deduplicate_by_url(accumulated)
            if len(accumulated) >= _MIN_SATISFACTORY_RESULTS:
                return accumulated, f"SearXNG ({_FALLBACK_LANG})"
            provider_used = f"SearXNG ({_PRIMARY_LANG}+{_FALLBACK_LANG})"

    # 3. Fallback DDGS library
    if event_callback:
        event_callback("web_prefetch.provider_attempt", {"provider": "DuckDuckGo (DDGS)", "query": query})
    logger.info(f"Trying DDGS library for: {query}")
    ddgs_results = search_ddgs_library(query, count=count, time_filter=time_filter)
    if ddgs_results:
        relevant = filter_irrelevant_results(query, ddgs_results)
        chosen = relevant if relevant else ddgs_results
        accumulated.extend(chosen)
        accumulated = deduplicate_by_url(accumulated)
        if accumulated:
            return accumulated, "DuckDuckGo (DDGS)"

    # 4. Fallback DDG HTML scraping
    if not accumulated:
        time.sleep(0.3)
        if event_callback:
            event_callback("web_prefetch.provider_attempt", {"provider": "DuckDuckGo (HTML)", "query": query})
        logger.info("Trying DDG HTML fallback")
        html_results = search_duckduckgo_html(query, count=count)
        if html_results:
            relevant = filter_irrelevant_results(query, html_results)
            accumulated.extend(relevant if relevant else html_results)
            provider_used = "DuckDuckGo (HTML)"

    # 5. Last resort DDG Instant Answer API
    if not accumulated:
        if event_callback:
            event_callback("web_prefetch.provider_attempt", {"provider": "DuckDuckGo (Instant API)", "query": query})
        logger.info("Trying DDG Instant Answer API")
        api_results = search_duckduckgo_api(query)
        if api_results:
            accumulated.extend(api_results)
            provider_used = "DuckDuckGo (Instant API)"

    return deduplicate_by_url(accumulated), provider_used


def execute_search(
    query: str,
    count: int = 8,
    max_fetch_pages: int = _MAX_FETCH_PAGES,
    event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Execute full search pipeline: query -> fallback -> rank -> safe fetch -> format.

    Guaranteed to return a structured dictionary, never raising uncaught exceptions.
    """
    clean_query = query.strip()
    if not clean_query:
        return {
            "query": "",
            "success": False,
            "provider_used": "None",
            "sources": [],
            "summary_text": "Query vuota.",
            "error": "Query mancante o vuota.",
        }

    start_time = time.time()
    try:
        raw_results, provider = search_with_fallback(clean_query, count=count, event_callback=event_callback)
    except Exception as e:
        logger.warning(f"Errore provider search per '{clean_query}': {e}")
        return {
            "query": clean_query,
            "success": False,
            "provider_used": "Error",
            "sources": [],
            "summary_text": f"Ricerca non riuscita: {e}",
            "error": str(e),
        }

    if not raw_results:
        return {
            "query": clean_query,
            "success": False,
            "provider_used": provider,
            "sources": [],
            "summary_text": f"Nessun risultato trovato per '{clean_query}'.",
            "error": None,
        }

    # Rank results
    try:
        ranked_results = rank_search_results(clean_query, raw_results)
    except Exception as e:
        logger.warning(f"Errore ranking per '{clean_query}': {e}")
        ranked_results = raw_results

    # Build sources list
    sources = [
        {"url": r["url"], "title": r.get("title", ""), "snippet": r.get("snippet", "")}
        for r in ranked_results
        if r.get("url") and is_safe_url(r["url"])
    ]

    # Concurrent safe page fetching
    urls_to_fetch = [s["url"] for s in sources[:max_fetch_pages]]
    url_to_index = {s["url"]: i for i, s in enumerate(sources, 1)}

    fetched_content: List[Dict[str, Any]] = []
    if urls_to_fetch:
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
            future_to_url = {
                executor.submit(fetch_webpage_content, url): url
                for url in urls_to_fetch
            }
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    res = future.result()
                    if res.get("success") and res.get("content") and len(res["content"]) >= 50:
                        res["source_index"] = url_to_index.get(url, 0)
                        fetched_content.append(res)
                except Exception as e:
                    logger.warning(f"Errore fetching pagina {url}: {e}")

        fetched_content.sort(key=lambda c: c.get("source_index", 999))
        logger.info(f"Pagine scaricate con successo: {len(fetched_content)}/{len(urls_to_fetch)}")

    # Format text output for LLM context
    output_parts = [
        "=" * 60,
        "WEB SEARCH RESULTS AND FETCHED CONTENT",
        f"Query: {clean_query}",
        f"Provider: {provider} | Risultati trovati: {len(ranked_results)} | Pagine estratte: {len(fetched_content)}",
        "=" * 60,
        "\nRIASSUNTO RISULTATI DI RICERCA:",
        "-" * 40,
    ]

    for i, r in enumerate(sources[:8], 1):
        output_parts.append(f"\n[{i}] {r['title']}")
        output_parts.append(f"    URL: {r['url']}")
        if r.get("snippet"):
            output_parts.append(f"    Snippet: {r['snippet'][:250]}")

    if fetched_content:
        output_parts.append("\n" + "=" * 60)
        output_parts.append("CONTENUTO DETTAGLIATO DELLE PAGINE:")
        output_parts.append("-" * 40)

        for content in fetched_content:
            idx = content.get("source_index", "?")
            output_parts.append(f"\n[PAGINA {idx}] {content.get('title', '')}")
            output_parts.append(f"URL: {content.get('url', '')}")
            output_parts.append("-" * 30)

            tldr = get_tldr(content.get("content", ""))
            if tldr and len(tldr) > 30:
                output_parts.append(f"TL;DR: {tldr[:500]}\n")

            if content.get("tables"):
                output_parts.append("Tabelle rilevate:")
                for table in content["tables"][:2]:
                    for row in table[:6]:
                        output_parts.append(" | ".join(row))
                output_parts.append("")

            text = content.get("content", "")[:_MAX_CONTENT_CHARS]
            output_parts.append("Testo principale:")
            output_parts.append(text)

            key_pts = extract_key_points(content.get("content", ""))
            if key_pts:
                output_parts.append("\nPunti salienti:")
                for pt in key_pts[:4]:
                    output_parts.append(f"- {pt}")
            output_parts.append("")

    output_parts.append("=" * 60)
    output_parts.append("FINE RISULTATI WEB SEARCH")
    output_parts.append("=" * 60)

    summary_text = "\n".join(output_parts)
    elapsed_ms = int((time.time() - start_time) * 1000)
    logger.info(f"Search pipeline completata per '{clean_query}' in {elapsed_ms}ms (sources={len(sources)})")

    return {
        "query": clean_query,
        "success": True,
        "provider_used": provider,
        "sources": sources,
        "summary_text": summary_text,
        "ranked_results": ranked_results,
        "fetched_content": fetched_content,
        "latency_ms": elapsed_ms,
        "error": None,
    }
