"""Provider gestiti dalla Web UI (docs/providers/PROVIDERS_DESIGN.md, 5.8).

- I provider del `.env` (`llamacpp`, `ollama`, `bedrock`) esistono sempre; la UI ne cambia i campi uno per uno
  (`provider_configs` in `mcp.db`) e un campo non impostato dalla UI prende il valore del `.env`.
- I provider aggiunti dalla UI hanno tutti i campi nella tabella.
- Il livello ammesso si salva con l'indirizzo per cui è stato concesso: con un altro indirizzo il livello effettivo è
  `public` (decisione 8). Alzarlo chiede `confirm`; un provider cloud riceve `private` solo così, mai dal `.env`.
- Le credenziali sono in sola scrittura, cifrate con `secret_box`; senza API_SECRET_KEY non si salvano (decisione 9).
- Salvare ricostruisce il provider e lo sostituisce nel registro (app.llm.providers) sotto un lock: nessun riavvio.
- Ogni modifica va nel log di audit con i nomi dei campi, mai il valore di una credenziale.

Queste funzioni le chiamano solo le API dell'utente (app.api.routes.providers, dietro `verify_api_key`): nessun tool
dell'agente le raggiunge (tests/test_provider_config_api.py lo verifica).
"""
import json
import logging
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

import httpx

from app.core.config import CLOUD_CLEARANCES, Settings, settings
from app.llm import costs, providers
from app.llm.providers import CloudOpenAIProvider, LLMProvider, OllamaProvider, OpenAICompatProvider
from app.security import secret_box
from app.security.flows import USER_LEVELS, Label

logger = logging.getLogger("provider_config")

# Serializza le modifiche della configurazione: lettura, controllo, scrittura e ricostruzione vanno insieme
_LOCK = threading.RLock()

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
# Nomi che non si possono dare a un provider: lo scope del tetto totale, i percorsi fissi delle API, quelli dei
# provider del `.env` che arriveranno (OpenRouter, P4)
RESERVED_NAMES = frozenset({costs.TOTAL_SCOPE, "costs", "settings", "ceilings", "default", "active", "openrouter"})
REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d{1,2}$")


