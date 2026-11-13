"""Sensibilità dei dati: etichette, destinazioni e il controllo `can_flow`.

Design: docs/sensitivity/SENSITIVITY_DESIGN.md. In breve:

- ogni dato che entra nel contesto di un modello ha un'etichetta (`Label`) e un attributo di fiducia; insieme, e con
  i motivi, formano un `Tag`. I tag si combinano con `join`: vince l'etichetta più alta;
- ciò che una chiamata a un modello scrive (risposta, argomenti di un tool, query) ha il tag del suo prompt;
- ogni destinazione fuori dal processo ha un livello ammesso (`Destination.clearance`): `can_flow` dice se un tag
  può andarci. È codice ordinario, fuori dal modello.

Le etichette delle sorgenti e i livelli delle destinazioni stanno qui, in un posto solo. Un tool del catalogo senza
regola esplicita è trattato come un server MCP non classificato: risultati `private`, argomenti ammessi solo se
`public` (decisione 5 del design: parte dal più stretto, lo classifica chi lo aggiunge).
"""
from __future__ import annotations

import contextvars
import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger("flows")

MAX_REASONS = 12


class Label(IntEnum):
    PUBLIC = 0     # potrebbe stare online
    INTERNAL = 1   # mio, ma può andare a un provider che ho scelto
    PRIVATE = 2    # solo modelli locali
    SECRET = 3     # nessun modello

    @property
    def key(self) -> str:
        return self.name.lower()

    @classmethod
    def parse(cls, value: Any, default: Optional["Label"] = None) -> "Label":
        """Da nome ('private'), numero o Label. Un valore non riconosciuto dà `default`, o ValueError senza default."""
        if isinstance(value, Label):
            return value
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 3:
            return cls(value)
        if isinstance(value, str) and value.strip().upper() in cls.__members__:
            return cls[value.strip().upper()]
        if default is not None:
            return default
        raise ValueError(f"Etichetta di sensibilità non valida: {value!r} (public, internal, private, secret)")


# Etichette che l'utente può scegliere per una conversazione o per un documento: `secret` no, lo decide il codice
USER_LEVELS = ("public", "internal", "private")


@dataclass(frozen=True)
class Tag:
    label: Label = Label.PUBLIC
    untrusted: bool = False
    reasons: Tuple[str, ...] = ()

    def raised(self, label: Label, reason: str, untrusted: bool = False) -> "Tag":
        return join(self, Tag(label, untrusted, (reason,)))

    def to_dict(self) -> Dict[str, Any]:
        return {"label": self.label.key, "untrusted": self.untrusted, "reasons": list(self.reasons)}

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "Tag":
        if not data:
            return PUBLIC_TAG
        if isinstance(data, Tag):
            return data
        return cls(Label.parse(data.get("label"), Label.PUBLIC), bool(data.get("untrusted")),
                   tuple(str(r) for r in (data.get("reasons") or ())))


PUBLIC_TAG = Tag()
# Chiamate che leggono conversazioni e memoria per mantenerla (consolidamento, entità, deduplica): private
MEMORY_MAINTENANCE_TAG = Tag(Label.PRIVATE, False, ("memoria:manutenzione",))


def join(*tags: Optional[Tag]) -> Tag:
    """Etichetta più alta, non attendibile se lo è una parte, motivi dell'etichetta risultante (in ordine, senza doppioni).

    Accetta anche i dict di `Tag.to_dict` (stato del grafo e checkpoint sono JSON)."""
    parts = [t if isinstance(t, Tag) else Tag.from_dict(t) for t in tags if t]
    if not parts:
        return PUBLIC_TAG
    label = max(t.label for t in parts)
    reasons: List[str] = []
    for t in parts:
        # Contano i motivi di chi porta l'etichetta finale, e quelli della non attendibilità
        for r in t.reasons:
            if r not in reasons and (t.label == label or r.startswith("untrusted:")):
                reasons.append(r)
    return Tag(label, any(t.untrusted for t in parts), tuple(reasons[:MAX_REASONS]))


