"""Richieste verso indirizzi scelti dal modello (`http_get`, `inspect_image` con un URL): host ammessi e controllo.

Una richiesta così è un'uscita di dati: indirizzo, query string e intestazioni li scrive il modello, che può averci
messo qualunque cosa abbia in contesto. Regole, in ordine:

1. Solo `http` e `https`.
2. Un host nella lista degli **host ammessi** (impostazioni, modificabile dalla UI) o in quella della policy
   dell'automazione in corso parte senza chiedere, anche se è nella rete locale.
3. Un host interno (rete privata, loopback, link-local, nomi locali) che non è in lista è **bloccato**, in ogni
   modalità di sicurezza: è la protezione SSRF.
4. Ogni altro host richiede l'approvazione dell'utente (`ApprovalRequired`, capability `net:<host>`), che vede
   l'indirizzo completo e le intestazioni. "Sempre" aggiunge l'host alla lista.

I redirect si seguono a mano, al massimo `MAX_REDIRECTS`: ogni passo rifà il controllo SSRF; un passo verso un host
pubblico non in lista è ammesso, perché l'indirizzo lo sceglie il server e non il modello. Le intestazioni scelte
dal modello non passano a un host diverso da quello richiesto.

Formato di una voce della lista: un nome (`example.com`, solo quel nome), un nome con `*.` davanti (`*.example.com`:
il dominio e tutti i suoi sottodomini) o un indirizzo IP. Niente porte né percorsi.
"""
from __future__ import annotations

import contextvars
import ipaddress
import logging
import re
import sqlite3
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from app.core.config import settings
from app.registry.search_security import internal_host_reason

logger = logging.getLogger("network")

CAPABILITY_PREFIX = "net:"
MAX_REDIRECTS = 5
USER_AGENT = "homelab-agent/1.0"

# Servizi pubblici noti, usati in lettura: enciclopedie, documentazione, codice pubblico, registri di pacchetti,
# articoli scientifici, meteo. Inseriti alla prima inizializzazione; l'utente li toglie o ne aggiunge dalla UI.
# Un indirizzo verso questi host può comunque portare dati nella query string: la lista dice dove si può andare
# senza chiedere, non che cosa si può mandare.
DEFAULT_ALLOWED_HOSTS: Tuple[Tuple[str, str], ...] = (
    ("*.wikipedia.org", "Wikipedia"),
    ("*.wikimedia.org", "Immagini e file di Wikipedia"),
    ("*.wikidata.org", "Wikidata"),
    ("github.com", "GitHub"),
    ("api.github.com", "API di GitHub"),
    ("raw.githubusercontent.com", "File dei repository pubblici di GitHub"),
    ("gitlab.com", "GitLab"),
    ("pypi.org", "Registro dei pacchetti Python"),
    ("registry.npmjs.org", "Registro dei pacchetti npm"),
    ("huggingface.co", "Modelli e dataset di Hugging Face"),
    ("*.arxiv.org", "Articoli scientifici arXiv e relativa API"),
    ("api.crossref.org", "Metadati degli articoli scientifici"),
    ("docs.python.org", "Documentazione di Python"),
    ("developer.mozilla.org", "Documentazione web MDN"),
    ("stackoverflow.com", "Stack Overflow"),
    ("api.stackexchange.com", "API di Stack Exchange"),
    ("hacker-news.firebaseio.com", "API di Hacker News"),
    ("*.open-meteo.com", "Previsioni meteo Open-Meteo"),
)

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_SENSITIVE_HEADER = re.compile(r"authorization|cookie|token|secret|key|password", re.IGNORECASE)

# Host ammessi in più per l'esecuzione in corso: quelli della policy dell'automazione (ToolRegistryManager)
_scope_hosts: contextvars.ContextVar[Tuple[str, ...]] = contextvars.ContextVar("network_scope_hosts", default=())


class NetworkBlocked(Exception):
    """L'indirizzo non si può raggiungere in nessun caso (schema, host interno non ammesso, nome non risolvibile)."""


# --- Voci della lista -----------------------------------------------------------------------------

def normalize_pattern(raw: str) -> str:
    """Voce valida e normalizzata, o ValueError con il motivo. Accetta anche un URL incollato, da cui tiene l'host."""
    text = str(raw or "").strip().lower()
    if "://" in text:
        text = urlparse(text).hostname or ""
    text = text.strip().rstrip(".")
    if not text:
        raise ValueError("Host vuoto.")
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        pass
    if "/" in text or ":" in text:
        raise ValueError(f"'{raw}': indica solo il nome dell'host, senza porta né percorso.")
    wildcard = text.startswith("*.")
    labels = (text[2:] if wildcard else text).split(".")
    if "*" in "".join(labels) or not all(_LABEL.match(label) for label in labels):
        raise ValueError(f"'{raw}' non è un nome di host valido.")
    if wildcard and len(labels) < 2:
        raise ValueError(f"'{raw}': con '*.' servono almeno due livelli (per esempio '*.example.com').")
    return text