class ProviderConfigError(Exception):
    """Una richiesta che non si può soddisfare: `status` HTTP, `code` per la UI, `message` in italiano per l'utente."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _conflict(code: str, message: str) -> ProviderConfigError:
    return ProviderConfigError(409, code, message)


def _invalid(message: str) -> ProviderConfigError:
    return ProviderConfigError(422, "invalid", message)


# --- Tipi --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str  # url | str | bool | list | region
    required: bool = False
    default: Any = ""


@dataclass(frozen=True)
class KindSpec:
    fields: Tuple[FieldSpec, ...]
    secrets: Tuple[str, ...]
    cloud: bool
    address_field: str  # il campo a cui è legato il livello ammesso

    def field(self, name: str) -> Optional[FieldSpec]:
        return next((f for f in self.fields if f.name == name), None)


KINDS: Dict[str, KindSpec] = {
    "openai_compat": KindSpec((FieldSpec("base_url", "url", True), FieldSpec("default_model", "str"),
                               FieldSpec("llama_cpp", "bool", default=False)), ("api_key",), False, "base_url"),
    "ollama": KindSpec((FieldSpec("base_url", "url", True), FieldSpec("default_model", "str")), (), False, "base_url"),
    "bedrock": KindSpec((FieldSpec("region", "region", True), FieldSpec("models", "list", True, default=())),
                        ("api_key", "access_key_id", "secret_access_key", "session_token"), True, "region"),
    "openai_cloud": KindSpec((FieldSpec("base_url", "url", True), FieldSpec("models", "list", True, default=())),
                             ("api_key",), True, "base_url"),
}


def _normalize_address(value: Any) -> str:
    return str(value or "").strip().rstrip("/").lower()


def _validate_field(spec: FieldSpec, value: Any) -> Any:
    """Il valore pulito di un campo, o ProviderConfigError 422."""
    if spec.type == "bool":
        if not isinstance(value, bool):
            raise _invalid(f"Il campo '{spec.name}' vuole sì o no.")
        return value
    if spec.type == "list":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise _invalid(f"Il campo '{spec.name}' vuole un elenco di nomi.")
        cleaned = [v.strip() for v in value if v.strip()]
        if len(set(cleaned)) != len(cleaned):
            raise _invalid(f"Il campo '{spec.name}' ha un nome ripetuto.")
        return cleaned
    if not isinstance(value, str):
        raise _invalid(f"Il campo '{spec.name}' vuole un testo.")
    value = value.strip()
    if spec.type == "url":
        if not re.match(r"^https?://[^\s/?#]+[^\s?#]*$", value):
            raise _invalid(f"Il campo '{spec.name}' vuole un indirizzo http:// o https://.")
        return value.rstrip("/")
    if spec.type == "region":
        # La regione entra nell'indirizzo di Bedrock: solo la forma di una regione AWS (es. eu-west-1)
        if not REGION_RE.match(value):
            raise _invalid(f"Il campo '{spec.name}' vuole una regione AWS, per esempio eu-west-1.")
        return value
    return value


# --- I provider del .env ------------------------------------------------------------------------------

def _env_value(attr: str) -> Tuple[Any, str]:
    """(valore, origine) di un'impostazione: `env` se il `.env` o l'ambiente la impostano, altrimenti `default`."""
    value = getattr(settings, attr)
    default = Settings.model_fields[attr].default
    source = "env" if (attr in settings.model_fields_set or value != default) and value not in ("", None) else "default"
    return value, source


@dataclass(frozen=True)
class EnvProvider:
    kind: str
    display_name: str
    fields: Callable[[], Dict[str, Tuple[Any, str]]]
    secrets: Callable[[], Dict[str, str]]
    clearance: Callable[[], str]
    defaults: Mapping[str, Any] = field(default_factory=dict)


def _bedrock_env_fields() -> Dict[str, Tuple[Any, str]]:
    region, region_source = _env_value("aws_region")
    models = settings.bedrock_model_list
    return {"region": (region.strip(), region_source), "models": (models, "env" if models else "default")}


ENV_PROVIDERS: Dict[str, EnvProvider] = {
    "llamacpp": EnvProvider(
        "openai_compat", "llama-swap",
        lambda: {"base_url": _env_value("llama_cpp_url"), "default_model": _env_value("default_model")},
        lambda: {}, lambda: settings.llama_cpp_clearance, {"llama_cpp": True}),
    "ollama": EnvProvider(
        "ollama", "Ollama",
        lambda: {"base_url": _env_value("ollama_url"), "default_model": _env_value("default_model")},
        lambda: {}, lambda: settings.ollama_clearance),
    "bedrock": EnvProvider(
        "bedrock", "AWS Bedrock", _bedrock_env_fields,
        lambda: {k: v.strip() for k, v in {"api_key": settings.bedrock_api_key,
                                            "access_key_id": settings.aws_access_key_id,
                                            "secret_access_key": settings.aws_secret_access_key,
                                            "session_token": settings.aws_session_token}.items() if v.strip()},
        lambda: settings.bedrock_clearance),
}


def env_clearance(raw: str, cloud: bool) -> Label:
    """Il livello di un provider dal `.env`: un valore non valido vale `public`; un provider cloud non va oltre
    `internal` (decisione 5: `private` si concede solo dalla UI); `secret` non è un livello di destinazione."""
    label = Label.parse(raw, Label.PUBLIC)
    if cloud and label.key not in CLOUD_CLEARANCES:
        return Label.PUBLIC
    return min(label, Label.PRIVATE)


# --- La tabella ---------------------------------------------------------------------------------------

@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    from pathlib import Path
    path = Path(settings.mcp_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_provider_db() -> None:
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS provider_configs ("
            " name TEXT PRIMARY KEY, kind TEXT NOT NULL, display_name TEXT,"
            " enabled INTEGER,"                    # NULL = attivo (il valore di base)
            " fields_json TEXT NOT NULL DEFAULT '{}',"  # solo i campi impostati dalla UI
            " clearance TEXT, clearance_url TEXT,"  # livello concesso dalla UI e l'indirizzo per cui vale
            " encrypted_secrets TEXT,"              # secret_box.seal; NULL = nessuna credenziale dalla UI
            " secret_names TEXT,"                   # i nomi delle credenziali salvate (JSON), anche se illeggibili
            " updated_at TEXT NOT NULL)"
        )
        conn.execute("CREATE TABLE IF NOT EXISTS provider_settings ("
                     " key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")


@dataclass
class Row:
    """La parte della UI di un provider, con le credenziali in chiaro (solo in memoria)."""
    kind: str
    display_name: Optional[str] = None
    enabled: Optional[bool] = None
    fields: Dict[str, Any] = field(default_factory=dict)
    secrets: Dict[str, str] = field(default_factory=dict)
    secret_names: Tuple[str, ...] = ()
    secrets_unreadable: bool = False
    clearance: Optional[str] = None
    clearance_url: Optional[str] = None


def _read_row(conn: sqlite3.Connection, name: str) -> Optional[Row]:
    r = conn.execute("SELECT * FROM provider_configs WHERE name = ?", (name,)).fetchone()
    if r is None:
        return None
    secrets: Dict[str, str] = {}
    unreadable = False
    names = tuple(json.loads(r["secret_names"] or "[]"))
    if r["encrypted_secrets"]:
        try:
            secrets = secret_box.unseal(r["encrypted_secrets"])
        except secret_box.SecretsUnreadable:
            unreadable = True
            logger.warning(f"Provider '{name}': credenziali illeggibili (API_SECRET_KEY cambiata?)")
    return Row(kind=r["kind"], display_name=r["display_name"], enabled=None if r["enabled"] is None else bool(r["enabled"]),
               fields=json.loads(r["fields_json"] or "{}"), secrets=secrets, secret_names=names,
               secrets_unreadable=unreadable, clearance=r["clearance"], clearance_url=r["clearance_url"])


def _write_row(conn: sqlite3.Connection, name: str, row: Row, sealed: Optional[str]) -> None:
    """Scrive la riga; `sealed` è il testo cifrato delle credenziali già calcolato (None = nessuna)."""
    conn.execute(
        "INSERT INTO provider_configs (name, kind, display_name, enabled, fields_json, clearance, clearance_url,"
        " encrypted_secrets, secret_names, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(name) DO UPDATE SET kind = excluded.kind, display_name = excluded.display_name,"
        " enabled = excluded.enabled, fields_json = excluded.fields_json, clearance = excluded.clearance,"
        " clearance_url = excluded.clearance_url, encrypted_secrets = excluded.encrypted_secrets,"
        " secret_names = excluded.secret_names, updated_at = excluded.updated_at",
        (name, row.kind, row.display_name, None if row.enabled is None else int(row.enabled),
         json.dumps(row.fields, ensure_ascii=False), row.clearance, row.clearance_url, sealed,
         json.dumps(sorted(row.secrets) if not row.secrets_unreadable else list(row.secret_names)),
         datetime.now(timezone.utc).isoformat()))


def _ui_names(conn: sqlite3.Connection) -> List[str]:
    return [r["name"] for r in conn.execute("SELECT name FROM provider_configs ORDER BY name")
            if r["name"] not in ENV_PROVIDERS]


def _read_settings(conn: sqlite3.Connection) -> Dict[str, str]:
    stored = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM provider_settings")}
    return {"default_provider": stored.get("default_provider", providers.DEFAULT_PROVIDER),
            "fallback_provider": stored.get("fallback_provider", providers.DEFAULT_PROVIDER)}


# --- La configurazione risolta --------------------------------------------------------------------------

@dataclass(frozen=True)
class Resolved:
    """Un provider con ogni campo e la sua origine, il livello salvato ed effettivo, cosa manca."""
    name: str
    kind: str
    origin: str  # env | ui
    display_name: str
    enabled: bool
    fields: Dict[str, Tuple[Any, str]]
    secrets: Dict[str, Tuple[str, Optional[str]]]  # nome -> (valore, origine env | ui | None)
    secrets_unreadable: bool
    saved: Label
    granted_for: str

    @property
    def spec(self) -> KindSpec:
        return KINDS[self.kind]

    @property
    def cloud(self) -> bool:
        return self.spec.cloud

    @property
    def address(self) -> str:
        return _normalize_address(self.fields[self.spec.address_field][0])

    @property
    def effective(self) -> Label:
        """Il livello salvato vale solo per l'indirizzo per cui è stato concesso (decisione 8); senza indirizzo, nessuno."""
        if not self.address:
            return Label.PUBLIC
        return self.saved if _normalize_address(self.granted_for) == self.address else Label.PUBLIC

    @property
    def reset_by_address_change(self) -> bool:
        return self.saved > Label.PUBLIC and self.effective == Label.PUBLIC

    def value(self, name: str) -> Any:
        return self.fields[name][0]

    def secret(self, name: str) -> str:
        return self.secrets.get(name, ("", None))[0]

    @property
    def missing(self) -> List[str]:
        missing = [f.name for f in self.spec.fields if f.required and not self.value(f.name)]
        if self.kind == "bedrock" and not (self.secret("api_key")
                                           or (self.secret("access_key_id") and self.secret("secret_access_key"))):
            missing.append("api_key")
        if self.kind == "openai_cloud" and not self.secret("api_key"):
            missing.append("api_key")
        return missing

    @property
    def configured(self) -> bool:
        return not self.missing

    @property
    def unavailable(self) -> Optional[str]:
        """Perché non si può costruire (completa "Il provider 'x' ..."), None se si può."""
        if not self.enabled:
            return providers.DISABLED
        if self.secrets_unreadable:
            return providers.UNREADABLE
        if self.missing:
            return providers.INCOMPLETE
        return None


