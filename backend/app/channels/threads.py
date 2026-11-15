"""Legame tra una chat di un canale e la sua conversazione: `(channel, chat_id) -> thread_id`.

La tabella sta nello stesso database delle conversazioni (come `thread_store`) e si crea all'avvio (`startup.init_storage`).
Il thread è lo stesso che la Web UI apre con `/c/<id>`."""
import sqlite3
import threading
import time

from app.core.config import settings

_lock = threading.Lock()


def _get_conn():
    return sqlite3.connect(settings.checkpoint_db_path)


def init_db() -> None:
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS channel_threads (
                channel TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (channel, chat_id)
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _unused_thread_id(conn: sqlite3.Connection) -> str:
    """`thread_<ms>` come quelli della Web UI; se due chat ne creano uno nello stesso millisecondo, il secondo scala."""
    ms = int(time.time() * 1000)
    while conn.execute("SELECT 1 FROM channel_threads WHERE thread_id = ?", (f"thread_{ms}",)).fetchone():
        ms += 1
    return f"thread_{ms}"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def current_thread(channel: str, chat_id: str) -> str:
    """Il thread corrente della chat; alla prima volta ne crea uno."""
    with _lock:
        conn = _get_conn()
        try:
            row = conn.execute("SELECT thread_id FROM channel_threads WHERE channel = ? AND chat_id = ?",
                               (channel, str(chat_id))).fetchone()
            if row:
                return row[0]
            thread_id = _unused_thread_id(conn)
            conn.execute("INSERT INTO channel_threads (channel, chat_id, thread_id, updated_at) VALUES (?, ?, ?, ?)",
                         (channel, str(chat_id), thread_id, _now()))
            conn.commit()
            return thread_id
        finally:
            conn.close()


def new_thread(channel: str, chat_id: str) -> str:
    """Apre una conversazione nuova per la chat (`/nuova`): la vecchia resta nella Web UI, la chat usa la nuova."""
    with _lock:
        conn = _get_conn()
        try:
            thread_id = _unused_thread_id(conn)
            conn.execute(
                "INSERT INTO channel_threads (channel, chat_id, thread_id, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(channel, chat_id) DO UPDATE SET thread_id = excluded.thread_id, updated_at = excluded.updated_at",
                (channel, str(chat_id), thread_id, _now()))
            conn.commit()
            return thread_id
        finally:
            conn.close()
