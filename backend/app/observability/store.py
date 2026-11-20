"""Metriche persistenti in `metrics.db`: chiamate LLM, turni (chat e automazioni) e campioni di salute dei servizi."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.core.config import settings
from app.core.sqlite_utils import ensure_columns

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    turn_key TEXT,
    provider TEXT,
    model TEXT,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    prompt_ms INTEGER,
    completion_ms INTEGER,
    duration_ms INTEGER NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_ts ON llm_calls(ts);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    turn_key TEXT NOT NULL,
    source TEXT NOT NULL,
    mode TEXT,
    model TEXT,
    status TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    llm_ms INTEGER NOT NULL DEFAULT 0,
    llm_calls INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    tool_calls INTEGER NOT NULL DEFAULT 0,
    tool_errors INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_turns_ts ON turns(ts);

CREATE TABLE IF NOT EXISTS health_samples (
    ts TEXT NOT NULL,
    service TEXT NOT NULL,
    ok INTEGER NOT NULL,
    latency_ms INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_health_ts ON health_samples(ts, service);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def since_iso(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    Path(settings.metrics_db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.metrics_db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_metrics_db() -> None:
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        # Sensibilità del prompt e destinazione (app.security.flows), per controllare a posteriori dove è andato cosa
        ensure_columns(conn, "llm_calls", {"label": "TEXT", "destination": "TEXT"})
        # Scopo della chiamata (app.llm.roles): le righe scritte prima non lo hanno
        ensure_columns(conn, "llm_calls", {"role": "TEXT"})
        # Costo in dollari col prezzo del momento (app.llm.costs); le righe scritte prima non lo hanno
        ensure_columns(conn, "llm_calls", {"cost_usd": "REAL"})
        # Perché la chiamata è andata al modello locale invece che al provider scelto: label o budget (app.agent.llm_calls)
        ensure_columns(conn, "llm_calls", {"fallback": "TEXT"})


def _insert(table: str, row: Dict[str, Any]) -> None:
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    with _connect() as conn:
        conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(row.values()))


def insert_llm_call(row: Dict[str, Any]) -> None:
    _insert("llm_calls", {"ts": now_iso(), **row})


def insert_turn(row: Dict[str, Any]) -> None:
    _insert("turns", row)


def insert_health_samples(samples: List[Dict[str, Any]]) -> None:
    ts = now_iso()
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO health_samples (ts, service, ok, latency_ms, error) VALUES (?, ?, ?, ?, ?)",
            [(ts, s["service"], int(s["ok"]), s.get("latency_ms"), s.get("error")) for s in samples],
        )


def select(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    with _connect() as conn:
        return [dict(r) for r in conn.execute(query, params)]


def purge_older_than(days: int) -> int:
    """Elimina le metriche più vecchie di `days` giorni; restituisce le righe rimosse. Le chiamate LLM del mese in
    corso (UTC) restano comunque: la spesa del mese, e quindi i tetti, si calcola da lì (app.llm.costs)."""
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    removed = 0
    with _connect() as conn:
        for table in ("llm_calls", "turns", "health_samples"):
            limit = min(cutoff, month_start) if table == "llm_calls" else cutoff
            removed += conn.execute(f"DELETE FROM {table} WHERE ts < ?", (limit,)).rowcount
    return removed


def latest_turns(limit: int, source: Optional[str] = None) -> List[Dict[str, Any]]:
    if source:
        return select("SELECT * FROM turns WHERE source = ? ORDER BY id DESC LIMIT ?", (source, limit))
    return select("SELECT * FROM turns ORDER BY id DESC LIMIT ?", (limit,))