def resolve(name: str, row: Optional[Row]) -> Resolved:
    """Unisce il `.env` (se il provider ne ha uno) e la riga della UI, campo per campo."""
    env = ENV_PROVIDERS.get(name)
    if env is None and row is None:
        raise ProviderConfigError(404, "not_found", f"Il provider '{name}' non esiste.")
    kind = env.kind if env else row.kind
    spec = KINDS[kind]
    env_fields = env.fields() if env else {}
    defaults = dict(env.defaults) if env else {}
    ui_fields = row.fields if row else {}
    fields: Dict[str, Tuple[Any, str]] = {}
    for f in spec.fields:
        if f.name in ui_fields:
            fields[f.name] = (ui_fields[f.name], "ui")
        elif f.name in env_fields and env_fields[f.name][1] == "env":
            fields[f.name] = env_fields[f.name]
        elif f.name in env_fields:
            fields[f.name] = (env_fields[f.name][0], "default")
        else:
            default = defaults.get(f.name, f.default)
            fields[f.name] = (list(default) if isinstance(default, tuple) else default, "default")
    env_secrets = env.secrets() if env else {}
    ui_secrets = row.secrets if row else {}
    secrets: Dict[str, Tuple[str, Optional[str]]] = {}
    for s in spec.secrets:
        if s in ui_secrets:
            secrets[s] = (ui_secrets[s], "ui")
        elif row and row.secrets_unreadable and s in row.secret_names:
            secrets[s] = ("", "ui")  # c'è, ma non si legge
        elif s in env_secrets:
            secrets[s] = (env_secrets[s], "env")
        else:
            secrets[s] = ("", None)
    if row and row.clearance:
        saved, granted_for = Label.parse(row.clearance, Label.PUBLIC), row.clearance_url or ""
    elif env:
        saved = env_clearance(env.clearance(), spec.cloud)
        address = env_fields.get(spec.address_field, ("", "default"))[0]
        granted_for = address
    else:
        saved, granted_for = Label.PUBLIC, ""
    display_name = (row.display_name if row and row.display_name else None) or (env.display_name if env else name)
    enabled = True if row is None or row.enabled is None else row.enabled
    return Resolved(name, kind, "env" if env else "ui", display_name, enabled, fields, secrets,
                    bool(row and row.secrets_unreadable), saved, granted_for)


