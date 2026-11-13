"""Piccoli aiuti per gli schemi SQLite che crescono nel tempo."""
import sqlite3
from typing import Mapping


def ensure_columns(conn: sqlite3.Connection, table: str, columns: Mapping[str, str]) -> None:
    """Aggiunge a `table` le colonne che mancano (nome -> tipo SQL): i database creati prima restano validi."""
    present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, sql_type in columns.items():
        if name not in present:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
