"""Dipendenze condivise dai router: autenticazione via API key e rate limiting."""
from typing import Optional

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core import config

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
limiter = Limiter(key_func=get_remote_address)

# Limite per le route che eseguono l'agente (l'endpoint deve ricevere `request: Request`)
rate_limited = limiter.limit(config.RATE_LIMIT)


def verify_api_key(x_api_key: Optional[str] = Security(api_key_header)):
    expected_key = config.API_SECRET_KEY.strip()
    if expected_key:
        if not x_api_key or x_api_key != expected_key:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")
    return x_api_key