def build(r: Resolved) -> Optional[LLMProvider]:
    """Il provider da mettere nel registro; None se non si può usare (`r.unavailable` dice perché)."""
    if r.unavailable:
        return None
    v = {name: value for name, (value, _) in r.fields.items()}
    if r.kind == "openai_compat":
        return OpenAICompatProvider(v["base_url"], v["default_model"], name=r.name, api_key=r.secret("api_key"),
                                    llama_cpp=bool(v["llama_cpp"]))
    if r.kind == "ollama":
        return OllamaProvider(v["base_url"], v["default_model"], name=r.name)
    if r.kind == "bedrock":
        region = v["region"]
        return CloudOpenAIProvider(
            f"https://bedrock-runtime.{region}.amazonaws.com/openai/v1", v["models"], r.name,
            api_key=r.secret("api_key"), access_key=r.secret("access_key_id"), secret_key=r.secret("secret_access_key"),
            session_token=r.secret("session_token"), region=region, service="bedrock")
    return CloudOpenAIProvider(v["base_url"], v["models"], r.name, api_key=r.secret("api_key"))


def _rebuild(name: str, r: Resolved) -> None:
    try:
        provider = build(r)
        reason = r.unavailable
    except Exception as e:  # una configurazione che il costruttore rifiuta: il provider resta fuori dal registro
        logger.warning(f"Provider '{name}' non costruito: {e}")
        provider, reason = None, providers.INCOMPLETE
    providers.replace_provider(name, provider, r.effective, reason)


