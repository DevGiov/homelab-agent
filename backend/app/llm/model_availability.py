"""Quali modelli si possono usare secondo il watchdog (WATCHDOG_URL).

Il watchdog non deve mai poter fermare l'agent: se non risponde, o non conosce un modello, non c'è alcuna restrizione.
"""
import logging
import threading
import time
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

TIMEOUT_S = 1.0
# list_models_with_details è chiamato anche ogni secondo durante un caricamento. Vale anche per gli errori:
# con il watchdog spento non si aspetta il timeout a ogni chiamata
CACHE_TTL_S = 5.0

_lock = threading.Lock()
_cache: Dict[str, Dict[str, Any]] = {}
_cache_expires_at = 0.0
_was_reachable = True


def _fetch() -> Dict[str, Dict[str, Any]]:
    global _was_reachable
    if not settings.watchdog_url:
        return {}
    try:
        with httpx.Client(timeout=TIMEOUT_S) as client:
            res = client.get(f"{settings.watchdog_url.rstrip('/')}/v1/availability")
        res.raise_for_status()
        models = res.json().get("models")
        _was_reachable = True
        return models if isinstance(models, dict) else {}
    except Exception as e:
        if _was_reachable:
            logger.warning(f"Watchdog non raggiungibile, nessuna restrizione sui modelli: {e}")
        _was_reachable = False
        return {}


def model_verdicts() -> Dict[str, Dict[str, Any]]:
    """Verdetti per modello, dalla cache se ancora validi."""
    global _cache, _cache_expires_at
    with _lock:
        now = time.monotonic()
        if now >= _cache_expires_at:
            _cache = _fetch()
            _cache_expires_at = now + CACHE_TTL_S
        return _cache


def clear_cache() -> None:
    global _cache, _cache_expires_at
    with _lock:
        _cache = {}
        _cache_expires_at = 0.0


def availability_fields(model: str) -> Dict[str, Any]:
    """Campi aggiunti ai dettagli di un modello. Il motivo c'è solo se il modello è bloccato o lo sarebbe."""
    verdict = model_verdicts().get(model) or {}
    return {
        "available": verdict.get("available", True) is not False,
        "would_block": bool(verdict.get("would_block")),
        "availability_note": verdict.get("reason"),
        "memory_class": verdict.get("memory_class"),
    }


def unavailable_reason(model: Optional[str]) -> Optional[str]:
    """Motivo per cui il modello non si può usare ora, o None. La simulazione non blocca."""
    if not model:
        return None
    verdict = model_verdicts().get(model) or {}
    if verdict.get("available", True) is not False:
        return None
    return verdict.get("reason") or "Modello non disponibile secondo il watchdog"
