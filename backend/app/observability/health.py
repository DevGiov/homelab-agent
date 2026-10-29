"""Campionamento periodico della salute dei servizi esterni e pulizia delle metriche scadute.

Servizi: llama.cpp, SearXNG e ogni server MCP attivo. llama.cpp ha un endpoint di stato e deve
rispondere 200; per gli altri basta una risposta sotto il 500 (un endpoint MCP
interrogato in GET risponde 405/406 ma è raggiungibile).
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx

from app.core.config import settings
from app.mcp.hub import get_mcp_hub
from app.observability import store

logger = logging.getLogger("health_sampler")

PROBE_TIMEOUT_SECONDS = 5.0
PURGE_EVERY_SECONDS = 24 * 3600


@dataclass
class Target:
    service: str
    url: str
    headers: Optional[Dict[str, str]] = None
    require_200: bool = False


def targets() -> List[Target]:
    return [
        Target("llamacpp", f"{settings.llama_cpp_url.rstrip('/')}/models", require_200=True),
        Target("searxng", settings.searxng_url),
        *(Target(f"mcp:{s.id}", s.url) for s in get_mcp_hub().servers() if s.enabled),
    ]


def probe(target: Target) -> Dict[str, object]:
    start = time.monotonic()
    try:
        with httpx.Client(timeout=PROBE_TIMEOUT_SECONDS, follow_redirects=True) as client:
            res = client.get(target.url, headers=target.headers)
        ok = res.status_code == 200 if target.require_200 else res.status_code < 500
        error = None if ok else f"HTTP {res.status_code}"
    except Exception as e:
        ok, error = False, str(e)[:200] or type(e).__name__
    return {"service": target.service, "ok": ok, "latency_ms": int((time.monotonic() - start) * 1000), "error": error}


def sample_once() -> List[Dict[str, object]]:
    probes = targets()
    with ThreadPoolExecutor(max_workers=len(probes)) as pool:
        samples = list(pool.map(probe, probes))
    store.insert_health_samples(samples)
    return samples


class HealthSampler:
    """Thread daemon: un campione ogni `metrics_sample_interval_s` secondi, pulizia una volta al giorno."""

    def __init__(self, interval_s: int):
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_purge = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="health-sampler", daemon=True)
        self._thread.start()
        logger.info(f"Campionamento salute dei servizi ogni {self.interval_s} s")

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                sample_once()
                if time.time() - self._last_purge > PURGE_EVERY_SECONDS:
                    removed = store.purge_older_than(settings.metrics_retention_days)
                    self._last_purge = time.time()
                    if removed:
                        logger.info(f"Metriche più vecchie di {settings.metrics_retention_days} giorni rimosse: {removed} righe")
            except Exception as e:
                logger.warning(f"Campionamento salute non riuscito: {e}")
            self._stop.wait(self.interval_s)


_sampler: Optional[HealthSampler] = None


def start_sampler() -> None:
    global _sampler
    if settings.metrics_sample_interval_s > 0 and _sampler is None:
        _sampler = HealthSampler(settings.metrics_sample_interval_s)
        _sampler.start()


def stop_sampler() -> None:
    global _sampler
    if _sampler is not None:
        _sampler.stop()
        _sampler = None