def _all(conn: sqlite3.Connection) -> List[Tuple[str, Optional[Row]]]:
    return [(name, _read_row(conn, name)) for name in [*ENV_PROVIDERS, *_ui_names(conn)]]


def load_all() -> None:
    """Costruisce tutti i provider dalla configurazione e li mette nel registro (avvio, e test che cambiano il .env)."""
    init_provider_db()
    with _LOCK, _connect() as conn:
        current = _read_settings(conn)
        for name, row in _all(conn):
            _rebuild(name, resolve(name, row))
    providers.set_provider_settings(current["default_provider"], current["fallback_provider"])
    providers.mark_loaded()


# --- Vista per le API --------------------------------------------------------------------------------

def _view(r: Resolved, health: Tuple[Optional[bool], Optional[str]], current: Dict[str, str]) -> Dict[str, Any]:
    """Un provider nella forma di 5.8.6. Mai il valore di una credenziale."""
    healthy, error = health
    return {
        "name": r.name, "display_name": r.display_name, "kind": r.kind, "origin": r.origin, "enabled": r.enabled,
        "configured": r.configured, "missing": r.missing, "cloud": r.cloud,
        "is_default": r.name == current["default_provider"], "is_fallback": r.name == current["fallback_provider"],
        "fields": {name: {"value": value, "source": source} for name, (value, source) in r.fields.items()},
        "secrets": {name: {"set": source is not None, "source": source} for name, (_, source) in r.secrets.items()},
        "secrets_unreadable": r.secrets_unreadable,
        "clearance": {"saved": r.saved.key, "effective": r.effective.key, "granted_for": r.granted_for or None,
                      "reset_by_address_change": r.reset_by_address_change},
        "healthy": healthy, "error": error,
    }


def _health_of(r: Resolved) -> Tuple[Optional[bool], Optional[str]]:
    """(raggiungibile, motivo). None = non provato: il provider non si può costruire."""
    if r.unavailable:
        return None, (f"Il provider '{r.name}' {r.unavailable}" if r.secrets_unreadable else None)
    try:
        ok = providers.get_provider(r.name).health()
    except Exception:
        ok = False
    return ok, None if ok else "non raggiungibile"


def _parallel(fn, items: List[Any]) -> List[Any]:
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(items))) as pool:
        return list(pool.map(fn, items))


def list_view() -> Dict[str, Any]:
    with _connect() as conn:
        resolved = [resolve(name, row) for name, row in _all(conn)]
        current = _read_settings(conn)
    healths = _parallel(_health_of, resolved)
    return {"providers": [_view(r, h, current) for r, h in zip(resolved, healths, strict=True)],
            "default_provider": current["default_provider"], "fallback_provider": current["fallback_provider"],
            "can_store_secrets": secret_box.can_seal()}


def provider_view(name: str) -> Dict[str, Any]:
    with _connect() as conn:
        r = resolve(name, _read_row(conn, name))
        current = _read_settings(conn)
    return _view(r, _health_of(r), current)


def exists(name: str) -> bool:
    if name in ENV_PROVIDERS:
        return True
    with _connect() as conn:
        return conn.execute("SELECT 1 FROM provider_configs WHERE name = ?", (name,)).fetchone() is not None


def catalog() -> Dict[str, Any]:
    """`GET /v1/models`: i provider che si possono usare, ognuno con i suoi modelli, e la scelta predefinita."""
    with _connect() as conn:
        resolved = [resolve(name, row) for name, row in _all(conn)]
    usable = [r for r in resolved if r.name in providers.registered_provider_names()]

    def entry(r: Resolved) -> Dict[str, Any]:
        provider = providers.get_provider(r.name)
        try:
            healthy = provider.health()
        except Exception:
            healthy = False
        try:
            models = provider.list_models_with_details()
        except Exception as e:
            logger.warning(f"Modelli di '{r.name}' non elencati: {e}")
            models = []
        return {"name": r.name, "display_name": r.display_name, "kind": r.kind, "cloud": r.cloud,
                "clearance": r.effective.key, "healthy": healthy, "models": models}

    default_name = providers.default_provider_name()
    try:
        default_model = providers.default_model_name(default_name)
    except Exception:
        default_model = None
    return {"providers": _parallel(entry, usable), "default": {"provider": default_name, "model": default_model}}


# --- Modifiche -----------------------------------------------------------------------------------------

