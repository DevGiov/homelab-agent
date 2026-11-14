"""Testo che viene da contenuto non attendibile dentro gli argomenti di un tool (design 7.3, decisione 6).

Un permesso già dato per un'azione che modifica qualcosa non vale quando i suoi argomenti portano testo che il turno ha
letto da contenuto scritto da altri (pagina web, email, fatto ricordato da contenuto esterno) e che l'utente non ha
scritto: in quel caso si chiede di nuovo. Il criterio è stretto di proposito: una conferma che compare a ogni comando
non viene più letta.

Cosa NON riconosce: un'istruzione letta da fuori ed eseguita con parole che vengono da altrove (la pagina dice "ferma
il container dell'agent" e il modello ricava l'id da un tool). Lì non c'è testo da confrontare.
"""
import re
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, List, Optional, Set, Tuple

# Separatori di parole in un comando e in un testo; un secondo taglio apre URL e percorsi nelle loro parti
_SEPARATORS = re.compile(r"""[\s;|&<>()\[\]{}"'`$=,*]+""")
_INNER = re.compile(r"[/:@?#]+")
_EDGES = ".,:;!?…-_"
# Una parola corta è una prova debole: 4 caratteri, 3 se contiene una cifra (id di container, porte)
MIN_LEN = 4
MIN_LEN_WITH_DIGIT = 3
# Quante parole mostrare nella richiesta di conferma
SHOWN = 5
# Vocabolario dei comandi: parole che stanno in ogni guida e in ogni comando e da sole non dicono da dove viene un
# argomento. Contano i bersagli (un pacchetto, un indirizzo, un file, un servizio), non il verbo
COMMAND_WORDS = frozenset("""
http https sudo bash echo curl wget true false null none root
install remove purge update upgrade restart start stop status enable disable reload
pull push exec build clone commit delete create list show config service compose docker systemctl apt-get
""".split())


@dataclass(frozen=True)
class Provenance:
    """Ciò che serve per riconoscere testo non attendibile negli argomenti di un tool.

    `untrusted`: coppie (origine, testo) di ciò che il turno ha letto da fuori. `trusted`: ciò che ha scritto l'utente
    (la richiesta e i suoi messaggi nella conversazione): una parola che l'utente ha scritto non è "portata da fuori"
    anche se compare pure in una pagina."""
    untrusted: Tuple[Tuple[str, str], ...] = ()
    trusted: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Carried:
    """Parole degli argomenti che vengono da contenuto non attendibile, con le origini in cui compaiono."""
    words: Tuple[str, ...]
    origins: Tuple[str, ...]

    def describe(self) -> str:
        shown = ", ".join(f"'{w}'" for w in self.words[:SHOWN])
        more = f" e altre {len(self.words) - SHOWN}" if len(self.words) > SHOWN else ""
        return f"{shown}{more} (da: {', '.join(self.origins)})"


def guarded_spans(text: str, guard_open: str, guard_close: str) -> List[str]:
    """I tratti di un testo racchiusi tra i delimitatori del contenuto non attendibile (un contesto già composto, come
    la memoria richiamata, li usa per i fatti nati da contenuto esterno)."""
    spans: List[str] = []
    rest = text or ""
    while guard_open in rest:
        _, _, rest = rest.partition(guard_open)
        inside, found, rest = rest.partition(guard_close)
        if inside.strip():
            spans.append(inside)
        if not found:
            break
    return spans


def _significant(word: str) -> bool:
    if not any(c.isalnum() for c in word) or word in COMMAND_WORDS:
        return False
    return len(word) >= (MIN_LEN_WITH_DIGIT if any(c.isdigit() for c in word) else MIN_LEN)


def words(text: str) -> Set[str]:
    """Le parole significative di un testo, in minuscolo: intere e nelle parti di URL e percorsi. Le opzioni di un
    comando (`-y`, `--now`) non contano."""
    found: Set[str] = set()
    for raw in _SEPARATORS.split(text.lower()):
        if not raw or raw.startswith("-"):
            continue
        for part in (raw, *_INNER.split(raw)):
            part = part.strip(_EDGES)
            if _significant(part):
                found.add(part)
    return found


def _strings(value: Any) -> Iterator[str]:
    """I valori di testo degli argomenti, a ogni profondità; i numeri contano (l'id di un container), i booleani no."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float)):
        yield str(value)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _strings(v)


def _all_words(texts: Iterable[str]) -> Set[str]:
    found: Set[str] = set()
    for t in texts:
        found |= words(t)
    return found


def carried_text(args: Any, provenance: Optional[Provenance], approved_prefix: str = "") -> Optional[Carried]:
    """Le parole degli argomenti che compaiono nel contenuto non attendibile del turno e non in ciò che ha scritto
    l'utente, né nel prefisso che l'utente ha autorizzato. None se non ce ne sono (o se il turno non ha letto nulla da
    fuori)."""
    if provenance is None or not provenance.untrusted:
        return None
    candidates = _all_words(_strings(args)) - _all_words(provenance.trusted) - words(approved_prefix or "")
    if not candidates:
        return None
    hits: Set[str] = set()
    origins: List[str] = []
    for origin, text in provenance.untrusted:
        found = candidates & words(text)
        if found:
            hits |= found
            if origin not in origins:
                origins.append(origin)
    if not hits:
        return None
    # Prima le più lunghe: sono le più riconoscibili per chi legge la richiesta
    return Carried(tuple(sorted(hits, key=lambda w: (-len(w), w))), tuple(origins))
