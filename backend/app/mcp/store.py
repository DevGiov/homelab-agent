"""Server MCP registrati dalla UI e impostazioni per tool, in `mcp.db`.

Il server predefinito (MetaMCP) viene dal `.env` e non è salvato qui: vedi `builtin_server()`.
Il token di un server è cifrato a riposo con `secret_box`.
"""
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Literal, Optional

from app.core.config import settings
from app.security.secret_box import decrypt_secrets, encrypt_secrets

BUILTIN_SERVER_ID = "metamcp"
SERVER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")

ToolRisk = Literal["auto", "view", "confirm", "blocked"]
TOOL_RISKS = ("auto", "view", "confirm", "blocked")


@dataclass
class MCPServer:
    id: str
    name: str
    url: str
    token: str = ""
    enabled: bool = True
    # MetaMCP espone già i tool con il prefisso del proprio server (proxmox-mcp__...): non se ne aggiunge un altro
    builtin: bool = False

    def tool_name(self, remote_name: str) -> str:
        """Nome del tool nel catalogo dell'agente: `<server>__<tool>`, invariato per il server predefinito."""
        return remote_name if self.builtin else f"{self.id}__{remote_name}"


@dataclass
class ToolSetting:
    enabled: bool = True
    risk: ToolRisk = "auto"


def builtin_server() -> MCPServer:
    return MCPServer(
        id=BUILTIN_SERVER_ID,
        name="MetaMCP",
        url=settings.metamcp_url,
        token=settings.metamcp_api_key,
        builtin=True,
    )


_lock = threading.Lock()
_tool_settings: Optional[Dict[str, ToolSetting]] = None


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Connessione con schema garantito; commit all'uscita senza errori, chiusura sempre."""
    path = settings.mcp_db_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS mcp_servers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            encrypted_token TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mcp_tool_settings (
            tool_name TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            risk TEXT NOT NULL DEFAULT 'auto' CHECK (risk IN ('auto', 'view', 'confirm', 'blocked'))
        );
        """
    )
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_server(row: sqlite3.Row) -> MCPServer:
    return MCPServer(
        id=row["id"],
        name=row["name"],
        url=row["url"],
        token=decrypt_secrets(row["encrypted_token"]).get("token", ""),
        enabled=bool(row["enabled"]),
    )


# --- Server ---------------------------------------------------------------------

def list_servers() -> List[MCPServer]:
    """Server registrati dalla UI (il predefinito escluso), in ordine di creazione."""
    with _connect() as conn:
        return [_row_to_server(r) for r in conn.execute("SELECT * FROM mcp_servers ORDER BY created_at")]


def get_server(server_id: str) -> Optional[MCPServer]:
    if server_id == BUILTIN_SERVER_ID:
        return builtin_server()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
    return _row_to_server(row) if row else None


def save_server(server: MCPServer) -> MCPServer:
    """Crea o aggiorna un server; il predefinito non è modificabile."""
    if server.id == BUILTIN_SERVER_ID:
        raise ValueError("Il server predefinito si configura dal .env (METAMCP_URL, METAMCP_API_KEY).")
    if not SERVER_ID_PATTERN.match(server.id):
        raise ValueError("Id non valido: 2-31 caratteri tra minuscole, cifre e '-', iniziando con lettera o cifra.")
    now = datetime.now(timezone.utc).isoformat()
    token = encrypt_secrets({"token": server.token}) if server.token else "{}"
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO mcp_servers (id, name, url, encrypted_token, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name, url = excluded.url, encrypted_token = excluded.encrypted_token,
                enabled = excluded.enabled, updated_at = excluded.updated_at
            """,
            (server.id, server.name, server.url, token, int(server.enabled), now, now),
        )
    return server


def delete_server(server_id: str) -> bool:
    if server_id == BUILTIN_SERVER_ID:
        raise ValueError("Il server predefinito non si può eliminare.")
    with _connect() as conn:
        deleted = conn.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,)).rowcount > 0
        # Le impostazioni dei suoi tool non servono più
        conn.execute("DELETE FROM mcp_tool_settings WHERE tool_name LIKE ? ESCAPE '\\'", (f"{server_id}\\_\\_%",))
    _invalidate_tool_settings()
    return deleted


# --- Impostazioni per tool -----------------------------------------------------------

def tool_settings() -> Dict[str, ToolSetting]:
    """Impostazioni dei tool modificate dall'utente; i tool assenti valgono `ToolSetting()`. Tenute in memoria."""
    global _tool_settings
    with _lock:
        if _tool_settings is None:
            with _connect() as conn:
                _tool_settings = {
                    r["tool_name"]: ToolSetting(enabled=bool(r["enabled"]), risk=r["risk"])
                    for r in conn.execute("SELECT * FROM mcp_tool_settings")
                }
        return dict(_tool_settings)


def tool_setting(tool_name: str) -> ToolSetting:
    return tool_settings().get(tool_name, ToolSetting())


def save_tool_setting(tool_name: str, setting: ToolSetting) -> ToolSetting:
    if setting.risk not in TOOL_RISKS:
        raise ValueError(f"Rischio non valido: {setting.risk}")
    with _connect() as conn:
        if setting == ToolSetting():
            conn.execute("DELETE FROM mcp_tool_settings WHERE tool_name = ?", (tool_name,))
        else:
            conn.execute(
                "INSERT INTO mcp_tool_settings (tool_name, enabled, risk) VALUES (?, ?, ?) "
                "ON CONFLICT(tool_name) DO UPDATE SET enabled = excluded.enabled, risk = excluded.risk",
                (tool_name, int(setting.enabled), setting.risk),
            )
    _invalidate_tool_settings()
    return setting


def _invalidate_tool_settings() -> None:
    global _tool_settings
    with _lock:
        _tool_settings = None
