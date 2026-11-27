"""Impostazioni modificabili dalla Web UI mentre il servizio gira (docs/settings/RUNTIME_SETTINGS_DESIGN.md, 3).

- **Sezioni dichiarate nel codice** (`Section`, `Field`), nei moduli di `SECTION_MODULES`: ogni campo ha l'attributo di
  `Settings` da cui viene il valore di base, il validatore del valore della UI, e se vale solo dal prossimo riavvio.
  Una sezione può avere credenziali, una funzione `apply` chiamata dopo un salvataggio (sotto il lock) e un controllo
  `confirm` che dice quando un cambio va confermato.
- **Tabella `runtime_settings` in `mcp.db`**: `(section, key, value_json, updated_at)`; una riga assente vale il `.env`.
  Le credenziali di una sezione stanno in una riga sola, `(section, "__secrets__")`, cifrate con `secret_box`: senza
  API_SECRET_KEY non si salvano (409 `no_secret_key`).
- **Lettura**: `get(section, key)` è il valore effettivo (UI, altrimenti `.env`, altrimenti default).
- **Audit**: `settings_update` e `settings_reset` con la sezione e i nomi dei campi, mai i valori delle credenziali.

Le funzioni che cambiano qualcosa (`update`, `reset`) e la vista per le API (`view`) le chiamano solo le API
dell'utente (app.api.routes.settings, dietro `verify_api_key`); il codice che l'agente esegue legge solo con `get` e
`snapshot` (tests/test_runtime_settings_api.py lo verifica).
"""
import importlib
import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

from app.core.config import Settings, settings
from app.security import secret_box

logger = logging.getLogger("runtime_settings")

# I moduli che dichiarano le sezioni (ognuno ha `SECTIONS`). R2 e R3 aggiungono qui i loro
SECTION_MODULES = ("app.channels.config",)

SECRETS_KEY = "__secrets__"

# Serializza le modifiche: lettura, controllo, scrittura e `apply` vanno insieme
_LOCK = threading.RLock()


class SettingsError(Exception):
    """Una richiesta che non si può soddisfare: `status` HTTP, `code` per la UI, `message` in italiano.
    Il messaggio non ripete mai il valore inviato (potrebbe essere una credenziale)."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def invalid(message: str) -> SettingsError:
    return SettingsError(422, "invalid", message)


def _identity(value: Any) -> Any:
    return value


@dataclass(frozen=True)
class Field:
    """Un campo. `attr`: l'attributo di `Settings` con il valore di base (None = solo `default`). `validate`: il valore
    della UI pulito, o `invalid(...)`. `from_env`: normalizza il valore del `.env` (ValueError = valore del `.env` non
    valido: vale `default` e il motivo resta in `Resolved.env_errors`). `default`: un valore, o una funzione delle
    credenziali risolte (`{nome: impostata}`). `restart`: il cambio vale dal prossimo riavvio del backend."""
    key: str
    validate: Callable[[Any], Any]
    attr: Optional[str] = None
    from_env: Callable[[Any], Any] = _identity
    default: Any = None
    restart: bool = False


@dataclass(frozen=True)
class Section:
    """Una sezione. `secrets`: nome della credenziale -> attributo di `Settings` (il valore del `.env`).
    `secret_validators`: il controllo di una credenziale (senza, basta un testo non vuoto). `parts`: le sezioni che le
    API mostrano dentro questa (`GET /v1/settings/channels` contiene `telegram`); una parte non ha una route sua.
    `confirm(prima, dopo)`: il motivo per cui il cambio va confermato, o None. `apply()`: rende effettivo un
    salvataggio. `status(valori)`: lo stato da mostrare accanto ai campi."""
    id: str
    fields: Tuple[Field, ...]
    secrets: Mapping[str, Optional[str]] = field(default_factory=dict)
    secret_validators: Mapping[str, Callable[[str], str]] = field(default_factory=dict)
    parts: Tuple[str, ...] = ()
    confirm: Optional[Callable[["Resolved", "Resolved"], Optional[str]]] = None
    apply: Optional[Callable[[], None]] = None
    status: Optional[Callable[["Resolved"], Dict[str, Any]]] = None

    def field(self, key: str) -> Optional[Field]:
        return next((f for f in self.fields if f.key == key), None)


# --- Registro delle sezioni -----------------------------------------------------------------------

_SECTIONS: Dict[str, Section] = {}
_PART_OF: Dict[str, str] = {}
_loaded = False
_load_lock = threading.Lock()


def _load_sections() -> None:
    global _loaded
    with _load_lock:
        if _loaded:
            return
        for module in SECTION_MODULES:
            for section in importlib.import_module(module).SECTIONS:
                if section.id in _SECTIONS or section.id == SECRETS_KEY:
                    raise ValueError(f"Sezione ripetuta: {section.id}")
                _SECTIONS[section.id] = section
        for section in _SECTIONS.values():
            for part in section.parts:
                _PART_OF[part] = section.id
        _loaded = True


def section(section_id: str) -> Section:
    _load_sections()
    try:
        return _SECTIONS[section_id]
    except KeyError:
        raise SettingsError(404, "not_found", f"La sezione '{section_id}' non esiste.") from None


def _top(section_id: str) -> Section:
    """Una sezione con le sue route: non una parte di un'altra."""
    s = section(section_id)
    if s.id in _PART_OF:
        raise SettingsError(404, "not_found", f"La sezione '{section_id}' non esiste.")
    return s