def _audit(action: str, name: str, details: Dict[str, Any]) -> None:
    """Chi (l'utente, dalle API), quando (il timestamp della riga), quali campi. Mai il valore di una credenziale."""
    from app.security import audit_log
    audit_log.log_tool_call(f"provider_{action}", {"provider": name, "by": "user", **details}, registry="providers",
                            result={"ok": True})
    logger.info(f"Provider '{name}': {action} {sorted(details)}")


def _apply(row: Row, spec: KindSpec, fields: Optional[Mapping[str, Any]], secrets: Optional[Mapping[str, Any]],
           display_name: Any = ..., enabled: Any = ...) -> Tuple[Row, Dict[str, Any]]:
    """La riga con le modifiche di una richiesta (null = togli il valore della UI), e cosa è cambiato per l'audit."""
    new = replace(row, fields=dict(row.fields), secrets=dict(row.secrets))
    changed: Dict[str, Any] = {}
    for key, value in (fields or {}).items():
        f = spec.field(key)
        if f is None:
            raise _invalid(f"Campo sconosciuto per questo tipo: '{key}'.")
        if value is None:
            new.fields.pop(key, None)
        else:
            new.fields[key] = _validate_field(f, value)
        changed.setdefault("fields", {})[key] = new.fields.get(key)
    if secrets:
        if new.secrets_unreadable:
            # Le credenziali vecchie non si leggono: quelle nuove le sostituiscono tutte
            new.secrets, new.secrets_unreadable, new.secret_names = {}, False, ()
        for key, value in secrets.items():
            if key not in spec.secrets:
                raise _invalid(f"Credenziale sconosciuta per questo tipo: '{key}'.")
            if value is None:
                new.secrets.pop(key, None)
            elif not isinstance(value, str) or not value.strip():
                raise _invalid(f"La credenziale '{key}' vuole un testo.")
            else:
                new.secrets[key] = value.strip()
            changed.setdefault("secrets", {})[key] = "cleared" if value is None else "set"
    if display_name is not ...:
        if display_name is not None and (not isinstance(display_name, str) or len(display_name.strip()) > 80):
            raise _invalid("Il nome visibile vuole un testo di al massimo 80 caratteri.")
        new.display_name = display_name.strip() if display_name else None
        changed["display_name"] = new.display_name
    if enabled is not ...:
        if enabled is not None and not isinstance(enabled, bool):
            raise _invalid("Il campo 'enabled' vuole sì o no.")
        new.enabled = enabled
        changed["enabled"] = enabled
    return new, changed


def _sealed(row: Row, old_sealed: Optional[str], secrets_touched: bool) -> Optional[str]:
    """Il testo cifrato da salvare. Senza API_SECRET_KEY una credenziale non si salva: 409 `no_secret_key`."""
    if not secrets_touched:
        return old_sealed
    if not row.secrets:
        return None
    if not secret_box.can_seal():
        raise _conflict("no_secret_key", "Le credenziali non si possono salvare senza API_SECRET_KEY nel .env del "
                                         "backend: la chiave di cifratura sarebbe nota. Nulla è stato salvato.")
    return secret_box.seal(row.secrets)


def _check_roles(name: str, r: Resolved, current: Dict[str, str]) -> None:
    """Il provider predefinito e quello di ripiego devono restare utilizzabili; il ripiego, con livello `private`."""
    if name == current["fallback_provider"]:
        if r.unavailable:
            raise _conflict("fallback_provider", f"'{name}' è il provider di ripiego: non si può disattivare, "
                                                 "lasciare incompleto o eliminare. Scegli prima un altro ripiego.")
        if r.effective < Label.PRIVATE:
            raise _conflict("fallback_provider", f"'{name}' è il provider di ripiego e deve poter ricevere dati "
                                                 f"private: il livello resterebbe {r.effective.key}.")
    if name == current["default_provider"] and r.unavailable:
        raise _conflict("default_provider", f"'{name}' è il provider predefinito: non si può disattivare, lasciare "
                                            "incompleto o eliminare. Scegli prima un altro predefinito.")


def _old_sealed(conn: sqlite3.Connection, name: str) -> Optional[str]:
    r = conn.execute("SELECT encrypted_secrets FROM provider_configs WHERE name = ?", (name,)).fetchone()
    return r["encrypted_secrets"] if r else None


