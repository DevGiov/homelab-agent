"""Web search orchestration service.

Handles:
- Provider fallback chain (SearXNG en -> SearXNG it -> DDGS -> DDG HTML -> DDG API)
- Deduplication, ranking, and concurrent safe page fetching
- Formatting structured results for both backend prefetch and agent tool execution
- Event notifications for real-time observability
"""

from __future__ import annotations

import contextvars
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from app.core.config import settings
from app.registry.search_content import (
    extract_key_points,
    fetch_webpage_content,
    get_tldr,
)
from app.registry.search_providers import (
    FAILURE_CAPTCHA,
    FAILURE_ENGINE,
    FAILURE_SUSPENDED,
    search_ddgs_library,
    search_duckduckgo_api,
    search_duckduckgo_html,
    search_searxng_api,
)
from app.registry.search_ranking import (
    filter_irrelevant_results,
    normalize_search_query,
    rank_search_results,
)
from app.registry.search_security import is_safe_url, sanitize_source_url

logger = logging.getLogger("web_search_service")

_MAX_FETCH_PAGES = 3
# Eventi di avanzamento per chi chiama la ricerca attraverso il ToolRegistryManager (il prefetch del grafo), dove una
# funzione non può passare negli argomenti del tool
_event_sink: contextvars.ContextVar[Optional[Callable[[str, Dict[str, Any]], None]]] = contextvars.ContextVar(
    "search_event_sink", default=None)


def run_with_event_sink(callback: Callable[[str, Dict[str, Any]], None], fn, *args, **kwargs):
    token = _event_sink.set(callback)
    try:
        return fn(*args, **kwargs)
    finally:
        _event_sink.reset(token)

_MAX_CONTENT_CHARS = 2000
_MAX_TOTAL_CONTENT_CHARS = 8000
_MAX_WORKERS = 4
_MIN_SATISFACTORY_RESULTS = 3



