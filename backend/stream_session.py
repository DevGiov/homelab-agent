"""Stream Session Manager per il controllo dello streaming e aggregazione metriche.

Gestisce lo stato di stop/pause/resume, il calcolo dei token/secondo,
il buffer di stato live per la riconnessione e il broadcasting multi-subscriber.
"""
import contextvars
import logging
import queue
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class StreamSession:
    def __init__(self, thread_id: str, task: str = "", mode: Optional[str] = None):
        self.thread_id = thread_id
        self.task = task
        self.mode = mode or "chat"
        self.status = "running"  # running, paused, completed, stopped, error
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()  # Inizialmente non in pausa
        self.start_time = time.time()
        self.completed_time: Optional[float] = None
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0

        self.reasoning_content = ""
        self.partial_content = ""
        self.active_tool: Optional[str] = None
        self.plan_steps: Optional[List[str]] = None
        self.plan_structure: Optional[Dict[str, Any]] = None
        self.execution_trace: Optional[List[Dict[str, Any]]] = None
        self.final_response: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None

        self.subscribers: List[queue.Queue] = []
        self._lock = threading.Lock()

    def is_active(self) -> bool:
        """Indica se il processo di elaborazione è attualmente in corso (running o paused)."""
        return self.status in ("running", "paused") and not self.stop_event.is_set()

    def is_stopped(self) -> bool:
        return self.stop_event.is_set() or self.status == "stopped"

    def is_paused(self) -> bool:
        return not self.pause_event.is_set() or self.status == "paused"

    def is_finished(self) -> bool:
        return self.status in ("completed", "stopped", "error")

    def stop(self) -> None:
        self.status = "stopped"
        self.completed_time = time.time()
        self.stop_event.set()
        self.pause_event.set()  # Sblocca se era in attesa su pausa
        self.broadcast({"type": "status", "status": "stopped"})
        logger.info(f"StreamSession[{self.thread_id}]: stop impostato")

    def pause(self) -> None:
        if self.is_active():
            self.status = "paused"
            self.pause_event.clear()
            self.broadcast({"type": "status", "status": "paused"})
            logger.info(f"StreamSession[{self.thread_id}]: pausa impostata")

    def resume(self) -> None:
        if self.is_active():
            self.status = "running"
            self.pause_event.set()
            self.broadcast({"type": "status", "status": "running"})
            logger.info(f"StreamSession[{self.thread_id}]: ripresa impostata")

    def record_metrics(self, m: Optional[Dict[str, Any]]) -> None:
        if not m:
            return
        self.prompt_tokens += m.get("prompt_tokens", 0)
        self.completion_tokens += m.get("completion_tokens", 0)
        self.total_tokens += m.get("total_tokens", (m.get("prompt_tokens", 0) + m.get("completion_tokens", 0)))

    def get_metrics(self) -> Dict[str, Any]:
        end_time = self.completed_time or time.time()
        duration_s = round(end_time - self.start_time, 2)
        tok_per_s = round(self.completion_tokens / max(duration_s, 0.001), 1)
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "duration_s": duration_s,
            "tok_per_s": tok_per_s,
        }

    def put(self, event: Any) -> None:
        """
        Riceve eventi di streaming (interfaccia compatibile con queue.Queue).
        Aggiorna il buffer di stato live e inoltra a tutti i subscriber connessi.
        """
        if event is None:
            if self.status == "running":
                self.status = "completed"
                self.completed_time = time.time()
            self.broadcast(None)
            return

        if isinstance(event, dict):
            ev_type = event.get("type")
            if ev_type == "reasoning":
                self.reasoning_content += event.get("delta", "")
            elif ev_type == "content":
                self.partial_content += event.get("delta", "")
            elif ev_type == "metrics":
                self.record_metrics(event.get("metrics"))
            elif ev_type == "final":
                self.status = "completed"
                self.completed_time = time.time()
                self.final_response = event.get("response")
                if isinstance(self.final_response, dict):
                    if not self.partial_content and self.final_response.get("response"):
                        self.partial_content = self.final_response.get("response")
                    if not self.reasoning_content and self.final_response.get("reasoning_content"):
                        self.reasoning_content = self.final_response.get("reasoning_content")
            elif ev_type == "error":
                self.status = "error"
                self.completed_time = time.time()
                self.error = event.get("error")

        self.broadcast(event)

    def broadcast(self, event: Any) -> None:
        """Inoltra un evento a tutti i subscriber attivi."""
        with self._lock:
            for sub in list(self.subscribers):
                try:
                    sub.put_nowait(event)
                except Exception:
                    pass

    def subscribe(self) -> queue.Queue:
        """Registra un nuovo client subscriber e restituisce la sua coda dedicata."""
        with self._lock:
            sub: queue.Queue = queue.Queue()
            self.subscribers.append(sub)
            return sub

    def unsubscribe(self, sub: queue.Queue) -> None:
        """Rimuove un subscriber disconnesso."""
        with self._lock:
            if sub in self.subscribers:
                self.subscribers.remove(sub)

    def get_snapshot(self) -> Dict[str, Any]:
        """Restituisce lo stato attuale per l'evento di sincronizzazione iniziale ('sync')."""
        return {
            "type": "sync",
            "status": self.status,
            "mode": self.mode,
            "tool_used": self.active_tool,
            "reasoning_content": self.reasoning_content,
            "content": self.partial_content,
            "execution_trace": self.execution_trace,
            "plan_steps": self.plan_steps,
            "plan_structure": self.plan_structure,
            "is_paused": self.is_paused(),
            "metrics": self.get_metrics(),
        }


_active_sessions: Dict[str, StreamSession] = {}
_sessions_lock = threading.Lock()
current_session_var: contextvars.ContextVar[Optional[StreamSession]] = contextvars.ContextVar("current_session_var", default=None)


def create_session(thread_id: str, task: str = "", mode: Optional[str] = None) -> StreamSession:
    with _sessions_lock:
        sess = StreamSession(thread_id, task=task, mode=mode)
        _active_sessions[thread_id] = sess
        current_session_var.set(sess)
        return sess


def get_session(thread_id: str) -> Optional[StreamSession]:
    with _sessions_lock:
        return _active_sessions.get(thread_id)


def remove_session(thread_id: str) -> None:
    with _sessions_lock:
        _active_sessions.pop(thread_id, None)