def create(name: Any, kind: Any, display_name: Optional[str] = None, fields: Optional[Mapping[str, Any]] = None,
           secrets: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Un provider nuovo dalla UI: nasce attivo e `public`."""
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise _invalid("Il nome vuole minuscole, cifre e '-', fino a 40 caratteri, e non può iniziare con '-'.")
    if name in RESERVED_NAMES:
        raise _conflict("reserved_name", f"Il nome '{name}' è riservato: scegline un altro.")
    if kind not in KINDS:
        raise _invalid(f"Tipo di provider sconosciuto: {kind!r} (openai_compat, ollama, bedrock, openai_cloud).")
    with _LOCK, _connect() as conn:
        if exists(name):
            raise _conflict("name_taken", f"Esiste già un provider di nome '{name}'.")
        row, changed = _apply(Row(kind=kind), KINDS[kind], fields, secrets,
                              display_name=display_name if display_name is not None else ...)
        sealed = _sealed(row, None, bool(row.secrets))
        _write_row(conn, name, row, sealed)
        r = resolve(name, row)
        conn.commit()
        _rebuild(name, r)
    _audit("create", name, {"kind": kind, "fields": sorted((fields or {})), "secrets": sorted(changed.get("secrets", {}))})
    return provider_view(name)


def patch(name: str, *, kind: Any = None, display_name: Any = ..., enabled: Any = ...,
          fields: Optional[Mapping[str, Any]] = None, secrets: Optional[Mapping[str, Any]] = None,
          confirm: bool = False) -> Dict[str, Any]:
    """Modifica campi e credenziali (null = torna al `.env`). Il ripiego che cambia indirizzo vuole `confirm`: il
    livello `private` passa al nuovo indirizzo."""
    with _LOCK, _connect() as conn:
        row = _read_row(conn, name)
        before = resolve(name, row)
        if kind is not None and kind != before.kind:
            raise _conflict("kind_change", f"Il tipo di '{name}' non si cambia: crea un altro provider.")
        new, changed = _apply(row or Row(kind=before.kind), before.spec, fields, secrets, display_name, enabled)
        after = resolve(name, new)
        current = _read_settings(conn)
        if name == current["fallback_provider"] and after.address != before.address and before.effective == Label.PRIVATE:
            if not confirm:
                raise _conflict("confirm_required", f"'{name}' è il provider di ripiego: con l'indirizzo "
                                                    f"{after.address or '(vuoto)'} il livello tornerebbe public. "
                                                    "Conferma per concedergli private al nuovo indirizzo.")
            new.clearance, new.clearance_url = Label.PRIVATE.key, after.address
            after = resolve(name, new)
            changed["clearance"] = {"to": Label.PRIVATE.key, "granted_for": after.address, "confirm": True}
        _check_roles(name, after, current)
        sealed = _sealed(new, _old_sealed(conn, name), "secrets" in changed)
        _write_row(conn, name, new, sealed)
        conn.commit()
        _rebuild(name, after)
    if after.address != before.address:
        changed["address"] = {"from": before.address, "to": after.address}
    _audit("update", name, changed)
    return provider_view(name)


def delete(name: str) -> None:
    """Elimina un provider della UI, con i suoi prezzi e il suo tetto; le metriche passate restano."""
    with _LOCK, _connect() as conn:
        resolve(name, _read_row(conn, name))  # 404 se non esiste
        if name in ENV_PROVIDERS:
            raise _conflict("env_provider", f"'{name}' viene dal .env e tornerebbe al riavvio: disattivalo, oppure "
                                            "ripristina il .env.")
        current = _read_settings(conn)
        if name == current["fallback_provider"]:
            raise _conflict("fallback_provider", f"'{name}' è il provider di ripiego: scegli prima un altro ripiego.")
        if name == current["default_provider"]:
            raise _conflict("default_provider", f"'{name}' è il provider predefinito: scegli prima un altro "
                                                "predefinito.")
        conn.execute("DELETE FROM provider_configs WHERE name = ?", (name,))
        conn.commit()
        costs.delete_provider(name)
        providers.forget_provider(name)
    _audit("delete", name, {})


def reset(name: str) -> Dict[str, Any]:
    """Provider del `.env`: toglie tutte le modifiche della UI (campi, credenziali, livello, attivazione)."""
    with _LOCK, _connect() as conn:
        resolve(name, _read_row(conn, name))
        if name not in ENV_PROVIDERS:
            raise _conflict("not_env_provider", f"'{name}' è stato aggiunto dalla UI: non ha un .env da ripristinare.")
        after = resolve(name, None)
        _check_roles(name, after, _read_settings(conn))
        conn.execute("DELETE FROM provider_configs WHERE name = ?", (name,))
        conn.commit()
        _rebuild(name, after)
    _audit("reset", name, {})
    return provider_view(name)


def set_clearance(name: str, level: str, confirm: bool) -> Dict[str, Any]:
    """Il livello ammesso, legato all'indirizzo di adesso. Alzarlo rispetto al livello effettivo vuole `confirm`."""
    if level not in USER_LEVELS:
        raise _invalid("Livello non valido: public, internal o private.")
    new_level = Label.parse(level)
    with _LOCK, _connect() as conn:
        row = _read_row(conn, name)
        before = resolve(name, row)
        if new_level > before.effective and not confirm:
            raise _conflict("confirm_required", f"Alzare '{name}' a {level} vuol dire mandare dati {level} a "
                                                f"{before.address or '(nessun indirizzo)'}: serve la conferma.")
        new = replace(row or Row(kind=before.kind), clearance=new_level.key, clearance_url=before.address)
        after = resolve(name, new)
        _check_roles(name, after, _read_settings(conn))
        _write_row(conn, name, new, _old_sealed(conn, name))
        conn.commit()
        _rebuild(name, after)
    _audit("clearance", name, {"from": before.effective.key, "to": new_level.key, "granted_for": before.address,
                               "confirm": bool(confirm)})
    return provider_view(name)


def update_settings(default_provider: Optional[str] = None, fallback_provider: Optional[str] = None) -> Dict[str, str]:
    """Provider predefinito e di ripiego: devono esistere ed essere utilizzabili; il ripiego, con livello `private`."""
    with _LOCK, _connect() as conn:
        current = _read_settings(conn)
        for key, name in (("default_provider", default_provider), ("fallback_provider", fallback_provider)):
            if name is None:
                continue
            r = resolve(name, _read_row(conn, name))
            if r.unavailable:
                raise _conflict("provider_disabled", f"Il provider '{name}' {r.unavailable}: non può essere "
                                                     f"{'il predefinito' if key == 'default_provider' else 'il ripiego'}.")
            if key == "fallback_provider" and r.effective < Label.PRIVATE:
                raise _conflict("fallback_provider", f"Il ripiego deve poter ricevere dati private: '{name}' ha "
                                                     f"livello {r.effective.key}.")
            current[key] = name
        now = datetime.now(timezone.utc).isoformat()
        for key, value in current.items():
            conn.execute("INSERT INTO provider_settings (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key)"
                         " DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at", (key, value, now))
        conn.commit()
        providers.set_provider_settings(current["default_provider"], current["fallback_provider"])
    _audit("settings", "*", dict(current))
    return current


# --- Prova connessione -------------------------------------------------------------------------------

def test_connection(name: str, overrides: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Chiama l'indirizzo configurato (o quello inviato, senza salvarlo) e restituisce solo stato, tempo e numero di
    modelli: mai il corpo della risposta."""
    overrides = overrides or {}
    with _connect() as conn:
        row = _read_row(conn, name)
        base = resolve(name, row)
    new, _ = _apply(row or Row(kind=base.kind), base.spec, overrides.get("fields"), overrides.get("secrets"))
    r = resolve(name, replace(new, enabled=True))
    if r.unavailable:
        return {"ok": False, "latency_ms": None, "models_count": None, "error": f"Il provider '{name}' {r.unavailable}"}
    provider = build(r)
    start = time.monotonic()
    try:
        ok, count, error = _probe(r, provider)
    except httpx.TimeoutException:
        ok, count, error = False, None, "timeout"
    except Exception:
        ok, count, error = False, None, "connessione fallita"
    return {"ok": ok, "latency_ms": int((time.monotonic() - start) * 1000), "models_count": count, "error": error}


def _probe(r: Resolved, provider: LLMProvider) -> Tuple[bool, Optional[int], Optional[str]]:
    with httpx.Client(timeout=5.0) as client:
        if r.kind == "ollama":
            res = client.get(f"{provider.base_url}/api/tags")
            count = len(res.json().get("models", [])) if res.status_code == 200 else None
        elif r.kind == "bedrock":
            # L'endpoint non ha un elenco gratuito (GET /models risponde 404): si prova solo che risponde
            res = client.get(provider.base_url)
            ok = res.status_code < 500
            return ok, len(r.value("models")), None if ok else f"HTTP {res.status_code}"
        else:
            res = client.get(f"{provider.base_url}/models", **provider._get_kwargs())
            count = len(res.json().get("data", [])) if res.status_code == 200 else None
    return res.status_code == 200, count, None if res.status_code == 200 else f"HTTP {res.status_code}"
