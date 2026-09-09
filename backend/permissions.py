"""Permission & Policy Engine per l'uso dei tool (Human-in-the-Loop).

Gestisce le autorizzazioni dei tool su tre livelli:
- ONE-TIME: approvazione per la singola chiamata/request_id.
- THREAD: autorizzazione in-memory valida per tutti i turni del thread_id specificato.
- ALWAYS: autorizzazione persistente salvata in SQLite (tabella tool_permissions).
"""

import logging
import re
import shlex
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import config

logger = logging.getLogger("permissions")

# Struttura in-memory per permessi di sessione (thread-scoped)
# thread_id -> set di stringhe tipo "tool_name" oppure "tool_name:cmd_prefix"
_SESSION_PERMISSIONS: Dict[str, Set[str]] = {}
_session_lock = threading.Lock()


def _get_conn():
    from pathlib import Path
    db_path = config.CHECKPOINT_DB_PATH
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def init_permissions_db():
    """Inizializza la tabella SQLite per i permessi persistenti (ALWAYS)."""
    try:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tool_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT NOT NULL,
                command_prefix TEXT,
                scope TEXT DEFAULT 'always',
                created_at TEXT NOT NULL,
                created_by TEXT DEFAULT 'user'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_perm_tool ON tool_permissions(tool_name)")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Errore inizializzazione tool_permissions: {e}")


init_permissions_db()


def extract_command_prefix(args: Dict[str, Any]) -> Optional[str]:
    """Estrae un prefisso significativo normalizzato per comandi shell (es. 'ls', 'pwd', 'rm', 'systemctl status')."""
    if not isinstance(args, dict):
        return None
    raw_cmd = args.get("command") or args.get("cmd")
    if not raw_cmd or not isinstance(raw_cmd, str):
        return None

    cleaned = raw_cmd.strip()
    try:
        tokens = shlex.split(cleaned)
    except Exception:
        tokens = cleaned.split()

    if not tokens:
        return None

    first = tokens[0].lower()
    idx = 0
    while idx < len(tokens) and tokens[idx].lower() in ("sudo", "env", "nohup", "timeout"):
        idx += 1
        if idx < len(tokens) and tokens[idx - 1].lower() == "timeout" and tokens[idx].isdigit():
            idx += 1

    if idx >= len(tokens):
        return first

    cmd = tokens[idx].lower()
    if len(tokens) > idx + 1 and cmd in ("systemctl", "apt", "apt-get", "docker", "git", "pct", "qm", "ip", "service"):
        return f"{cmd} {tokens[idx + 1].lower()}"
    return cmd


def normalize_tool_name(tool_name: str) -> str:
    """Rimuove l'eventuale prefisso del namespace MCP (es. 'proxmox-mcp__exec_host_command' -> 'exec_host_command')."""
    if not tool_name:
        return ""
    return re.sub(r'^[a-zA-Z0-9_-]+__', '', tool_name)


def is_tool_level_approved(tool_name: str, thread_id: Optional[str] = None) -> bool:
    """Verifica se il tool stesso è stato autorizzato a livello generale (tool-level) per questo thread o a livello globale."""
    if not tool_name:
        return False
    clean_name = normalize_tool_name(tool_name)
    candidates = [tool_name]
    if clean_name and clean_name != tool_name:
        candidates.append(clean_name)

    if thread_id:
        with _session_lock:
            thread_perms = _SESSION_PERMISSIONS.get(thread_id, set())
            for c_name in candidates:
                if c_name in thread_perms:
                    return True

    try:
        conn = _get_conn()
        c = conn.cursor()
        placeholders = ",".join("?" * len(candidates))
        c.execute(
            f"SELECT 1 FROM tool_permissions WHERE tool_name IN ({placeholders}) AND (command_prefix IS NULL OR command_prefix = '') AND scope = 'always'",
            tuple(candidates)
        )
        row = c.fetchone()
        conn.close()
        if row:
            return True
    except Exception as e:
        logger.warning(f"Errore lettura permessi tool_level: {e}")

    return False


def is_command_preapproved(tool_name: str, cmd_prefix: Optional[str], thread_id: Optional[str] = None) -> bool:
    """Verifica se lo specifico comando/prefisso è nella allow-list del thread o globale (ALWAYS)."""
    if not tool_name or not cmd_prefix:
        return False

    clean_name = normalize_tool_name(tool_name)
    candidates = [tool_name]
    if clean_name and clean_name != tool_name:
        candidates.append(clean_name)

    normalized_prefix = cmd_prefix.strip().lower()

    # 1. Allow-list di sessione (THREAD)
    if thread_id:
        with _session_lock:
            thread_perms = _SESSION_PERMISSIONS.get(thread_id, set())
            for c_name in candidates:
                if f"{c_name}:{normalized_prefix}" in thread_perms:
                    return True

    # 2. Allow-list permanente (ALWAYS in SQLite)
    try:
        conn = _get_conn()
        c = conn.cursor()
        placeholders = ",".join("?" * len(candidates))
        c.execute(
            f"SELECT command_prefix FROM tool_permissions WHERE tool_name IN ({placeholders}) AND scope = 'always'",
            tuple(candidates)
        )
        rows = c.fetchall()
        conn.close()
        for (row_prefix,) in rows:
            if row_prefix and row_prefix.strip().lower() == normalized_prefix:
                return True
    except Exception as e:
        logger.warning(f"Errore lettura command allow-list da DB: {e}")

    return False