# --- La tabella ------------------------------------------------------------------------------------

@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = Path(settings.mcp_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS runtime_settings ("
                     " section TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL, updated_at TEXT NOT NULL,"
                     " PRIMARY KEY (section, key))")


@dataclass
class _Row:
    """La parte della UI di una sezione, con le credenziali in chiaro (solo in memoria)."""
    values: Dict[str, Any] = field(default_factory=dict)
    secrets: Dict[str, str] = field(default_factory=dict)
    secret_names: Tuple[str, ...] = ()  # anche quando non si leggono
    unreadable: bool = False


def _read(conn: sqlite3.Connection, s: Section) -> _Row:
    try:
        rows = conn.execute("SELECT key, value_json FROM runtime_settings WHERE section = ?", (s.id,)).fetchall()
    except sqlite3.OperationalError:  # tabella non ancora creata (init_db all'avvio): vale il .env
        return _Row()
    row = _Row()
    for r in rows:
        if r["key"] == SECRETS_KEY:
            stored = json.loads(r["value_json"])
            row.secret_names = tuple(stored.get("names") or ())
            try:
                row.secrets = secret_box.unseal(stored["sealed"])
            except (secret_box.SecretsUnreadable, KeyError, TypeError):
                row.unreadable = True
                logger.warning(f"Impostazioni '{s.id}': credenziali illeggibili (API_SECRET_KEY cambiata?)")
            continue
        f = s.field(r["key"])
        if f is None:
            continue  # un campo che il codice non dichiara più
        try:
            row.values[f.key] = f.validate(json.loads(r["value_json"]))
        except (SettingsError, ValueError):
            logger.warning(f"Impostazioni '{s.id}': il valore salvato di '{f.key}' non vale più, uso il .env")
    return row


# --- Il valore effettivo ---------------------------------------------------------------------------

def _env_value(attr: str) -> Tuple[Any, str]:
    """(valore, origine) di un'impostazione: `env` se il `.env` o l'ambiente la impostano, altrimenti `default`."""
    value = getattr(settings, attr)
    default = Settings.model_fields[attr].default
    source = "env" if (attr in settings.model_fields_set or value != default) and value not in ("", None) else "default"
    return value, source


@dataclass(frozen=True)
class Resolved:
    """Una sezione con ogni campo e la sua origine (`ui`, `env`, `default`) e le credenziali (origine `ui`, `env`, o
    None se non impostata). `env_errors`: i campi il cui valore del `.env` non vale (con il motivo)."""
    section: Section
    values: Dict[str, Tuple[Any, str]]
    secrets: Dict[str, Tuple[str, Optional[str]]]
    secrets_unreadable: bool = False
    env_errors: Dict[str, str] = field(default_factory=dict)

    def value(self, key: str) -> Any:
        return self.values[key][0]

    def secret(self, name: str) -> str:
        """Il valore di una credenziale; "" se non è impostata o non si legge."""
        return self.secrets.get(name, ("", None))[0]


def _resolve(s: Section, row: _Row) -> Resolved:
    secrets: Dict[str, Tuple[str, Optional[str]]] = {}
    for name, attr in s.secrets.items():
        env = str(getattr(settings, attr) or "").strip() if attr else ""
        if name in row.secrets:
            secrets[name] = (row.secrets[name], "ui")
        elif row.unreadable and name in row.secret_names:
            secrets[name] = ("", "ui")  # c'è, ma non si legge
        elif env:
            secrets[name] = (env, "env")
        else:
            secrets[name] = ("", None)
    is_set = {name: source is not None for name, (_, source) in secrets.items()}
    values: Dict[str, Tuple[Any, str]] = {}
    env_errors: Dict[str, str] = {}
    for f in s.fields:
        default = f.default(is_set) if callable(f.default) else f.default
        if f.key in row.values:
            values[f.key] = (row.values[f.key], "ui")
            continue
        if f.attr is None:
            values[f.key] = (default, "default")
            continue
        raw, source = _env_value(f.attr)
        try:
            values[f.key] = (f.from_env(raw), source)
        except ValueError as e:
            env_errors[f.key] = str(e)
            values[f.key] = (default, source)
    return Resolved(s, values, secrets, row.unreadable, env_errors)


def snapshot(section_id: str) -> Resolved:
    """I valori effettivi di una sezione, letti adesso."""
    s = section(section_id)
    with _connect() as conn:
        return _resolve(s, _read(conn, s))


def get(section_id: str, key: str) -> Any:
    """Il valore effettivo di un campo o di una credenziale (UI, altrimenti `.env`, altrimenti default)."""
    r = snapshot(section_id)
    if key in r.values:
        return r.value(key)
    if key in r.secrets:
        return r.secret(key)
    raise KeyError(f"{section_id}.{key}")


# --- Vista per le API ------------------------------------------------------------------------------

def _part_view(r: Resolved) -> Dict[str, Any]:
    out: Dict[str, Any] = {key: {"value": value, "source": source} for key, (value, source) in r.values.items()}
    if r.section.secrets:
        out["secrets"] = {name: {"set": source is not None, "source": source} for name, (_, source) in r.secrets.items()}
    if r.section.status:
        out["status"] = r.section.status(r)
    return out


def view(section_id: str) -> Dict[str, Any]:
    """Una sezione nella forma delle API (design 5), con le sue parti. Mai il valore di una credenziale."""
    s = _top(section_id)
    out = _part_view(snapshot(s.id))
    for part in s.parts:
        out[part] = _part_view(snapshot(part))
    out["can_store_secrets"] = secret_box.can_seal()
    return out


# --- Modifiche -------------------------------------------------------------------------------------

def _audit(action: str, section_id: str, details: Dict[str, Any]) -> None:
    """Chi (l'utente, dalle API), quando (il timestamp della riga), quali campi. Mai un valore di una credenziale."""
    from app.security import audit_log
    audit_log.log_tool_call(f"settings_{action}", {"section": section_id, "by": "user", **details},
                            registry="settings", result={"ok": True})
    logger.info(f"Impostazioni '{section_id}': {action} {details}")


def _changed(s: Section, row: _Row, body: Any) -> Tuple[_Row, List[str], List[str]]:
    """La riga con le modifiche di una richiesta (`null` = togli il valore della UI) e i nomi di campi e credenziali
    toccati."""
    if body is None:
        return row, [], []
    if not isinstance(body, dict) or set(body) - {"fields", "secrets"}:
        raise invalid(f"La sezione '{s.id}' accetta solo 'fields' e 'secrets'.")
    new = _Row(dict(row.values), dict(row.secrets), row.secret_names, row.unreadable)
    fields = {} if body.get("fields") is None else body["fields"]
    secrets = {} if body.get("secrets") is None else body["secrets"]
    if not isinstance(fields, dict) or not isinstance(secrets, dict):
        raise invalid("'fields' e 'secrets' vogliono un oggetto.")
    for key, value in fields.items():
        f = s.field(key)
        if f is None:
            raise invalid(f"Campo sconosciuto in '{s.id}': '{key}'.")
        if value is None:
            new.values.pop(key, None)
        else:
            new.values[key] = f.validate(value)
    if secrets and new.unreadable:
        # Le credenziali vecchie non si leggono: quelle nuove le sostituiscono tutte
        new.secrets, new.secret_names, new.unreadable = {}, (), False
    for name, value in secrets.items():
        if name not in s.secrets:
            raise invalid(f"Credenziale sconosciuta in '{s.id}': '{name}'.")
        if value is None:
            new.secrets.pop(name, None)
        else:
            new.secrets[name] = _validate_secret(s, name, value)
    return new, sorted(fields), sorted(secrets)


def _validate_secret(s: Section, name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise invalid(f"La credenziale '{name}' vuole un testo.")
    check = s.secret_validators.get(name)
    return check(value.strip()) if check else value.strip()


def validate_secret(section_id: str, name: str, value: Any) -> str:
    """Una credenziale di una bozza (per una prova senza salvare), pulita come in un salvataggio."""
    s = section(section_id)
    if name not in s.secrets:
        raise invalid(f"Credenziale sconosciuta in '{s.id}': '{name}'.")
    return _validate_secret(s, name, value)


def _sealed(row: _Row) -> Optional[str]:
    """Il valore della riga `__secrets__` (None = nessuna credenziale). Senza API_SECRET_KEY: 409 `no_secret_key`."""
    if not row.secrets:
        return None
    if not secret_box.can_seal():
        raise SettingsError(409, "no_secret_key", "Le credenziali non si possono salvare senza API_SECRET_KEY nel .env "
                                                  "del backend: la chiave di cifratura sarebbe nota. Nulla è stato salvato.")
    return json.dumps({"names": sorted(row.secrets), "sealed": secret_box.seal(row.secrets)})


def _write(conn: sqlite3.Connection, s: Section, new: _Row, fields: List[str], sealed: Any) -> None:
    """Scrive i campi toccati (assenti dalla riga = cancellati) e, se `sealed` non è `...`, le credenziali."""
    now = datetime.now(timezone.utc).isoformat()

    def upsert(key: str, value_json: str) -> None:
        conn.execute("INSERT INTO runtime_settings (section, key, value_json, updated_at) VALUES (?, ?, ?, ?)"
                     " ON CONFLICT(section, key) DO UPDATE SET value_json = excluded.value_json,"
                     " updated_at = excluded.updated_at", (s.id, key, value_json, now))

    for key in fields:
        if key in new.values:
            upsert(key, json.dumps(new.values[key], ensure_ascii=False))
        else:
            conn.execute("DELETE FROM runtime_settings WHERE section = ? AND key = ?", (s.id, key))
    if sealed is not ...:
        if sealed is None:
            conn.execute("DELETE FROM runtime_settings WHERE section = ? AND key = ?", (s.id, SECRETS_KEY))
        else:
            upsert(SECRETS_KEY, sealed)


def _apply_all(sections: List[Section]) -> None:
    """Rende effettivo il salvataggio; un errore resta nel log (e nello stato della sezione), il salvataggio vale."""
    for s in sections:
        if s.apply is None:
            continue
        try:
            s.apply()
        except Exception as e:
            logger.error(f"Impostazioni '{s.id}': salvate ma non applicate: {type(e).__name__}", exc_info=True)


def update(section_id: str, body: Any) -> Dict[str, Any]:
    """`PATCH /v1/settings/{section}`: `{"fields"?, "secrets"?, <parte>?: {"fields"?, "secrets"?}, "confirm"?}`.

    Tutto o niente: ogni valore si controlla, le conferme e le credenziali si verificano prima di scrivere qualcosa."""
    s = _top(section_id)
    if not isinstance(body, dict):
        raise invalid("Il corpo vuole un oggetto.")
    confirm = body.get("confirm", False)
    if not isinstance(confirm, bool):
        raise invalid("'confirm' vuole sì o no.")
    unknown = set(body) - {"fields", "secrets", "confirm", *s.parts}
    if unknown:
        raise invalid(f"Chiavi sconosciute in '{s.id}': {', '.join(sorted(map(str, unknown)))}.")
    own = {k: body[k] for k in ("fields", "secrets") if k in body}
    targets = [(s, own or None)] + [(section(p), body.get(p)) for p in s.parts]
    with _LOCK, _connect() as conn:
        plans = []
        for target, change in targets:
            row = _read(conn, target)
            new, fields, secrets = _changed(target, row, change)
            if not fields and not secrets:
                continue
            before, after = _resolve(target, row), _resolve(target, new)
            reason = target.confirm(before, after) if target.confirm else None
            if reason and not confirm:
                raise SettingsError(409, "confirm_required", reason)
            sealed = _sealed(new) if secrets else ...
            plans.append((target, new, fields, secrets, sealed, bool(reason)))
        for target, new, fields, _, sealed, _ in plans:
            _write(conn, target, new, fields, sealed)
        conn.commit()
        _apply_all([p[0] for p in plans])
    for target, _, fields, secrets, _, confirmed in plans:
        _audit("update", target.id, {"fields": fields, "secrets": secrets, "confirm": confirmed})
    return view(s.id)


def reset(section_id: str) -> Dict[str, Any]:
    """`POST /v1/settings/{section}/reset`: toglie ogni valore della UI della sezione e delle sue parti (si torna al
    `.env`, che è il valore di base scritto da chi gestisce l'istanza: nessuna conferma)."""
    s = _top(section_id)
    targets = [s] + [section(p) for p in s.parts]
    with _LOCK, _connect() as conn:
        for target in targets:
            conn.execute("DELETE FROM runtime_settings WHERE section = ?", (target.id,))
        conn.commit()
        _apply_all(targets)
    _audit("reset", s.id, {"parts": list(s.parts)})
    return view(s.id)
