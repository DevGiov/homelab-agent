"""Dipendenze condivise dai router: autenticazione via API key e rate limiting."""
import secrets
from typing import Optional

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
limiter = Limiter(key_func=get_remote_address)

# Limite per le route che eseguono l'agente (l'endpoint deve ricevere `request: Request`)
rate_limited = limiter.limit(settings.rate_limit)


def verify_api_key(x_api_key: Optional[str] = Security(api_key_header)):
    expected_key = settings.api_secret_key.strip()
    # compare_digest: il tempo di confronto non rivela quanti caratteri della chiave sono corretti
    if expected_key and not (x_api_key and secrets.compare_digest(x_api_key.encode(), expected_key.encode())):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")
    return x_api_key
