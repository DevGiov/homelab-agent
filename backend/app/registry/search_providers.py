import logging
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, quote, urljoin, urlparse

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_SEARCH_TIMEOUT = 12

# Modi di fallimento generici. Il testo per il modello usa solo questi, mai il nome del motore.
FAILURE_ENGINE = "engine_error"
FAILURE_SUSPENDED = "suspended"
FAILURE_CAPTCHA = "captcha"


class ProviderResults(list):
    """Risultati di un provider, con i modi di fallimento dei motori."""

    def __init__(self, items: Optional[List[Dict[str, str]]] = None, failures: Optional[Iterable[str]] = None):
        super().__init__(items or [])
        self.failures = frozenset(failures or ())


def classify_engine_failure(item: Any) -> Optional[str]:
    """Riduce un motore non responsivo a errore motore, sospeso o captcha.

    Il nome del motore non entra nella classificazione: non deve finire nel testo per il modello.
    """
    if item is None:
        return None
    suspended_flag = False
    if isinstance(item, dict):
        suspended_flag = bool(item.get("suspended"))
        text = " ".join(
            str(item.get(key) or "")
            for key in ("error_type", "error", "message", "reason", "status")
        )
    elif isinstance(item, (list, tuple)):
        parts = list(item)
        if parts and isinstance(parts[-1], bool):
            suspended_flag = bool(parts.pop())
        detail = parts[1:] if len(parts) > 1 else []
        text = " ".join(str(part) for part in detail if not isinstance(part, bool))
    else:
        text = str(item)
    low = text.lower()
    if any(token in low for token in ("captcha", "recaptcha", "hcaptcha")):
        return FAILURE_CAPTCHA
    if suspended_flag or any(token in low for token in ("suspend", "too many", "rate limit", "rate-limit")):
        return FAILURE_SUSPENDED
    if low.strip():
        return FAILURE_ENGINE
    if suspended_flag:
        return FAILURE_SUSPENDED
    return None


def _failure_modes(unresponsive: Any) -> frozenset:
    modes = set()
    for item in unresponsive or []:
        mode = classify_engine_failure(item)
        if mode:
            modes.add(mode)
    return frozenset(modes)

def get_searxng_url() -> Optional[str]:
    """URL di SearXNG dalle settings; vuoto = provider disabilitato."""
    url = settings.searxng_url
    return url.rstrip("/") if url else None

def search_searxng_api(
    query: str,
    count: int = 8,
    time_filter: Optional[str] = None,
    language: Optional[str] = None,
) -> ProviderResults:
    """Search using SearXNG JSON API.

    Args:
        query: Search query string.
        count: Max number of results to return.
        time_filter: One of 'day', 'week', 'month', 'year'.
        language: Language code for results (e.g. 'en', 'it'). None uses SearXNG default.
    """
    url = get_searxng_url()
    if not url:
        return ProviderResults()

    params: Dict[str, str] = {
        "q": query,
        "format": "json",
        "engines": settings.searxng_engines,
        "categories": "general",
        "safesearch": "0",
    }

    if language:
        params["language"] = language

    if time_filter:
        time_map = {"day": "day", "week": "week", "month": "month", "year": "year"}
        if time_filter in time_map:
            params["time_range"] = time_map[time_filter]

    try:
        logger.info(f"SearXNG request: q={query!r}  lang={language}  engines={settings.searxng_engines}")
        res = requests.get(
            f"{url}/search",
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=_SEARCH_TIMEOUT,
        )
        if res.status_code != 200:
            logger.warning(f"SearXNG returned {res.status_code}")
            return ProviderResults([], {FAILURE_ENGINE})

        data = res.json()
        results = []
        for item in data.get("results", [])[:count * 2]:  # Get more for ranking
            link = item.get("url", "")
            title = item.get("title", "")
            if not link or not title:
                continue
            results.append({
                "title": title,
                "url": link,
                "snippet": item.get("content", ""),
                "age": item.get("publishedDate", None),
                "engine": item.get("engine", ""),
            })
        modes = _failure_modes(data.get("unresponsive_engines"))
        logger.info(f"SearXNG returned {len(results)} results for: {query}")
        return ProviderResults(results, modes)
    except Exception as e:
        logger.warning(f"SearXNG search failed: {e}")
        return ProviderResults([], {FAILURE_ENGINE})


