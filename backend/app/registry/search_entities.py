"""Una domanda su più prodotti diventa una ricerca per prodotto (ISS-38).

Con una sola query per sette prodotti il primo marchio domina i risultati. Qui si riconosce l'elenco solo
quando la forma è inequivocabile: nomi separati da virgola, «e», «vs»; il primo nome in fondo al suo
pezzo, l'ultimo in testa al suo, quelli in mezzo soli. Altrimenti la domanda resta una query.

Ogni query prodotta usa solo parole della domanda originale: la ricerca passa dallo stesso percorso e
dallo stesso controllo di sensibilità della domanda intera.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from app.registry.search_ranking import _STOPWORDS, _has_word

# Massimo di ricerche per una chiamata di web_search: una per prodotto, più i tentativi con il solo nome.
MAX_SEARCHES = 8

# Parole di comando o di domanda: aprono una frase con la maiuscola ma non sono nomi di prodotto.
_NOT_NAMES = _STOPWORDS | {
    "i", "the", "tra", "fra", "ed", "between", "about", "mi", "dici", "puoi", "vorrei", "dimmi",
    "confronta", "confrontare", "confronto", "compara", "comparare", "compare", "comparison",
    "differenza", "differenze", "difference", "differences", "info", "informazioni", "cerca", "search",
    "come", "cosa", "che", "chi", "dove", "quando", "quale", "quali", "perché", "perche", "quanto",
    "sono", "è", "are", "do", "does", "how", "what", "which", "who", "where", "when", "why", "versus", "contro", "vs", "scritto", "chiamato",
}
_MAX_TOPIC_WORDS = 5
_PARENTHESES = re.compile(r"\([^)]*\)")
_QUOTES = re.compile(r"[«»“”\"]")
_SEPARATORS = re.compile(r"\s*(?:;|(?:(?<!\d),|,(?!\d))|\s/\s)\s*|\s+(?i:vs\.?|versus|contro)\s+|\s+(?:e|ed|and|&)\s+")
_YEAR = re.compile(r"^(?:19|20)\d{2}$")


@dataclass(frozen=True)
class EntityQuery:
    """Un prodotto della domanda: `name` è il solo nome, `query` è il nome con le parole di argomento."""

    name: str
    query: str


def _edge_clean(token: str) -> str:
    return token.strip(".,:;!?()[]")


def _is_name_token(token: str) -> bool:
    if not token or token.lower() in _NOT_NAMES or _YEAR.match(token):
        return False
    return any(char.isupper() or char.isdigit() for char in token)


def _tokens(text: str) -> List[str]:
    return [token for token in (_edge_clean(raw) for raw in text.split()) if token]


def _runs(tokens: List[str]) -> List[tuple]:
    """Gruppi contigui di token-nome, come (inizio, fine escluso)."""
    runs = []
    start: Optional[int] = None
    for index, token in enumerate(tokens):
        if _is_name_token(token):
            if start is None:
                start = index
        elif start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(tokens)))
    return runs


def _simplify(query: str) -> str:
    return _QUOTES.sub(" ", _PARENTHESES.sub(" ", query))


def _brand(name: str) -> str:
    prefix = []
    for token in name.split():
        if any(char.isdigit() for char in token):
            break
        prefix.append(token)
    return " ".join(prefix)


def _topic_words(leftovers: List[str]) -> List[str]:
    words: List[str] = []
    for token in leftovers:
        low = token.lower()
        if low in _NOT_NAMES or low in (word.lower() for word in words):
            continue
        words.append(token)
    return words[:_MAX_TOPIC_WORDS]


def entity_queries(query: str) -> List[EntityQuery]:
    """Una ricerca per prodotto, o lista vuota se la domanda non è un elenco chiaro di nomi."""
    pieces = [piece.strip() for piece in _SEPARATORS.split(_simplify(query)) if piece and piece.strip()]
    if len(pieces) < 2:
        return []
    names: List[str] = []
    leftovers: List[str] = []
    for position, piece in enumerate(pieces):
        tokens = _tokens(piece)
        runs = _runs(tokens)
        if not runs:
            return []
        if position == 0:
            start, end = runs[-1]
            if end != len(tokens):
                return []
        elif position == len(pieces) - 1:
            start, end = runs[0]
            if start != 0:
                return []
        else:
            start, end = runs[0]
            if len(runs) != 1 or (start, end) != (0, len(tokens)):
                return []
        name = " ".join(tokens[start:end])
        if names and len(tokens[start:end]) == 1 and any(char.isdigit() for char in name) and _brand(names[-1]):
            name = f"{_brand(names[-1])} {name}"
        names.append(name)
        leftovers.extend(tokens[:start] + tokens[end:])
    topic = " ".join(_topic_words(leftovers))
    seen = set()
    plans: List[EntityQuery] = []
    for name in names:
        if name.casefold() in seen:
            continue
        seen.add(name.casefold())
        plans.append(EntityQuery(name=name, query=f"{name} {topic}".strip()))
    return plans[:MAX_SEARCHES] if len(plans) >= 2 else []


def bare_name(query: str) -> Optional[str]:
    """Il nome di una domanda con un solo soggetto, se la query ha anche altre parole."""
    tokens = _tokens(_simplify(query))
    runs = _runs(tokens)
    if len(runs) != 1:
        return None
    start, end = runs[0]
    if end - start == len(tokens):
        return None
    return " ".join(tokens[start:end])


def name_in_results(name: str, results: List[dict]) -> bool:
    """Vero se almeno una fonte contiene tutte le parole del nome (titolo, snippet o indirizzo)."""
    words = [
        word.lower() for word in re.findall(r"[A-Za-z0-9]+", name)
        if word.lower() not in _STOPWORDS and len(word) > 1
    ]
    if not words:
        return True
    for result in results:
        text = f"{result.get('title', '')} {result.get('snippet', '')} {result.get('url', '')}".lower()
        if all(_has_word(text, word) for word in words):
            return True
    return False


def interleave(groups: List[List[dict]]) -> List[dict]:
    """Un risultato a turno da ogni gruppo, senza ripetere un indirizzo."""
    merged: List[dict] = []
    seen = set()
    for rank in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if rank >= len(group):
                continue
            item = group[rank]
            url = (item.get("url") or "").rstrip("/")
            if url and url not in seen:
                seen.add(url)
                merged.append(item)
    return merged
