"""Connessione SQLite al database delle automazioni (WAL, busy_timeout 30 s, foreign key)."""
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from app.core import config

logger = logging.getLogger("automations.db")


def get_db_path() -> str:
    path = config.AUTOMATIONS_DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    target_path = db_path or get_db_path()
    conn = sqlite3.connect(target_path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA synchronous = NORMAL;")
    cursor.execute("PRAGMA busy_timeout = 30000;")
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.close()
    return conn