def host_matches(host: str, pattern: str) -> bool:
    host = host.lower().rstrip(".")
    if pattern.startswith("*."):
        domain = pattern[2:]
        return host == domain or host.endswith("." + domain)
    return host == pattern


def _matches_any(host: str, patterns: Iterable[str]) -> bool:
    return any(host_matches(host, p) for p in patterns)


# --- Archivio --------------------------------------------------------------------------------------

@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = Path(settings.checkpoint_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_network_db() -> None:
    """Crea la tabella e, solo la prima volta, inserisce gli host predefiniti: una voce tolta dall'utente non torna."""
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS allowed_hosts ("
            " host TEXT PRIMARY KEY, note TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        conn.execute("CREATE TABLE IF NOT EXISTS security_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        seeded = conn.execute("SELECT 1 FROM security_meta WHERE key = 'allowed_hosts_seeded'").fetchone()
        if not seeded:
            _insert_defaults(conn)
            conn.execute("INSERT INTO security_meta (key, value) VALUES ('allowed_hosts_seeded', ?)", (_now(),))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert_defaults(conn: sqlite3.Connection) -> int:
    added = 0
    for host, note in DEFAULT_ALLOWED_HOSTS:
        cur = conn.execute(
            "INSERT OR IGNORE INTO allowed_hosts (host, note, origin, created_at) VALUES (?, ?, 'default', ?)",
            (host, note, _now()),
        )
        added += cur.rowcount
    return added


def list_allowed_hosts() -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT host, note, origin, created_at FROM allowed_hosts ORDER BY host").fetchall()
    return [dict(r) for r in rows]


def allowed_patterns() -> List[str]:
    with _connect() as conn:
        return [r["host"] for r in conn.execute("SELECT host FROM allowed_hosts")]


def add_allowed_host(raw: str, note: str = "", origin: str = "user") -> Dict[str, Any]:
    """Aggiunge una voce (o ne aggiorna la nota). `origin`: user | approval | default."""
    host = normalize_pattern(raw)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO allowed_hosts (host, note, origin, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(host) DO UPDATE SET note = excluded.note",
            (host, str(note or "").strip()[:200], origin, _now()),
        )
        row = conn.execute("SELECT host, note, origin, created_at FROM allowed_hosts WHERE host = ?", (host,)).fetchone()
    logger.info(f"Host ammesso: '{host}' (origine {origin})")
    return dict(row)


def remove_allowed_host(raw: str) -> bool:
    try:
        host = normalize_pattern(raw)
    except ValueError:
        return False
    with _connect() as conn:
        removed = conn.execute("DELETE FROM allowed_hosts WHERE host = ?", (host,)).rowcount
    if removed:
        logger.info(f"Host tolto dalla lista: '{host}'")
    return bool(removed)


def restore_default_hosts() -> int:
    """Rimette gli host predefiniti che mancano; non tocca le altre voci. Ritorna quanti ne ha aggiunti."""
    with _connect() as conn:
        return _insert_defaults(conn)


# --- Ambito dell'esecuzione ------------------------------------------------------------------------

def run_with_scope_hosts(hosts: Optional[Sequence[str]], fn, *args, **kwargs):
    """Esegue `fn` ammettendo anche `hosts` (la policy di un'automazione). Voci non valide ignorate."""
    valid = []
    for raw in hosts or ():
        try:
            valid.append(normalize_pattern(raw))
        except ValueError:
            logger.warning(f"Host non valido nella policy ignorato: {raw!r}")
    token = _scope_hosts.set(tuple(valid))
    try:
        return fn(*args, **kwargs)
    finally:
        _scope_hosts.reset(token)


# --- Controllo -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Verdict:
    host: str
    allowed: bool  # True: parte senza chiedere. False: serve l'approvazione


def _host_of(url: str) -> Tuple[str, str]:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise NetworkBlocked(f"Schema non ammesso in '{url}': solo http e https.")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise NetworkBlocked(f"Indirizzo senza host: '{url}'.")
    return parsed.scheme, host


def is_listed(host: str) -> bool:
    return _matches_any(host, _scope_hosts.get()) or _matches_any(host, allowed_patterns())


def check_url(url: str) -> Verdict:
    """Verdetto per un indirizzo scelto dal modello. Solleva NetworkBlocked se non si può raggiungere in nessun caso."""
    _, host = _host_of(url)
    if is_listed(host):
        return Verdict(host, True)
    reason = internal_host_reason(host)
    if reason:
        raise NetworkBlocked(
            f"Host '{host}' non raggiungibile: {reason}. Se è un servizio di cui ti fidi, aggiungilo agli host ammessi "
            "(Impostazioni > Sicurezza, o la policy dell'automazione)."
        )
    return Verdict(host, False)


def capability_for(host: str) -> str:
    return f"{CAPABILITY_PREFIX}{host}"


def host_from_capability(capability: Optional[str]) -> Optional[str]:
    if capability and capability.startswith(CAPABILITY_PREFIX):
        return capability[len(CAPABILITY_PREFIX):] or None
    return None


def _masked(name: str, value: Any) -> str:
    text = str(value)
    return f"•••• ({len(text)} caratteri)" if _SENSITIVE_HEADER.search(name) else text


def request_preview(url: str, headers: Optional[Mapping[str, Any]] = None) -> str:
    """Testo mostrato nella richiesta di approvazione: ciò che esce, con i valori delle intestazioni di accesso coperti."""
    lines = [f"GET {url}"]
    for name, value in (headers or {}).items():
        lines.append(f"{name}: {_masked(str(name), value)}")
    return "\n".join(lines)


def require_approval_unless_listed(tool_name: str, url: str, headers: Optional[Mapping[str, Any]] = None) -> str:
    """Controllo da chiamare nel tool prima della richiesta. Ritorna l'host; solleva NetworkBlocked o ApprovalRequired.

    L'approvazione vale per la capability `net:<host>`: la concede la richiesta approvata (una volta), un permesso per
    la chat, o la lista degli host ammessi."""
    from app.security import approvals

    verdict = check_url(url)
    capability = capability_for(verdict.host)
    if verdict.allowed or approvals.is_capability_approved(capability):
        return verdict.host
    raise approvals.ApprovalRequired(
        capability,
        f"'{tool_name}' vuole contattare '{verdict.host}', che non è tra gli host ammessi: indirizzo e intestazioni "
        "escono dalla rete",
        preview=request_preview(url, headers),
    )


# --- Richiesta -------------------------------------------------------------------------------------

@dataclass
class FetchResult:
    status: int
    headers: Mapping[str, str]
    body: bytes
    final_url: str


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - firma di urllib
        return None


def _open(request: urllib.request.Request, timeout: float):
    """Unico punto che apre una connessione (sostituito nei test)."""
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)


def _redirect_hop_allowed(url: str) -> None:
    """Un redirect lo sceglie il server: basta che non porti a un host interno non ammesso."""
    _, host = _host_of(url)
    if is_listed(host):
        return
    reason = internal_host_reason(host)
    if reason:
        raise NetworkBlocked(f"Redirect verso '{host}' bloccato: {reason}.")


def fetch(url: str, *, headers: Optional[Mapping[str, Any]] = None, timeout: float = 15.0,
          max_bytes: int = 1024 * 1024) -> FetchResult:
    """GET con redirect seguiti a mano. Il primo indirizzo va già controllato (`require_approval_unless_listed`).

    Solleva NetworkBlocked per un redirect verso un host interno o troppo lunghi; urllib.error.URLError per errori di
    rete. Un codice HTTP di errore torna come FetchResult con il suo status."""
    current = url
    _, first_host = _host_of(url)
    for _ in range(MAX_REDIRECTS + 1):
        _, host = _host_of(current)
        request = urllib.request.Request(current, headers={"User-Agent": USER_AGENT})
        # Le intestazioni del modello (anche di accesso) vanno solo all'host che ha chiesto
        if host == first_host:
            for name, value in (headers or {}).items():
                request.add_header(str(name), str(value))
        try:
            with _open(request, timeout) as resp:
                return FetchResult(resp.status, dict(resp.headers), resp.read(max_bytes), current)
        except urllib.error.HTTPError as e:
            location = e.headers.get("Location") if e.headers else None
            if e.code in (301, 302, 303, 307, 308) and location:
                current = urljoin(current, location)
                _redirect_hop_allowed(current)
                continue
            body = e.read(max_bytes) if hasattr(e, "read") else b""
            return FetchResult(e.code, dict(e.headers or {}), body or b"", current)
    raise NetworkBlocked(f"Troppi redirect a partire da '{url}' (massimo {MAX_REDIRECTS}).")