def tag_of(label: Any, reason: str, untrusted: bool = False) -> Tag:
    return Tag(Label.parse(label, Label.PRIVATE), untrusted, (reason,) + ((f"untrusted:{reason}",) if untrusted else ()))


# --- Destinazioni ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Destination:
    id: str          # "provider:llamacpp", "search:web", "http:example.org", "mcp:proxmox-mcp", "sandbox:code"
    kind: str        # model | search | http | mcp | sandbox | channel
    clearance: Label  # l'etichetta più alta che può ricevere


@dataclass(frozen=True)
class Decision:
    allowed: bool
    tag: Tag
    destination: Destination
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"allowed": self.allowed, "destination": self.destination.id, "clearance": self.destination.clearance.key,
                "label": self.tag.label.key, "reason": self.reason}


class FlowDenied(RuntimeError):
    def __init__(self, decision: Decision):
        super().__init__(decision.reason)
        self.decision = decision


def can_flow(tag: Tag, dest: Destination) -> Decision:
    """Pura e senza effetti. Un segreto non va da nessuna parte, il resto fino al livello ammesso."""
    if tag.label == Label.SECRET:
        return Decision(False, tag, dest, f"Contiene un segreto: non può andare a {dest.id}.")
    if tag.label <= dest.clearance:
        return Decision(True, tag, dest)
    why = ", ".join(r for r in tag.reasons if not r.startswith("untrusted:")) or "contenuto della conversazione"
    return Decision(False, tag, dest,
                    f"Dati {tag.label.key} ({why}) verso {dest.id}, che ammette al massimo {dest.clearance.key}.")


def provider_destination(provider_name: str) -> Destination:
    """Il livello ammesso di un provider viene da un'impostazione esplicita, non dall'indirizzo: un indirizzo di rete
    locale può essere un proxy verso un servizio cloud."""
    raw = {"llamacpp": settings.llama_cpp_clearance, "ollama": settings.ollama_clearance}.get(provider_name, "internal")
    return Destination(f"provider:{provider_name}", "model", Label.parse(raw, Label.INTERNAL))


SEARCH_DESTINATION = Destination("search:web", "search", Label.PUBLIC)
SANDBOX_DESTINATION = Destination("sandbox:code", "sandbox", Label.PRIVATE)  # microVM Firecracker: rete da verificare


# --- Regole dei tool -------------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolFlow:
    """Come un tool tratta i dati: etichetta dei risultati, se sono non attendibili, dove vanno gli argomenti.

    `exit`: None se gli argomenti restano nel processo (memoria, database locali), altrimenti il tipo di destinazione;
    "url" la ricava dall'host dell'argomento `url`/`image_path_or_url`/`feed_url`."""
    result: Label
    untrusted: bool = False
    exit: Optional[str] = None
    note: str = ""


