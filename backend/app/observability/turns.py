"""Metriche per turno (chat o run di automazione) e per singola chiamata LLM.

`observe_turn` apre il turno in un contextvar: le chiamate LLM fatte nello stesso contesto vi si
sommano, le chiamate ai tool si contano a fine turno dall'audit log (che le registra tutte, anche
quelle eseguite in parallelo su altri thread). Registrare una metrica non fa mai fallire il turno.
"""
import contextvars
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional

from app.observability import store
from app.security import audit_log

logger = logging.getLogger("observability")


@dataclass
class TurnTrace:
    key: str  # thread della chat o run dell'automazione
    source: str  # "chat" | "automation"
    started_at: str = field(default_factory=store.now_iso)
    started: float = field(default_factory=time.monotonic)
    mode: Optional[str] = None
    model: Optional[str] = None
    status: str = "ok"  # ok | error | stopped
    error: Optional[str] = None
    llm_calls: int = 0
    llm_ms: int = 0
    prompt_tokens: int = 0
    cached_tokens: int = 0
    completion_tokens: int = 0


_current_turn: contextvars.ContextVar[Optional[TurnTrace]] = contextvars.ContextVar("current_turn", default=None)


@contextmanager
def observe_turn(key: str, source: str, stopped: Optional[Callable[[], bool]] = None) -> Iterator[TurnTrace]:
    """Misura il blocco come un turno; un'eccezione lo registra come errore e prosegue. `stopped` segnala l'interruzione."""
    trace = TurnTrace(key=key, source=source)
    token = _current_turn.set(trace)
    try:
        yield trace
    except Exception as e:
        trace.status, trace.error = "error", str(e)[:500]
        raise
    finally:
        _current_turn.reset(token)
        if trace.status == "ok" and stopped and stopped():
            trace.status = "stopped"
        _save_turn(trace)


@contextmanager
def capture_llm_calls(key: str) -> Iterator[TurnTrace]:
    """Somma le chiamate LLM del blocco come un turno, senza registrarlo tra i turni (per le valutazioni dei modelli)."""
    trace = TurnTrace(key=key, source="eval")
    token = _current_turn.set(trace)
    try:
        yield trace
    finally:
        _current_turn.reset(token)


def _save_turn(trace: TurnTrace) -> None:
    try:
        tool_calls, tool_errors = audit_log.count_calls(trace.key, trace.started_at)
        store.insert_turn(
            {
                "ts": trace.started_at,
                "turn_key": trace.key,
                "source": trace.source,
                "mode": trace.mode,
                "model": trace.model,
                "status": trace.status,
                "duration_ms": int((time.monotonic() - trace.started) * 1000),
                "llm_ms": trace.llm_ms,
                "llm_calls": trace.llm_calls,
                "prompt_tokens": trace.prompt_tokens,
                "cached_tokens": trace.cached_tokens,
                "completion_tokens": trace.completion_tokens,
                "tool_calls": tool_calls,
                "tool_errors": tool_errors,
                "error": trace.error,
            }
        )
    except Exception as e:
        logger.warning(f"Metriche del turno '{trace.key}' non salvate: {e}")


def record_llm_call(
    *,
    provider: str,
    model: Optional[str],
    duration_ms: int,
    prompt_tokens: int = 0,
    cached_tokens: int = 0,
    completion_tokens: int = 0,
    prompt_ms: Optional[int] = None,
    completion_ms: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    """Registra una chiamata LLM e la somma al turno in corso, se c'è (le chiamate in background non ne hanno)."""
    trace = _current_turn.get()
    if trace is not None:
        trace.llm_calls += 1
        trace.llm_ms += duration_ms
        trace.prompt_tokens += prompt_tokens
        trace.cached_tokens += cached_tokens
        trace.completion_tokens += completion_tokens
        trace.model = model or trace.model
        if error and trace.error is None:
            trace.error = f"LLM: {error}"
    try:
        store.insert_llm_call(
            {
                "turn_key": trace.key if trace else None,
                "provider": provider,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "cached_tokens": cached_tokens,
                "completion_tokens": completion_tokens,
                "prompt_ms": prompt_ms,
                "completion_ms": completion_ms,
                "duration_ms": duration_ms,
                "error": error,
            }
        )
    except Exception as e:
        logger.warning(f"Metriche della chiamata LLM non salvate: {e}")
