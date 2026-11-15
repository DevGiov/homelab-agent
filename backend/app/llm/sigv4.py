"""Firma AWS Signature Version 4 di una richiesta HTTP, scritta qui per non aggiungere una libreria (botocore).

Segue l'algoritmo della documentazione IAM (https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_sigv4-create-signed-request.html):
richiesta canonica, stringa da firmare, chiave derivata (data, regione, servizio, `aws4_request`) e firma HMAC-SHA256.
Provata contro due esempi ufficiali (tests/test_sigv4.py).

Cosa copre: percorso doppiamente codificato (come per ogni servizio tranne S3), parametri di query ordinati, header
firmati scelti dal chiamante più `host`, `x-amz-date` e, se c'è, `x-amz-security-token`. Cosa non fa: non normalizza
i segmenti `.` e `..` del percorso, non firma nel parametro di query (presigned URL), non fa streaming del corpo.
"""
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Mapping, Optional
from urllib.parse import parse_qsl, quote, urlsplit

ALGORITHM = "AWS4-HMAC-SHA256"
# Caratteri che la codifica di AWS lascia intatti (RFC 3986, caratteri non riservati)
_UNRESERVED = "-_.~"


@dataclass(frozen=True)
class Signature:
    """Tutti i passi della firma, per poterli confrontare con gli esempi della documentazione."""
    canonical_request: str
    string_to_sign: str
    signature: str
    headers: Dict[str, str]  # da aggiungere alla richiesta (Authorization, x-amz-date, ...)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _canonical_query(query: str) -> str:
    pairs = parse_qsl(query, keep_blank_values=True)
    encoded = sorted((quote(k, safe=_UNRESERVED), quote(v, safe=_UNRESERVED)) for k, v in pairs)
    return "&".join(f"{k}={v}" for k, v in encoded)


def _header_value(value: str) -> str:
    """Spazi iniziali e finali tolti, quelli ripetuti ridotti a uno."""
    return " ".join(str(value).split())


def compute_signature(
    *,
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
    timestamp: datetime,
    session_token: Optional[str] = None,
    sign_content_sha256: bool = True,
) -> Signature:
    """Firma una richiesta.

    `headers`: gli header della richiesta che vanno firmati (tipicamente `content-type`); `host` si ricava dall'URL.
    Ciò che la richiesta invia deve coincidere con ciò che si è firmato. `sign_content_sha256`: aggiunge e firma
    `x-amz-content-sha256` (l'hash del corpo), richiesto da alcuni servizi e innocuo per gli altri.
    `timestamp`: l'istante della firma, passato dal chiamante (nessun orologio qui dentro: i test lo fissano).
    """
    parts = urlsplit(url)
    stamp = timestamp.astimezone(timezone.utc)
    amz_date = stamp.strftime("%Y%m%dT%H%M%SZ")
    date = stamp.strftime("%Y%m%d")
    payload_hash = _sha256_hex(body)

    to_sign = {name.lower(): _header_value(value) for name, value in headers.items()}
    to_sign["host"] = parts.netloc.rpartition("@")[2]
    to_sign["x-amz-date"] = amz_date
    if session_token:
        to_sign["x-amz-security-token"] = session_token
    if sign_content_sha256:
        to_sign["x-amz-content-sha256"] = payload_hash

    names = sorted(to_sign)
    canonical_headers = "".join(f"{name}:{to_sign[name]}\n" for name in names)
    signed_headers = ";".join(names)
    # L'URL porta già il percorso codificato una volta; AWS vuole la codifica doppia (tranne S3)
    canonical_uri = quote(parts.path or "/", safe="/" + _UNRESERVED)
    canonical_request = "\n".join([
        method.upper(), canonical_uri, _canonical_query(parts.query), canonical_headers, signed_headers, payload_hash,
    ])

    scope = f"{date}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([ALGORITHM, amz_date, scope, _sha256_hex(canonical_request.encode("utf-8"))])

    key = _hmac(("AWS4" + secret_key).encode("utf-8"), date)
    for part in (region, service, "aws4_request"):
        key = _hmac(key, part)
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    added = {
        "Authorization": f"{ALGORITHM} Credential={access_key}/{scope}, SignedHeaders={signed_headers}, Signature={signature}",
        "x-amz-date": amz_date,
    }
    if sign_content_sha256:
        added["x-amz-content-sha256"] = payload_hash
    if session_token:
        added["x-amz-security-token"] = session_token
    return Signature(canonical_request, string_to_sign, signature, added)


def sign_request(**kwargs) -> Dict[str, str]:
    """Gli header da aggiungere a una richiesta firmata: Authorization, x-amz-date, x-amz-content-sha256 e, con un
    token di sessione, x-amz-security-token. Argomenti come `compute_signature`."""
    return compute_signature(**kwargs).headers