_TOOL_FLOWS: Dict[str, ToolFlow] = {
    # Rete
    "web_search": ToolFlow(Label.PUBLIC, True, "search"),
    "http_get": ToolFlow(Label.PUBLIC, True, "url"),
    "inspect_image": ToolFlow(Label.PUBLIC, True, "url", "un'immagine locale non esce: solo un URL è un'uscita"),
    "calendar_import_feed": ToolFlow(Label.PRIVATE, True, "url"),
    # Memoria e conoscenza
    "recall_memory": ToolFlow(Label.PRIVATE),
    "search_conversations": ToolFlow(Label.PRIVATE),
    "propose_procedure": ToolFlow(Label.INTERNAL),
    "knowledge_search": ToolFlow(Label.INTERNAL, note="l'etichetta vera è quella dei documenti trovati"),
    # Posta e calendario: privati; ciò che arriva da altri non è attendibile
    "email_fetch_unread": ToolFlow(Label.PRIVATE, True),
    "email_create_draft": ToolFlow(Label.PRIVATE),
    "save_briefing_artifact": ToolFlow(Label.PUBLIC),
    "calendar_list_calendars": ToolFlow(Label.PRIVATE),
    "calendar_list_events": ToolFlow(Label.PRIVATE, True),
    "calendar_get_event": ToolFlow(Label.PRIVATE, True),
    "calendar_check_availability": ToolFlow(Label.PRIVATE),
    "calendar_create_event": ToolFlow(Label.PRIVATE),
    "calendar_update_event": ToolFlow(Label.PRIVATE),
    "calendar_delete_event": ToolFlow(Label.PRIVATE),
    "calendar_create_calendar": ToolFlow(Label.PRIVATE),
    "calendar_update_calendar": ToolFlow(Label.PRIVATE),
    "calendar_delete_calendar": ToolFlow(Label.PRIVATE),
    # Automazioni e artefatti: stato del sistema
    "list_automation_templates": ToolFlow(Label.PUBLIC),
    "list_automations": ToolFlow(Label.INTERNAL),
    "get_automation_details": ToolFlow(Label.INTERNAL),
    "create_automation_from_template": ToolFlow(Label.INTERNAL),
    "create_custom_automation": ToolFlow(Label.INTERNAL),
    "update_automation": ToolFlow(Label.INTERNAL),
    "trigger_automation_run": ToolFlow(Label.INTERNAL),
    "save_artifact": ToolFlow(Label.PUBLIC),
    # Codice: gira nella sandbox; il risultato dipende solo dal codice, che ha già l'etichetta della chiamata
    "python_interpreter": ToolFlow(Label.PUBLIC, exit="sandbox"),
}

# Tool del progetto ProxmoxMcp (nomi senza il prefisso del server): stato dell'infrastruttura `internal`, output di
# comandi e log `private` (decisione 2). Gli argomenti vanno al server MCP: il livello ammesso lo decide la
# classificazione del server.
_PRIVATE_OUTPUT_TOOLS = {"exec_lxc_command", "exec_host_command", "get_lxc_service_logs", "get_task_log",
                         "run_agy_bootstrap", "run_host_agy"}


def _clean(tool_name: str) -> Tuple[str, Optional[str]]:
    """(nome senza prefisso, prefisso del server) da `server__tool`."""
    if "__" in tool_name:
        ns, _, clean = tool_name.partition("__")
        return clean, ns
    return tool_name, None


# --- Classificazione dei server MCP ----------------------------------------------------------------

@dataclass(frozen=True)
class McpFlowSetting:
    result: Label = Label.PRIVATE
    untrusted: bool = False
    clearance: Label = Label.PUBLIC
    classified: bool = False


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