def search_ddgs_library(query: str, count: int = 8, time_filter: Optional[str] = None) -> ProviderResults:
    """Search using the ddgs library (duckduckgo fallback).

    Supports both the new 'ddgs' package name and the legacy 'duckduckgo_search' name.
    """
    DDGS = None
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            logger.warning("Neither 'ddgs' nor 'duckduckgo_search' package installed; skipping DDGS provider")
            return ProviderResults()

    timelimit = None
    if time_filter:
        time_map = {"day": "d", "week": "w", "month": "m", "year": "y"}
        timelimit = time_map.get(time_filter)

    try:
        ddgs = DDGS()
        raw = ddgs.text(query, max_results=count * 2, timelimit=timelimit)
        results = []
        for item in raw:
            url = item.get("href", "") or item.get("url", "")
            if not url:
                continue
            results.append({
                "title": item.get("title", ""),
                "url": url,
                "snippet": item.get("body", "") or item.get("excerpt", ""),
            })
        logger.info(f"DDGS library returned {len(results)} results for: {query}")
        return ProviderResults(results)
    except Exception as e:
        logger.warning(f"DDGS library search failed: {e}")
        return ProviderResults([], {FAILURE_ENGINE})

def _resolve_ddg_redirect(raw_url: str) -> str:
    """Resolve DDG /l/?uddg=... redirect URLs to actual destinations."""
    if not raw_url:
        return raw_url
    resolved = raw_url
    if resolved.startswith("//"):
        resolved = "https:" + resolved
    elif resolved.startswith("/"):
        resolved = urljoin("https://html.duckduckgo.com", resolved)
    try:
        parsed = urlparse(resolved)
        hostname = (parsed.hostname or "").lower()
        if (hostname == "duckduckgo.com" or hostname.endswith(".duckduckgo.com")) and parsed.path.rstrip("/") == "/l":
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                return qs["uddg"][0]
    except Exception:
        pass
    return resolved

def search_duckduckgo_html(query: str, count: int = 8) -> ProviderResults:
    """Fallback: Search DuckDuckGo HTML lite."""
    from bs4 import BeautifulSoup
    headers = {"User-Agent": _USER_AGENT}
    results = []

    try:
        res = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers=headers,
            timeout=_SEARCH_TIMEOUT,
        )
        if res.status_code not in (200, 202):
            return ProviderResults([], {FAILURE_ENGINE})

        text = res.text
        if "anomaly-modal" in text or "Select all squares" in text:
            logger.warning("DDG HTML returned CAPTCHA page")
            return ProviderResults([], {FAILURE_CAPTCHA})

        soup = BeautifulSoup(text, "html.parser")
        for result in soup.select(".result")[:count * 2]:
            link_el = result.select_one(".result__a")
            if not link_el:
                continue
            url = _resolve_ddg_redirect(link_el.get("href", ""))
            if not url:
                continue
            snippet_el = result.select_one(".result__snippet")
            results.append({
                "title": link_el.get_text(" ", strip=True),
                "url": url,
                "snippet": snippet_el.get_text(" ", strip=True) if snippet_el else "",
            })
        logger.info(f"DDG HTML returned {len(results)} results")
        return ProviderResults(results)
    except Exception as e:
        logger.warning(f"DDG HTML search error: {e}")
        return ProviderResults([], {FAILURE_ENGINE})

def search_duckduckgo_api(query: str) -> ProviderResults:
    """DuckDuckGo Instant Answer API for quick facts."""
    headers = {"User-Agent": _USER_AGENT}
    results = []
    try:
        url_api = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_html=1&skip_disambig=1"
        res = requests.get(url_api, headers=headers, timeout=_SEARCH_TIMEOUT)
        if res.status_code not in (200, 202):
            return ProviderResults([], {FAILURE_ENGINE})
        data = res.json()
        abstract = data.get("AbstractText", "")
        heading = data.get("Heading", "")
        abstract_url = data.get("AbstractURL", "")
        if abstract and len(abstract) > 30:
            results.append({
                "title": heading or "DuckDuckGo Abstract",
                "url": abstract_url or "",
                "snippet": abstract[:500],
            })
        return ProviderResults(results)
    except Exception:
        return ProviderResults([], {FAILURE_ENGINE})
