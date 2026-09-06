import logging
import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Minimal set of language-agnostic function words (articles, prepositions, conjunctions)
# only filtered out when computing query-term overlap.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "to", "for", "is", "it",
    "di", "il", "la", "le", "lo", "gli", "un", "una", "e", "che", "per", "con",
    "del", "dei", "delle", "da", "in", "su", "nel", "nella", "sui", "sulle",
}

_GENERIC_TECH_TOKENS = {
    "gpt", "ai", "chatgpt", "llm", "model", "modello", "modelli", "models",
    "vs", "versus", "comparison", "confronto", "artificial", "intelligence",
    "online", "api", "app", "pro", "plus", "free", "gratis", "news", "notizie"
}

_AGE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")

def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

def recency_score(age_str: Optional[str], now: Optional[datetime] = None) -> float:
    if not age_str:
        return 0.0
    dt = None
    for fmt in _AGE_FORMATS:
        try:
            dt = datetime.strptime(age_str, fmt)
            break
        except Exception:
            dt = None
    if not dt:
        return 0.0
    now = now or _utcnow_naive()
    days_old = (now - dt).days
    if days_old <= 7:
        return 1.0
    if days_old >= 30:
        return 0.0
    return (30 - days_old) / 23

_LOW_VALUE_NEWS_DOMAINS = {
    "facebook.com", "www.facebook.com", "sports.yahoo.com", "yahoo.com",
    "www.yahoo.com", "msn.com", "www.msn.com",
}
_TRUSTED_NEWS_DOMAINS = {
    "apnews.com", "www.apnews.com", "reuters.com", "www.reuters.com",
    "bbc.com", "www.bbc.com", "cbc.ca", "www.cbc.ca",
    "theguardian.com", "www.theguardian.com", "euronews.com", "www.euronews.com",
    "ansa.it", "www.ansa.it", "repubblica.it", "www.repubblica.it",
    "corriere.it", "www.corriere.it", "ilsole24ore.com", "www.ilsole24ore.com",
    "nasa.gov", "science.nasa.gov", "space.com", "www.space.com",
}

def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

def _has_word(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None

def _content_query_terms(query: str) -> List[str]:
    """Extract meaningful query terms, filtering out common stopwords."""
    return [
        t.lower() for t in re.findall(r"\b\w+\b", query)
        if t.lower() not in _STOPWORDS and len(t) > 1
    ]

def compute_relevance(query: str, title: str, snippet: str) -> float:
    """Return a 0-1 score measuring how many content query terms appear
    in the title or snippet (case-insensitive, word-boundary match)."""
    terms = _content_query_terms(query)
    if not terms:
        return 1.0
    text = f"{title} {snippet}".lower()
    hits = sum(1 for t in terms if _has_word(text, t))
    return hits / len(terms)

def is_result_relevant(query: str, title: str, snippet: str) -> bool:
    """Determine if a result is genuinely relevant to the query.
    Prevents false positives from accidental matches on a single ambiguous word or generic buzzwords.
    """
    terms = _content_query_terms(query)
    if not terms:
        return True

    text = f"{title} {snippet}".lower()

    # If the query contains distinctive entity terms (e.g. 'astra', 'sol'),
    # require that at least one distinctive entity term is present in title or snippet.
    specific_terms = [t for t in terms if t not in _GENERIC_TECH_TOKENS]
    if specific_terms:
        specific_hits = sum(1 for t in specific_terms if _has_word(text, t))
        if specific_hits == 0:
            return False

    hits = sum(1 for t in terms if _has_word(text, t))

    if len(terms) >= 4:
        # Long query (e.g. 4+ content words): require at least 2 matching words
        return hits >= 2
    elif len(terms) >= 2:
        # 2-3 words: require at least 1 match in the title or 2 in title+snippet
        title_hits = sum(1 for t in terms if _has_word(title.lower(), t))
        return hits >= 2 or title_hits >= 1
    else:
        # Single-word query
        return hits >= 1

def filter_irrelevant_results(query: str, results: List[dict]) -> List[dict]:
    """Filter out results that don't satisfy minimal query overlap."""
    kept = [
        r for r in results
        if is_result_relevant(query, r.get("title", ""), r.get("snippet", ""))
    ]
    logger.info(
        "Relevance filter: %d/%d results kept for query %r",
        len(kept), len(results), query,
    )
    return kept

def rank_search_results(query: str, results: List[dict]) -> List[dict]:
    """Rank search results by title relevance, snippet quality, domain authority, and recency."""
    query_terms = _content_query_terms(query)

    def title_score(title: str) -> float:
        if not title or not query_terms:
            return 0.0
        title_lc = title.lower()
        matches = sum(1 for term in query_terms if _has_word(title_lc, term))
        return matches / len(query_terms)

    def snippet_score(snippet: str) -> float:
        if not snippet or not query_terms:
            return 0.0
        length_factor = min(len(snippet), 200) / 200
        term_hits = sum(1 for term in query_terms if _has_word(snippet.lower(), term))
        term_factor = term_hits / len(query_terms)
        return (length_factor + term_factor) / 2

    def domain_score(url: str) -> float:
        netloc = _domain(url)
        if not netloc:
            return 0.0
        if netloc in _TRUSTED_NEWS_DOMAINS:
            return 1.2
        if netloc.endswith(".edu") or netloc.endswith(".gov"):
            return 1.2
        if netloc.endswith(".org"):
            return 0.8
        if netloc in _LOW_VALUE_NEWS_DOMAINS:
            return 0.2
        return 0.5

    ranked = []
    for result in results:
        title = result.get("title", "")
        snippet = result.get("snippet", "")
        url = result.get("url", "")
        age = result.get("age", None)

        score = (
            3.0 * title_score(title)
            + 1.5 * snippet_score(snippet)
            + 1.0 * domain_score(url)
            + 1.0 * recency_score(age)
        )
        ranked.append((score, result))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in ranked]


_CONVERSATIONAL_PREFIXES = (
    r"^(?:ciao|buongiorno|buonasera|salve|hey|hello|hi)[,\s]*",
    r"^(?:per\s+favore|per\s+cortesia|ti\s+prego|please)[,\s]*",
    r"^(?:mi\s+(?:dici|diresse|spieghi|trovi|cerchi)|puoi\s+(?:dirmi|spiegarmi|cercare|trovare)|sapresti\s+dirmi)[,\s]*",
    r"^(?:vorrei\s+sapere|vorrei\s+conoscere|voglio\s+sapere|dimmi|spiegami|trova|cerca)[,\s]*",
    r"^(?:can\s+you\s+(?:tell|explain|find|search)|tell\s+me|show\s+me|find|search\s+for)[,\s]*",
)

def normalize_search_query(query: str) -> str:
    """Normalizza la query rimuovendo prefissi colloquiali senza perdere entità, date o codici."""
    if not query or not isinstance(query, str):
        return ""
    q = query.strip()
    changed = True
    while changed:
        changed = False
        for pat in _CONVERSATIONAL_PREFIXES:
            new_q = re.sub(pat, "", q, flags=re.IGNORECASE).strip()
            if new_q != q and len(new_q) >= 3:
                q = new_q
                changed = True
                break
    # Rimuovi punti interrogativi o esclamativi finali ridondanti per i motori di ricerca
    q = re.sub(r"[\?!.]+$", "", q).strip()
    return q if q else query.strip()