def deduplicate_by_url(results: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    unique = []
    for r in results:
        u = r.get("url", "").rstrip("/")
        if u and u not in seen:
            seen.add(u)
            unique.append(r)
    return unique


class SearchOutcome(tuple):
    """(results, provider) più i modi di fallimento. Si spacchetta ancora come coppia."""

    failures: frozenset

    def __new__(cls, results, provider: str, failures=()):
        self = super().__new__(cls, (list(results), provider))
        self.failures = frozenset(failures or ())
        return self


def _modes_of(results) -> set:
    return set(getattr(results, "failures", ()) or ())


_MODE_ORDER = (FAILURE_ENGINE, FAILURE_SUSPENDED, FAILURE_CAPTCHA)
_MODE_PHRASE = {
    FAILURE_ENGINE: "errore motore",
    FAILURE_SUSPENDED: "sospeso",
    FAILURE_CAPTCHA: "captcha",
}


def degradation_notice(modes: set, query: str, *, empty: bool) -> str:
    """Testo per il modello quando la ricerca è degradata, con i modi di fallimento in termini generici.

    Un elenco vuoto o parziale, senza questo avviso, si legge come «nessuna pagina su questo prodotto».
    """
    labels = [_MODE_PHRASE[mode] for mode in _MODE_ORDER if mode in modes]
    if not labels:
        return ""
    listed = ", ".join(labels)
    if empty:
        return (
            f"Ricerca degradata ({listed}): nessun risultato per '{query}', ma alcuni motori non hanno risposto. "
            "L'elenco vuoto non vuol dire che il prodotto non esista sul web: non concluderlo."
        )
    return (
        f"Ricerca degradata ({listed}): alcuni motori non hanno risposto. "
        "Un prodotto assente da questi risultati può esistere comunque: non concludere che non esista."
    )


def search_with_fallback(
    query: str,
    count: int = 8,
    time_filter: Optional[str] = None,
    event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> SearchOutcome:
    """Execute multi-tier search with fallback and provider tracking.

    Returns:
        (results, provider_name), con `.failures` (errore motore, sospeso, captcha).
    """
    accumulated: List[Dict[str, str]] = []
    provider_used = "None"
    failures: set = set()
    primary_lang, fallback_lang = settings.search_primary_lang, settings.search_fallback_lang

    def take(results) -> List[Dict[str, str]]:
        failures.update(_modes_of(results))
        return list(results or [])

    # 1. Primary SearXNG
    if event_callback:
        event_callback("web_prefetch.provider_attempt", {"provider": f"SearXNG ({primary_lang})", "query": query})
    logger.info(f"Trying SearXNG ({primary_lang}) for: {query}")
    results = take(search_searxng_api(query, count=count, time_filter=time_filter, language=primary_lang))
    if results:
        relevant = filter_irrelevant_results(query, results)
        if len(relevant) >= _MIN_SATISFACTORY_RESULTS:
            return SearchOutcome(relevant, f"SearXNG ({primary_lang})", failures)
        accumulated.extend(relevant)
        provider_used = f"SearXNG ({primary_lang})"

    # 1b. If query had restrictive quotes and gave < MIN results, retry unquoted
    unquoted_q = " ".join(query.replace('"', ' ').replace("'", ' ').split())
    if unquoted_q != query and len(accumulated) < _MIN_SATISFACTORY_RESULTS:
        logger.info(f"Retrying SearXNG ({primary_lang}) without restrictive quotes: {unquoted_q}")
        unquoted_results = take(search_searxng_api(unquoted_q, count=count, time_filter=time_filter, language=primary_lang))
        if unquoted_results:
            relevant = filter_irrelevant_results(unquoted_q, unquoted_results)
            accumulated.extend(relevant)
            accumulated = deduplicate_by_url(accumulated)
            if len(accumulated) >= _MIN_SATISFACTORY_RESULTS:
                return SearchOutcome(accumulated, f"SearXNG ({primary_lang} unquoted)", failures)
            provider_used = f"SearXNG ({primary_lang} unquoted)"

    # 2. Retry SearXNG fallback language
    if fallback_lang and fallback_lang != primary_lang:
        time.sleep(0.2)
        if event_callback:
            event_callback("web_prefetch.provider_attempt", {"provider": f"SearXNG ({fallback_lang})", "query": query})
        logger.info(f"Trying SearXNG ({fallback_lang}) for: {query}")
        results = take(search_searxng_api(query, count=count, time_filter=time_filter, language=fallback_lang))
        if results:
            relevant = filter_irrelevant_results(query, results)
            accumulated.extend(relevant)
            accumulated = deduplicate_by_url(accumulated)
            if len(accumulated) >= _MIN_SATISFACTORY_RESULTS:
                return SearchOutcome(accumulated, f"SearXNG ({fallback_lang})", failures)
            provider_used = f"SearXNG ({primary_lang}+{fallback_lang})"

    # 3. Fallback DDGS library
    if event_callback:
        event_callback("web_prefetch.provider_attempt", {"provider": "DuckDuckGo (DDGS)", "query": query})
    logger.info(f"Trying DDGS library for: {query}")
    ddgs_results = take(search_ddgs_library(query, count=count, time_filter=time_filter))
    if ddgs_results:
        relevant = filter_irrelevant_results(query, ddgs_results)
        chosen = relevant if relevant else ddgs_results
        accumulated.extend(chosen)
        accumulated = deduplicate_by_url(accumulated)
        if accumulated:
            return SearchOutcome(accumulated, "DuckDuckGo (DDGS)", failures)

    # 4. Fallback DDG HTML scraping
    if not accumulated:
        time.sleep(0.3)
        if event_callback:
            event_callback("web_prefetch.provider_attempt", {"provider": "DuckDuckGo (HTML)", "query": query})
        logger.info("Trying DDG HTML fallback")
        html_results = take(search_duckduckgo_html(query, count=count))
        if html_results:
            relevant = filter_irrelevant_results(query, html_results)
            accumulated.extend(relevant if relevant else html_results)
            provider_used = "DuckDuckGo (HTML)"

    # 5. Last resort DDG Instant Answer API
    if not accumulated:
        if event_callback:
            event_callback("web_prefetch.provider_attempt", {"provider": "DuckDuckGo (Instant API)", "query": query})
        logger.info("Trying DDG Instant Answer API")
        api_results = take(search_duckduckgo_api(query))
        if api_results:
            accumulated.extend(api_results)
            provider_used = "DuckDuckGo (Instant API)"

    return SearchOutcome(deduplicate_by_url(accumulated), provider_used, failures)


def execute_search(
    query: str,
    count: int = 8,
    max_fetch_pages: int = _MAX_FETCH_PAGES,
    event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Execute full search pipeline: query -> fallback -> rank -> safe fetch -> format.

    Guaranteed to return a structured dictionary, never raising uncaught exceptions.
    """
    event_callback = event_callback or _event_sink.get()
    raw_query = query.strip()
    clean_query = normalize_search_query(raw_query) or raw_query
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
        outcome = search_with_fallback(clean_query, count=count, event_callback=event_callback)
        raw_results, provider = outcome
        failures = set(_modes_of(outcome))
    except Exception as e:
        logger.warning(f"Errore provider search per '{clean_query}': {e}", exc_info=True)
        return {
            "query": clean_query,
            "success": False,
            "provider_used": "Error",
            "sources": [],
            "summary_text": "Ricerca degradata: errore motore. Ricerca web temporaneamente non disponibile.",
            "error": "search_unavailable",
            "degraded": True,
        }

    if not raw_results:
        if failures:
            summary = degradation_notice(failures, clean_query, empty=True)
        else:
            summary = f"Nessun risultato trovato per '{clean_query}'."
        return {
            "query": clean_query,
            "success": False,
            "provider_used": provider,
            "sources": [],
            "summary_text": summary,
            "error": None,
            "degraded": bool(failures),
        }

    # Rank results
    try:
        ranked_results = rank_search_results(clean_query, raw_results)
    except Exception as e:
        logger.warning(f"Errore ranking per '{clean_query}': {e}")
        ranked_results = raw_results

    # Build sources list with safe sanitized URLs
    sources = [
        {
            "url": sanitize_source_url(r["url"]),
            "title": r.get("title", "").strip(),
            "snippet": r.get("snippet", "").strip()[:250]
        }
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

    # Format text output for LLM context with total character budget enforcement
    output_parts = []
    notice = degradation_notice(failures, clean_query, empty=False)
    if notice:
        output_parts.append(notice)
    output_parts.extend([
        "=" * 60,
        "WEB SEARCH RESULTS AND FETCHED CONTENT",
        f"Query: {clean_query}",
        f"Provider: {provider} | Risultati trovati: {len(ranked_results)} | Pagine estratte: {len(fetched_content)}",
        "=" * 60,
        "\nRIASSUNTO RISULTATI DI RICERCA:",
        "-" * 40,
    ])

    for i, r in enumerate(sources[:8], 1):
        output_parts.append(f"\n[{i}] {r['title']}")
        output_parts.append(f"    URL: {r['url']}")
        if r.get("snippet"):
            output_parts.append(f"    Snippet: {r['snippet']}")

    current_evidence_chars = sum(len(p) for p in output_parts)

    if fetched_content:
        output_parts.append("\n" + "=" * 60)
        output_parts.append("CONTENUTO DETTAGLIATO DELLE PAGINE:")
        output_parts.append("-" * 40)

        for content in fetched_content:
            if current_evidence_chars >= _MAX_TOTAL_CONTENT_CHARS:
                output_parts.append("\n[Ulteriori dettagli delle pagine omessi per budget di contesto]")
                break

            idx = content.get("source_index", "?")
            page_parts = [
                f"\n[PAGINA {idx}] {content.get('title', '')}",
                f"URL: {content.get('url', '')}",
                "-" * 30,
            ]

            tldr = get_tldr(content.get("content", ""))
            if tldr and len(tldr) > 30:
                page_parts.append(f"TL;DR: {tldr[:400]}\n")

            if content.get("tables"):
                page_parts.append("Tabelle rilevate:")
                for table in content["tables"][:2]:
                    for row in table[:5]:
                        page_parts.append(" | ".join(row))
                page_parts.append("")

            remaining_budget = max(400, _MAX_TOTAL_CONTENT_CHARS - current_evidence_chars)
            allowed_chars = min(_MAX_CONTENT_CHARS, remaining_budget)
            text = content.get("content", "")[:allowed_chars]
            page_parts.append("Testo principale:")
            page_parts.append(text)

            key_pts = extract_key_points(content.get("content", ""))
            if key_pts:
                page_parts.append("\nPunti salienti:")
                for pt in key_pts[:4]:
                    page_parts.append(f"- {pt}")
                page_parts.append("")

            page_block = "\n".join(page_parts)
            current_evidence_chars += len(page_block)
            output_parts.append(page_block)

    output_parts.append("=" * 60)
    output_parts.append("FINE RISULTATI WEB SEARCH")
    output_parts.append("=" * 60)

    summary_text = "\n".join(output_parts)
    elapsed_ms = int((time.time() - start_time) * 1000)
    logger.info(f"Search pipeline completata per '{clean_query}' in {elapsed_ms}ms (sources={len(sources)}, chars={len(summary_text)})")

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
        "degraded": bool(failures),
    }