def init_flows_db() -> None:
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS mcp_flow_settings ("
            " scope TEXT PRIMARY KEY,"        # nome del server MCP (prefisso dei tool) o nome completo di un tool
            " result_label TEXT NOT NULL, result_untrusted INTEGER NOT NULL DEFAULT 0, clearance TEXT NOT NULL,"
            " updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )


def mcp_flow_settings() -> Dict[str, McpFlowSetting]:
    try:
        with _connect() as conn:
            rows = conn.execute("SELECT * FROM mcp_flow_settings").fetchall()
    except sqlite3.Error as e:
        logger.warning(f"Classificazione dei server MCP non leggibile: {e}")
        return {}
    return {r["scope"]: McpFlowSetting(Label.parse(r["result_label"], Label.PRIVATE), bool(r["result_untrusted"]),
                                       Label.parse(r["clearance"], Label.PUBLIC), True) for r in rows}


def save_mcp_flow_setting(scope: str, result: Any, clearance: Any, untrusted: bool = False) -> McpFlowSetting:
    scope = str(scope or "").strip()
    if not scope:
        raise ValueError("Server o tool mancante.")
    res, clr = Label.parse(result), Label.parse(clearance)
    if clr == Label.SECRET:
        raise ValueError("Nessuna destinazione può ricevere segreti.")
    with _connect() as conn:
        conn.execute(
            "INSERT INTO mcp_flow_settings (scope, result_label, result_untrusted, clearance) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(scope) DO UPDATE SET result_label = excluded.result_label, "
            "result_untrusted = excluded.result_untrusted, clearance = excluded.clearance, updated_at = CURRENT_TIMESTAMP",
            (scope, res.key, int(bool(untrusted)), clr.key),
        )
    logger.info(f"Classificazione MCP '{scope}': risultati {res.key}, argomenti fino a {clr.key}")
    return McpFlowSetting(res, bool(untrusted), clr, True)


def delete_mcp_flow_setting(scope: str) -> bool:
    with _connect() as conn:
        return bool(conn.execute("DELETE FROM mcp_flow_settings WHERE scope = ?", (scope,)).rowcount)


def mcp_setting_for(tool_name: str, table: Optional[Dict[str, McpFlowSetting]] = None) -> McpFlowSetting:
    """La regola del tool, poi quella del suo server, poi il default più stretto."""
    table = mcp_flow_settings() if table is None else table
    _, ns = _clean(tool_name)
    return table.get(tool_name) or (table.get(ns) if ns else None) or McpFlowSetting()


# --- Tag dei risultati e destinazione degli argomenti ----------------------------------------------

def _url_arg(args: Mapping[str, Any]) -> Optional[str]:
    for key in ("url", "image_path_or_url", "feed_url"):
        value = args.get(key)
        if isinstance(value, str) and value.strip().lower().startswith("webcal://"):
            return "https://" + value.strip()[len("webcal://"):]
        if isinstance(value, str) and value.strip().lower().startswith(("http://", "https://")):
            return value.strip()
    return None


def _url_destination(url: str) -> Destination:
    """Un host della rete locale (in lista, altrimenti il controllo di rete lo blocca prima) resta in casa."""
    from urllib.parse import urlparse

    from app.registry.search_security import internal_host_reason

    host = (urlparse(url).hostname or "").lower()
    local = bool(host) and internal_host_reason(host) not in (None, "nome non risolvibile")
    return Destination(f"http:{host or '?'}", "http", Label.PRIVATE if local else Label.PUBLIC)


def destination_for_tool(tool_name: str, args: Mapping[str, Any],
                         mcp_table: Optional[Dict[str, McpFlowSetting]] = None) -> Optional[Destination]:
    """Dove vanno gli argomenti di una chiamata; None se restano nel processo."""
    clean, ns = _clean(tool_name)
    flow = _TOOL_FLOWS.get(tool_name) or (_TOOL_FLOWS.get(clean) if ns is None else None)
    if flow is not None:
        if flow.exit == "search":
            return SEARCH_DESTINATION
        if flow.exit == "sandbox":
            return SANDBOX_DESTINATION
        if flow.exit == "url":
            url = _url_arg(args)
            return _url_destination(url) if url else None
        return None
    setting = mcp_setting_for(tool_name, mcp_table)
    return Destination(f"mcp:{ns or tool_name}", "mcp", setting.clearance)


def result_tag(tool_name: str, args: Optional[Mapping[str, Any]] = None, result: Any = None,
               mcp_table: Optional[Dict[str, McpFlowSetting]] = None) -> Tag:
    """Tag intrinseco del risultato di un tool. Chi lo riceve lo unisce al tag del turno (gli argomenti ne fanno parte)."""
    args = args or {}
    clean, ns = _clean(tool_name)
    flow = _TOOL_FLOWS.get(tool_name) or (_TOOL_FLOWS.get(clean) if ns is None else None)
    reason = f"tool:{tool_name}"
    if flow is not None:
        label = flow.result
        if clean == "knowledge_search":
            label = _kb_result_label(result, default=flow.result)
        if flow.exit == "url":
            url = _url_arg(args)
            if url and _url_destination(url).clearance == Label.PRIVATE:
                label = max(label, Label.INTERNAL)  # un servizio della rete locale
            if clean == "inspect_image" and not url:
                return Tag(Label.PUBLIC, True, (f"untrusted:{reason}",))  # immagine caricata: ha l'etichetta del messaggio
        return tag_of(label, reason, flow.untrusted)
    table = mcp_flow_settings() if mcp_table is None else mcp_table
    tool_row, server_row = table.get(tool_name), table.get(ns) if ns else None
    if tool_row:
        return tag_of(tool_row.result, reason, tool_row.untrusted)
    untrusted = bool(server_row and server_row.untrusted)
    if clean in _PRIVATE_OUTPUT_TOOLS:
        # Output di comandi e log: privati anche se il server è classificato più in basso (decisione 2)
        return tag_of(Label.PRIVATE, reason, untrusted)
    return tag_of(server_row.result if server_row else Label.PRIVATE, reason, untrusted)


def _kb_result_label(result: Any, default: Label) -> Label:
    """La più alta tra le etichette dei documenti restituiti; un documento senza etichetta vale `default`."""
    hits: Iterable[Any] = []
    if isinstance(result, dict):
        hits = result.get("results") or result.get("hits") or []
    elif isinstance(result, list):
        hits = result
    labels = [default]
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        raw = hit.get("sensitivity") or (hit.get("metadata") or {}).get("sensitivity")
        if raw:
            labels.append(Label.parse(raw, default))
    return max(labels)


# --- Sorgenti della memoria ------------------------------------------------------------------------

def message_tag(sensitivity: Optional[str], role: str) -> Tag:
    """Messaggio salvato: la sua etichetta; senza (messaggi precedenti a S1) `public`, come un messaggio nuovo."""
    label = Label.parse(sensitivity, Label.PUBLIC)
    return Tag(label, False, (f"messaggio:{role}",) if label > Label.PUBLIC else ())


def memory_item_tag(kind: str, item: Optional[Mapping[str, Any]], default: Label = Label.PRIVATE) -> Tag:
    """Fatto, episodio o procedura richiamati: l'etichetta del record (campo `sensitivity`, o nei suoi `metadata`) o
    il default della sorgente."""
    item = item or {}
    raw = item.get("sensitivity") or (item.get("metadata") or {}).get("sensitivity")
    return tag_of(Label.parse(raw, default), f"memoria:{kind}")


# --- Approvazioni e chiamate annidate --------------------------------------------------------------

FLOW_CAPABILITY_PREFIX = "flow:"


def flow_capability(dest: Destination, tag: Tag) -> str:
    """Capability di un'approvazione "uscita di dati": per destinazione ed etichetta. Un permesso per inviare dati
    `internal` alla ricerca non vale per dati `private`."""
    return f"{FLOW_CAPABILITY_PREFIX}{dest.id}:{tag.label.key}"


def is_flow_capability(capability: Optional[str]) -> bool:
    return bool(capability) and str(capability).startswith(FLOW_CAPABILITY_PREFIX)


def outgoing_preview(tool_name: str, args: Mapping[str, Any], dest: Destination) -> str:
    """Il testo che uscirebbe, come lo vede l'utente nella richiesta di approvazione."""
    if dest.kind == "search":
        return f"Ricerca: {args.get('query', '')}"
    if dest.kind == "http":
        from app.security.network import request_preview
        return request_preview(_url_arg(args) or "", args.get("headers") if isinstance(args.get("headers"), dict) else None)
    text = json.dumps(dict(args), ensure_ascii=False, default=str, indent=1)
    return text if len(text) <= 1500 else text[:1500] + "\n…"


_call_tag: contextvars.ContextVar[Tag] = contextvars.ContextVar("flow_call_tag", default=PUBLIC_TAG)


def run_with_call_tag(tag: Tag, fn, *args, **kwargs):
    """Il tag di chi chiama un tool, visibile al tool (current_call_tag) per le chiamate a un modello che fa lui."""
    token = _call_tag.set(join(tag))
    try:
        return fn(*args, **kwargs)
    finally:
        _call_tag.reset(token)


def current_call_tag() -> Tag:
    return _call_tag.get()