def is_tool_preapproved(tool_name: str, args: Dict[str, Any], thread_id: Optional[str] = None) -> bool:
    """
    Verifica se il tool (o il comando specifico se shell) è già stato pre-approvato.
    Per tool shell:
      - se il comando è già nella allow-list specifica (command_prefix) -> True
      - se il tool è approvato a livello generale nel thread e il comando è safe-read -> True
    Per tool non-shell, verifica l'approvazione a livello di tool.
    """
    if not tool_name:
        return False

    clean_name = normalize_tool_name(tool_name)
    cmd_prefix = extract_command_prefix(args)

    if clean_name in ("exec_lxc_command", "exec_host_command"):
        if cmd_prefix and is_command_preapproved(tool_name, cmd_prefix, thread_id):
            return True
        if is_tool_level_approved(tool_name, thread_id):
            raw_cmd = args.get("command") or args.get("cmd") or ""
            try:
                from guardrails import analyze_shell_command_nature
                nature, _, _ = analyze_shell_command_nature(str(raw_cmd))
                if nature == "safe_read":
                    return True
            except Exception:
                pass
        return False

    return is_tool_level_approved(tool_name, thread_id)


def grant_permission(
    tool_name: str,
    scope: str,
    thread_id: Optional[str] = None,
    command_prefix: Optional[str] = None,
    created_by: str = "user"
) -> Dict[str, Any]:
    """Concede un permesso per un dato tool con scope 'thread' o 'always'."""
    scope = scope.lower().strip()
    clean_name = normalize_tool_name(tool_name)
    normalized_prefix = command_prefix.strip().lower() if command_prefix else None

    if scope in ("thread", "session") and thread_id:
        with _session_lock:
            if thread_id not in _SESSION_PERMISSIONS:
                _SESSION_PERMISSIONS[thread_id] = set()
            
            # Se è presente un prefisso comando, salva il permesso granulare per comando
            if normalized_prefix:
                _SESSION_PERMISSIONS[thread_id].add(f"{tool_name}:{normalized_prefix}")
                if clean_name and clean_name != tool_name:
                    _SESSION_PERMISSIONS[thread_id].add(f"{clean_name}:{normalized_prefix}")
            
            # Salva anche il permesso a livello tool (per sbloccare comandi safe-read)
            _SESSION_PERMISSIONS[thread_id].add(tool_name)
            if clean_name and clean_name != tool_name:
                _SESSION_PERMISSIONS[thread_id].add(clean_name)

        logger.info(f"Permesso concesso: tool='{tool_name}' scope=thread thread_id='{thread_id}' prefix='{normalized_prefix}'")
        return {"tool_name": tool_name, "scope": "thread", "thread_id": thread_id, "command_prefix": normalized_prefix}

    elif scope in ("always", "global"):
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            conn = _get_conn()
            c = conn.cursor()
            canonical_name = clean_name or tool_name
            c.execute("""
                INSERT INTO tool_permissions (tool_name, command_prefix, scope, created_at, created_by)
                VALUES (?, ?, 'always', ?, ?)
            """, (canonical_name, normalized_prefix, now_iso, created_by))
            perm_id = c.lastrowid
            conn.commit()
            conn.close()
            logger.info(f"Permesso persistente salvato: id={perm_id} tool='{canonical_name}' prefix='{normalized_prefix}'")
            return {
                "id": perm_id,
                "tool_name": canonical_name,
                "scope": "always",
                "command_prefix": normalized_prefix,
                "created_at": now_iso
            }
        except Exception as e:
            logger.error(f"Errore salvataggio permesso persistente: {e}")
            return {"error": str(e)}

    return {"error": f"Parametri non validi per scope '{scope}'"}


def list_granted_permissions(thread_id: Optional[str] = None) -> Dict[str, Any]:
    """Elenca tutti i permessi persistenti (ALWAYS) e quelli attivi per il thread specificato."""
    always_list = []
    try:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("SELECT id, tool_name, command_prefix, scope, created_at, created_by FROM tool_permissions ORDER BY id DESC")
        for row in c.fetchall():
            always_list.append({
                "id": row[0],
                "tool_name": row[1],
                "command_prefix": row[2],
                "scope": row[3],
                "created_at": row[4],
                "created_by": row[5],
            })
        conn.close()
    except Exception as e:
        logger.warning(f"Errore lettura permessi da DB: {e}")

    thread_list = []
    session_map: Dict[str, list] = {}
    with _session_lock:
        for t_id, keys in _SESSION_PERMISSIONS.items():
            if keys:
                session_map[t_id] = sorted(list(keys))
        if thread_id:
            keys = list(_SESSION_PERMISSIONS.get(thread_id, set()))
            for k in keys:
                parts = k.split(":", 1)
                thread_list.append({
                    "tool_name": parts[0],
                    "command_prefix": parts[1] if len(parts) > 1 else None,
                    "scope": "thread",
                    "thread_id": thread_id,
                })

    return {
        "status": "ok",
        "always": always_list,
        "thread": thread_list,
        "session": session_map,
    }


def revoke_permission(permission_id: int) -> bool:
    """Revoca un permesso persistente per ID."""
    try:
        conn = _get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM tool_permissions WHERE id = ?", (permission_id,))
        deleted = c.rowcount > 0
        conn.commit()
        conn.close()
        if deleted:
            logger.info(f"Permesso persistente {permission_id} revocato")
        return deleted
    except Exception as e:
        logger.error(f"Errore revoca permesso {permission_id}: {e}")
        return False


def revoke_thread_permissions(thread_id: str) -> None:
    """Azzera tutti i permessi temporanei associati a un thread."""
    with _session_lock:
        if thread_id in _SESSION_PERMISSIONS:
            del _SESSION_PERMISSIONS[thread_id]
            logger.info(f"Permessi di sessione azzerati per thread '{thread_id}'")
