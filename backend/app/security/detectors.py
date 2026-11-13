"""Rilevatori di dati sensibili nel testo: segreti, dati personali e indirizzi interni.

Design: docs/sensitivity/SENSITIVITY_DESIGN.md (sezioni 3 e 4.2).
Funzioni pure e senza effetti: trovano dati sensibili nel testo e possono solo
alzare l'etichetta di sensibilità, mai abbassarla.
Nessun log né stampa del contenuto sensibile trovato.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Iterable, List, Mapping, Optional, Tuple

from app.security.flows import PUBLIC_TAG, Label, Tag


@dataclass(frozen=True)
class Finding:
    kind: str
    label: Label
    start: int
    end: int


# --- Espressioni regolari precompilate a livello di modulo -----------------------------------------

# Blocchi PEM di chiavi private
_PEM_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 _-]+PRIVATE KEY-----[\s\S]+?-----END [A-Z0-9 _-]+PRIVATE KEY-----"
)

# Token con prefissi noti
_KNOWN_TOKENS_PATTERN = re.compile(
    r"""(?x)
    \b(?:
        (?:ghp|gho|ghs)_[0-9A-Za-z]{10,}
      | github_pat_[0-9A-Za-z_]{10,}
      | glpat-[0-9A-Za-z_-]{10,}
      | sk-ant-[0-9A-Za-z_-]{10,}
      | sk-proj-[0-9A-Za-z_-]{10,}
      | sk-[0-9A-Za-z]{20,}
      | xox[baprs]-[0-9A-Za-z-]{10,}
      | AKIA[0-9A-Z]{16}
      | AIza[0-9A-Za-z_-]{35}
      | hf_[0-9A-Za-z]{30,}
    )\b
    """
)

# JWT (tre segmenti base64url separati da punti, il primo che inizia con eyJ)
_JWT_PATTERN = re.compile(
    r"\beyJ[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+\.[0-9A-Za-z_-]+\b"
)

# Valori dopo chiavi di autenticazione/password (lo span catturato è solo il valore)
_KV_SECRET_PATTERN = re.compile(
    r"""(?ix)
    (?:
        \b(?:password|passwd|pwd|token|secret|api_key|apikey|access_key)\s*[:=]\s*
      | \bauthorization\s*[:=]\s*bearer\s+
      | \bauthorization\s*[:=]\s*bearer\s*[:=]\s*
    )
    (?:
        "(?P<val_dq>[^"\r\n]{8,})"
      | '(?P<val_sq>[^'\r\n]{8,})'
      | (?P<val_raw>\S{8,})
    )
    """
)

# IBAN (2 lettere, 2 cifre, 11-30 caratteri alfanumerici, spazi opzionali a gruppi di 4)
_IBAN_PATTERN = re.compile(
    r"""(?ix)
    \b
    [A-Z]{2}\d{2}
    (?:
        (?:[ ]?[0-9A-Z]{4}){2,7}(?:[ ]?[0-9A-Z]{1,4})?
      | [0-9A-Z]{11,30}
    )
    \b
    """
)

# Codice Fiscale italiano (16 caratteri: 6L 2C 1L 2C 1L 3C 1L)
_CF_PATTERN = re.compile(
    r"\b[A-Za-z]{6}[0-9]{2}[A-Za-z][0-9]{2}[A-Za-z][0-9]{3}[A-Za-z]\b"
)

# Carte di credito (13-19 cifre, continue o a gruppi con spazi o trattini)
_CARD_PATTERN = re.compile(
    r"""(?x)
    \b
    (?:
        \d{3,6}(?:[ -]\d{3,6}){1,5}
      | \d{13,19}
    )
    \b
    """
)

# Numeri di telefono internazionali (+ o 00 seguito da 8-15 cifre, spazi ammessi)
_INTL_PHONE_PATTERN = re.compile(
    r"""(?x)
    (?<![\w\.:])
    (?:
        \+(?:[ ]*\d){8,15}
      | \b00(?:[ ]*\d){8,15}
    )
    (?![\w:]|\.\d)
    """
)

# Cellulari italiani senza prefisso (3 seguito da 8-9 cifre, spazi ammessi)
_IT_MOBILE_PATTERN = re.compile(
    r"""(?x)
    (?<![\w\.:])
    3(?:[ ]*\d){8,9}
    (?![\w:]|\.\d)
    """
)

# Email
_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# IPv4 candidati
_IPV4_PATTERN = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
)

# Host locali
_LOCAL_HOST_PATTERN = re.compile(
    r"""(?ix)
    \b
    [a-z0-9](?:[a-z0-9-]*[a-z0-9])?
    (?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*
    \.(?:local|lan|internal|home\.arpa|localdomain)
    \b
    """
)

# Tabelle ufficiali di conversione per il Codice Fiscale
_CF_ODD_VALUES: Mapping[str, int] = {
    "0": 1,  "1": 0,  "2": 5,  "3": 7,  "4": 9,  "5": 13, "6": 15, "7": 17, "8": 19, "9": 21,
    "A": 1,  "B": 0,  "C": 5,  "D": 7,  "E": 9,  "F": 13, "G": 15, "H": 17, "I": 19, "J": 21,
    "K": 2,  "L": 4,  "M": 18, "N": 20, "O": 11, "P": 3,  "Q": 6,  "R": 8,  "S": 12, "T": 14,
    "U": 16, "V": 10, "W": 22, "X": 25, "Y": 24, "Z": 23,
}

_CF_EVEN_VALUES: Mapping[str, int] = {
    "0": 0,  "1": 1,  "2": 2,  "3": 3,  "4": 4,  "5": 5,  "6": 6,  "7": 7,  "8": 8,  "9": 9,
    "A": 0,  "B": 1,  "C": 2,  "D": 3,  "E": 4,  "F": 5,  "G": 6,  "H": 7,  "I": 8,  "J": 9,
    "K": 10, "L": 11, "M": 12, "N": 13, "O": 14, "P": 15, "Q": 16, "R": 17, "S": 18, "T": 19,
    "U": 20, "V": 21, "W": 22, "X": 23, "Y": 24, "Z": 25,
}


# --- Algoritmi di controllo ------------------------------------------------------------------------

def _is_valid_iban(raw: str) -> bool:
    """Verifica di validità IBAN con algoritmo ISO 7064 Mod 97-10."""
    clean = raw.replace(" ", "").upper()
    if not (15 <= len(clean) <= 34):
        return False
    if not (clean[:2].isalpha() and clean[2:4].isdigit() and clean[4:].isalnum()):
        return False
    rearranged = clean[4:] + clean[:4]
    num_str = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    try:
        return int(num_str) % 97 == 1
    except ValueError:
        return False


def _is_valid_codice_fiscale(cf: str) -> bool:
    """Controllo carattere di verifica (CIN) del Codice Fiscale italiano."""
    if len(cf) != 16:
        return False
    cf = cf.upper()
    total = 0
    for i in range(15):
        c = cf[i]
        if i % 2 == 0:
            val = _CF_ODD_VALUES.get(c)
        else:
            val = _CF_EVEN_VALUES.get(c)
        if val is None:
            return False
        total += val
    expected_cin = chr(ord("A") + (total % 26))
    return cf[15] == expected_cin


def _is_valid_luhn(raw: str) -> bool:
    """Verifica di validità di un numero di carta con algoritmo di Luhn."""
    digits = [c for c in raw if c.isdigit()]
    if not (13 <= len(digits) <= 19):
        return False
    checksum = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            doubled = d * 2
            checksum += doubled if doubled < 10 else doubled - 9
        else:
            checksum += d
    return checksum % 10 == 0


def _remove_overlaps(findings: List[Finding]) -> List[Finding]:
    """Rimuove sovrapposizioni tra risultati dello stesso tipo, conservando il primo/più esteso."""
    if not findings:
        return []
    sorted_findings = sorted(findings, key=lambda f: (f.start, -(f.end - f.start)))
    result: List[Finding] = []
    last_end = -1
    for f in sorted_findings:
        if f.start >= last_end:
            result.append(f)
            last_end = f.end
    return result


# --- Scansioni per tipo ----------------------------------------------------------------------------

def _scan_secrets(text: str) -> List[Finding]:
    findings: List[Finding] = []

    # 1. Blocchi PEM chiavi private
    for m in _PEM_PRIVATE_KEY_PATTERN.finditer(text):
        findings.append(Finding(kind="secret", label=Label.SECRET, start=m.start(), end=m.end()))

    # 2. Token con prefissi noti
    for m in _KNOWN_TOKENS_PATTERN.finditer(text):
        findings.append(Finding(kind="secret", label=Label.SECRET, start=m.start(), end=m.end()))

    # 3. JWT
    for m in _JWT_PATTERN.finditer(text):
        findings.append(Finding(kind="secret", label=Label.SECRET, start=m.start(), end=m.end()))

    # 4. Valori chiave-valore (password=..., Bearer ...)
    for m in _KV_SECRET_PATTERN.finditer(text):
        if m.group("val_dq") is not None:
            v_start, v_end = m.start("val_dq"), m.end("val_dq")
        elif m.group("val_sq") is not None:
            v_start, v_end = m.start("val_sq"), m.end("val_sq")
        else:
            raw = m.group("val_raw")
            stripped = raw.rstrip(".,;")
            if len(stripped) < 8:
                continue
            v_start = m.start("val_raw")
            v_end = v_start + len(stripped)
        findings.append(Finding(kind="secret", label=Label.SECRET, start=v_start, end=v_end))

    return _remove_overlaps(findings)


def _scan_ibans(text: str) -> List[Finding]:
    findings: List[Finding] = []
    for m in _IBAN_PATTERN.finditer(text):
        if _is_valid_iban(m.group(0)):
            findings.append(Finding(kind="iban", label=Label.PRIVATE, start=m.start(), end=m.end()))
    return _remove_overlaps(findings)


def _scan_codici_fiscali(text: str) -> List[Finding]:
    findings: List[Finding] = []
    for m in _CF_PATTERN.finditer(text):
        if _is_valid_codice_fiscale(m.group(0)):
            findings.append(Finding(kind="codice_fiscale", label=Label.PRIVATE, start=m.start(), end=m.end()))
    return _remove_overlaps(findings)


def _scan_cards(text: str) -> List[Finding]:
    findings: List[Finding] = []
    for m in _CARD_PATTERN.finditer(text):
        if _is_valid_luhn(m.group(0)):
            findings.append(Finding(kind="card", label=Label.PRIVATE, start=m.start(), end=m.end()))
    return _remove_overlaps(findings)


def _scan_phones(text: str) -> List[Finding]:
    findings: List[Finding] = []
    for m in _INTL_PHONE_PATTERN.finditer(text):
        findings.append(Finding(kind="phone", label=Label.PRIVATE, start=m.start(), end=m.end()))
    for m in _IT_MOBILE_PATTERN.finditer(text):
        findings.append(Finding(kind="phone", label=Label.PRIVATE, start=m.start(), end=m.end()))
    return _remove_overlaps(findings)


def _scan_emails(text: str) -> List[Finding]:
    findings: List[Finding] = []
    for m in _EMAIL_PATTERN.finditer(text):
        findings.append(Finding(kind="email", label=Label.PRIVATE, start=m.start(), end=m.end()))
    return _remove_overlaps(findings)


def _scan_persons(text: str, person_names: Iterable[str]) -> List[Finding]:
    valid_names = [n.strip() for n in person_names if n and len(n.strip()) >= 3]
    if not valid_names:
        return []
    valid_names.sort(key=len, reverse=True)
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in valid_names) + r")\b", re.IGNORECASE)
    findings = [Finding(kind="person", label=Label.PRIVATE, start=m.start(), end=m.end()) for m in pattern.finditer(text)]
    return _remove_overlaps(findings)


def _scan_internal_addresses(text: str) -> List[Finding]:
    findings: List[Finding] = []
    for m in _IPV4_PATTERN.finditer(text):
        try:
            ip = ipaddress.IPv4Address(m.group(0))
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                findings.append(Finding(kind="internal_address", label=Label.INTERNAL, start=m.start(), end=m.end()))
        except ValueError:
            continue
    for m in _LOCAL_HOST_PATTERN.finditer(text):
        findings.append(Finding(kind="internal_address", label=Label.INTERNAL, start=m.start(), end=m.end()))
    return _remove_overlaps(findings)


# --- Interfaccia pubblica --------------------------------------------------------------------------

ALL_KINDS = frozenset({"secret", "iban", "codice_fiscale", "card", "phone", "email", "person", "internal_address"})
# Risultati dei tool: solo i tipi che non scattano su output tecnici. Numeri di telefono e carte darebbero falsi
# positivi su byte, uptime e id; gli indirizzi privati sono già nell'etichetta della sorgente (stato dell'infrastruttura)
RESULT_KINDS = frozenset({"secret", "iban", "codice_fiscale", "email", "person"})


def scan(text: str, person_names: Iterable[str] = (), kinds: Optional[Iterable[str]] = None) -> List[Finding]:
    """Trova dati sensibili nel testo, ordinati per posizione e senza sovrapposizioni tra stesso tipo.

    `kinds`: solo questi tipi (default tutti)."""
    if not text:
        return []
    wanted = ALL_KINDS if kinds is None else frozenset(kinds)
    findings: List[Finding] = []
    scanners = (
        ("secret", lambda: _scan_secrets(text)),
        ("iban", lambda: _scan_ibans(text)),
        ("codice_fiscale", lambda: _scan_codici_fiscali(text)),
        ("card", lambda: _scan_cards(text)),
        ("phone", lambda: _scan_phones(text)),
        ("email", lambda: _scan_emails(text)),
        ("person", lambda: _scan_persons(text, person_names)),
        ("internal_address", lambda: _scan_internal_addresses(text)),
    )
    for kind, run in scanners:
        if kind in wanted:
            findings.extend(run())

    findings.sort(key=lambda f: (f.start, f.end, f.kind))
    return findings


def label_for(text: str, person_names: Iterable[str] = (), kinds: Optional[Iterable[str]] = None) -> Tuple[Label, List[str]]:
    """Restituisce l'etichetta più alta trovata (PUBLIC se nulla) e l'elenco ordinato dei tipi senza doppioni."""
    findings = scan(text, person_names, kinds)
    if not findings:
        return Label.PUBLIC, []
    highest_label = max(f.label for f in findings)
    unique_kinds = sorted({f.kind for f in findings})
    return highest_label, unique_kinds


def tag_for(text: str, reason_prefix: str, person_names: Iterable[str] = (), kinds: Optional[Iterable[str]] = None) -> Tag:
    """Restituisce un Tag con l'etichetta di label_for e motivi '{reason_prefix}:{kind}'; PUBLIC_TAG se pulito."""
    label, kinds = label_for(text, person_names, kinds)
    if not kinds:
        return PUBLIC_TAG
    reasons = tuple(f"{reason_prefix}:{k}" for k in kinds)
    return Tag(label=label, untrusted=False, reasons=reasons)


def redact_secrets(text: str) -> Tuple[str, int]:
    """Sostituisce ogni span 'secret' con '[RIMOSSO: segreto]' e restituisce il testo e il numero di sostituzioni."""
    secrets = scan(text, kinds=("secret",))
    if not secrets:
        return text, 0
    # Procediamo da destra verso sinistra per non alterare gli indici di inizio/fine degli span precedenti
    secrets.sort(key=lambda f: f.start, reverse=True)
    res = text
    for s in secrets:
        res = res[:s.start] + "[RIMOSSO: segreto]" + res[s.end:]
    return res, len(secrets)
