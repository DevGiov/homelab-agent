"""Stream Session Manager per il controllo dello streaming e aggregazione metriche.

Gestisce lo stato di stop/pause/resume e il calcolo dei token/secondo per thread.
"""
import contextvars
import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class StreamSession:
    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()  # Inizialmente non in pausa
        self.start_time = time.time()
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

    def is_stopped(self) -> bool:
        return self.stop_event.is_set()

    def is_paused(self) -> bool:
        return not self.pause_event.is_set()

    def stop(self) -> None:
        self.stop_event.set()
        self.pause_event.set()  # Sblocca se era in attesa su pausa
        logger.info(f"StreamSession[{self.thread_id}]: stop impostato")

    def pause(self) -> None:
        self.pause_event.clear()
        logger.info(f"StreamSession[{self.thread_id}]: pausa impostata")

    def resume(self) -> None:
        self.pause_event.set()
        logger.info(f"StreamSession[{self.thread_id}]: ripresa impostata")

    def record_metrics(self, m: Optional[Dict[str, Any]]) -> None:
        if not m:
            return
        self.prompt_tokens += m.get("prompt_tokens", 0)
        self.completion_tokens += m.get("completion_tokens", 0)
        self.total_tokens += m.get("total_tokens", (m.get("prompt_tokens", 0) + m.get("completion_tokens", 0)))

    def get_metrics(self) -> Dict[str, Any]:
        duration_s = round(time.time() - self.start_time, 2)
        tok_per_s = round(self.completion_tokens / max(duration_s, 0.001), 1)
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "duration_s": duration_s,
            "tok_per_s": tok_per_s,
        }


_active_sessions: Dict[str, StreamSession] = {}
_sessions_lock = threading.Lock()
current_session_var: contextvars.ContextVar[Optional[StreamSession]] = contextvars.ContextVar("current_session_var", default=None)


def create_session(thread_id: str) -> StreamSession:
    with _sessions_lock:
        sess = StreamSession(thread_id)
        _active_sessions[thread_id] = sess
        current_session_var.set(sess)
        return sess


def get_session(thread_id: str) -> Optional[StreamSession]:
    with _sessions_lock:
        return _active_sessions.get(thread_id)


def remove_session(thread_id: str) -> None:
    with _sessions_lock:
        _active_sessions.pop(thread_id, None)
