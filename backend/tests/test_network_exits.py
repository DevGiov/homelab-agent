"""Test di sicurezza per uscite di rete verso indirizzi scelti dal modello (fase S0).

Verifica contratti di:
- app.security.network (normalize_pattern, host_matches, allowed_hosts DB, check_url, fetch, redirect)
- app.registry.search_security (internal_host_reason, is_safe_url)
- app.registry.web_search (http_get, web_search detail: full)
- app.registry.vision (inspect_image: percorsi locali, upload URL, URL remoti)
- app.registry.manager (policy automazioni scope_hosts, execute_tools_parallel con audit)
- app.security.approvals (resolve_approval approve_always per capability net:<host>)
- app.automations.models (ExecutionPolicy allowed_hosts validatore)
- app.agent.nodes.web_prefetch (web_prefetch_node con manager e gestione errori)
- app.registry.web_search_service (run_with_event_sink)
- API REST /v1/security/allowed-hosts
"""
import io
import ipaddress
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pydantic
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.agent.nodes.web_prefetch import web_prefetch_node
from app.api.main import api
from app.automations.db import definitions as definitions_db
from app.automations.models import ExecutionPolicy
from app.core.config import settings
from app.mcp.store import ToolSetting, save_tool_setting
from app.registry.manager import get_registry_manager
from app.registry.web_search_service import execute_search, run_with_event_sink
from app.security import approvals, audit_log, network, permissions
from app.security.network import (
    DEFAULT_ALLOWED_HOSTS,
    MAX_REDIRECTS,
    NetworkBlocked,
    Verdict,
    add_allowed_host,
    check_url,
    host_matches,
    init_network_db,
    list_allowed_hosts,
    normalize_pattern,
    remove_allowed_host,
    restore_default_hosts,
)

# --- Fixtures e Mock di Rete ----------------------------------------------------------------------

class RecordedRequest:
    def __init__(self, url: str, headers: Dict[str, str]):
        self.url = url
        self.headers = headers


class FakeOpen:
    """Mock di network._open che registra ogni richiesta e gestisce routing/redirect personalizzati."""

    def __init__(self):
        self.requests: List[RecordedRequest] = []
        self._handlers: List[Any] = []

    def add_handler(self, handler):
        self._handlers.append(handler)

    def __call__(self, request: urllib.request.Request, timeout: float):
        url = request.full_url
        headers = {k.lower(): v for k, v in request.header_items()}
        self.requests.append(RecordedRequest(url, headers))

        for handler in reversed(self._handlers):
            res = handler(request)
            if res is not None:
                if isinstance(res, Exception):
                    raise res
                return res

        resp = MagicMock()
        resp.status = 200
        resp.headers = {"Content-Type": "application/json"}
        resp.read.return_value = b'{"status": "ok", "mock": true}'
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = None
        return resp


@pytest.fixture
def fake_open(monkeypatch):
    fo = FakeOpen()
    monkeypatch.setattr("app.security.network._open", fo)
    return fo


@pytest.fixture
def mock_dns(monkeypatch):
    """Risoluzione DNS deterministica su IP di documentazione inventati."""
    def _fake_resolve(hostname: str) -> List[ipaddress._BaseAddress]:
        h = (hostname or "").strip().lower().rstrip(".")
        if h in (
            "example.org", "api.example.org", "svc.example.org",
            "a.example.org", "b.example.org", "c.example.org",
            "destination.example.org", "unlisted.example.org",
        ):
            return [ipaddress.ip_address("93.184.216.34")]
        if h in ("nas.home.example", "nas.local"):
            return [ipaddress.ip_address("192.168.50.10")]
        if h in ("printer.lan", "local.device"):
            return [ipaddress.ip_address("10.0.0.5")]
        return []

    monkeypatch.setattr("app.registry.search_security.resolve_hostname_ips", _fake_resolve)
    return _fake_resolve


@pytest.fixture(autouse=True)
def clean_environment():
    """Salva e ripristina lo stato di allowed_hosts e dei permessi di sessione prima e dopo ogni test."""
    init_network_db()
    with network._connect() as conn:
        hosts_backup = [dict(r) for r in conn.execute("SELECT host, note, origin, created_at FROM allowed_hosts").fetchall()]
        meta_backup = [dict(r) for r in conn.execute("SELECT key, value FROM security_meta").fetchall()]
    try:
        yield
    finally:
        with network._connect() as conn:
            conn.execute("DELETE FROM allowed_hosts")
            conn.execute("DELETE FROM security_meta")
            for h in hosts_backup:
                conn.execute(
                    "INSERT INTO allowed_hosts (host, note, origin, created_at) VALUES (?, ?, ?, ?)",
                    (h["host"], h["note"], h["origin"], h["created_at"])
                )
            for m in meta_backup:
                conn.execute("INSERT INTO security_meta (key, value) VALUES (?, ?)", (m["key"], m["value"]))
        with permissions._session_lock:
            permissions._SESSION_PERMISSIONS.clear()
        with approvals._approval_lock:
            approvals._APPROVALS.clear()


# --- Caso a: normalize_pattern --------------------------------------------------------------------

def test_normalize_pattern_valid():
    assert normalize_pattern("Example.org.") == "example.org"
    assert normalize_pattern("*.example.org") == "*.example.org"
    assert normalize_pattern("192.168.1.10") == "192.168.1.10"
    assert normalize_pattern("https://api.example.org/x?y=1") == "api.example.org"
    assert normalize_pattern("[::1]") == "::1"


def test_normalize_pattern_invalid():
    invalid_cases = [
        "",
        "*",
        "*.org",
        "example.org:8080",
        "example.org/path",
        "exa mple.org",
        "-bad.example.org",
    ]
    for case in invalid_cases:
        with pytest.raises(ValueError):
            normalize_pattern(case)


# --- Caso b: host_matches -------------------------------------------------------------------------

def test_host_matches_rules():
    assert host_matches("example.org", "*.example.org") is True
    assert host_matches("a.b.example.org", "*.example.org") is True
    assert host_matches("badexample.org", "*.example.org") is False
    assert host_matches("www.example.org", "example.org") is False
    assert host_matches("example.org", "example.org") is True


# --- Caso c: allowed_hosts lifecycle e defaults ---------------------------------------------------

def test_allowed_hosts_lifecycle_and_defaults():
    init_network_db()
    current = list_allowed_hosts()
    defaults_dict = dict(DEFAULT_ALLOWED_HOSTS)
    for host in defaults_dict:
        row = next((r for r in current if r["host"] == host), None)
        assert row is not None
        assert row["origin"] == "default"

    # Rimuovi un host
    assert remove_allowed_host("pypi.org") is True
    assert not any(r["host"] == "pypi.org" for r in list_allowed_hosts())

    # init_network_db non deve ripristinare host rimossi intenzionalmente dall'utente
    init_network_db()
    assert not any(r["host"] == "pypi.org" for r in list_allowed_hosts())

    # restore_default_hosts lo ripristina e restituisce il conteggio degli aggiunti (1)
    added = restore_default_hosts()
    assert added == 1
    assert any(r["host"] == "pypi.org" for r in list_allowed_hosts())


# --- Caso d: check_url ----------------------------------------------------------------------------

def test_check_url_listed_host_skips_dns(monkeypatch):
    add_allowed_host("example.org")

    def failing_dns(hostname: str):
        pytest.fail(f"DNS non deve essere risolto per host in lista: {hostname}")

    monkeypatch.setattr("app.registry.search_security.resolve_hostname_ips", failing_dns)
    verdict = check_url("https://example.org/resource?q=1")
    assert verdict == Verdict("example.org", True)


def test_check_url_public_unlisted_requires_approval(mock_dns):
    # api.example.org risolve a 93.184.216.34 (pubblico) ma non è in lista
    verdict = check_url("https://api.example.org/endpoint")
    assert verdict == Verdict("api.example.org", False)


def test_check_url_internal_hosts_blocked(mock_dns):
    with pytest.raises(NetworkBlocked):
        check_url("http://10.0.0.5/")
    with pytest.raises(NetworkBlocked):
        check_url("http://localhost/")
    with pytest.raises(NetworkBlocked):
        check_url("http://printer.lan/")
    # nas.home.example risolve a 192.168.50.10
    with pytest.raises(NetworkBlocked):
        check_url("http://nas.home.example/")


def test_check_url_listed_host_resolving_to_private_ip_allowed(mock_dns):
    add_allowed_host("nas.home.example")
    verdict = check_url("http://nas.home.example/ui")
    assert verdict == Verdict("nas.home.example", True)


def test_check_url_invalid_schemes_blocked():
    with pytest.raises(NetworkBlocked):
        check_url("ftp://example.org/")
    with pytest.raises(NetworkBlocked):
        check_url("file:///etc/passwd")


# --- Caso e: http_get end-to-end ------------------------------------------------------------------

def test_http_get_listed_host_executes_and_returns_data(fake_open, mock_dns):
    add_allowed_host("example.org")
    reg_mgr = get_registry_manager()

    res = reg_mgr.execute_tool(
        "http_get",
        {"url": "https://example.org/api/status"},
        allowed_registries=["web"],
        thread_id="t-http-1"
    )
    assert res.get("status") == 200
    assert res.get("data") == {"status": "ok", "mock": True}
    assert len(fake_open.requests) == 1
    assert fake_open.requests[0].url == "https://example.org/api/status"


def test_http_get_public_unlisted_requires_approval(fake_open, mock_dns):
    reg_mgr = get_registry_manager()
    res = reg_mgr.execute_tool(
        "http_get",
        {"url": "https://api.example.org/items?category=tech&page=1"},
        allowed_registries=["web"],
        thread_id="t-http-2"
    )
    assert res.get("approval_required") is True
    assert res.get("command_prefix") == "net:api.example.org"
    assert "https://api.example.org/items?category=tech&page=1" in res.get("command_preview", "")
    assert len(fake_open.requests) == 0


def test_http_get_preview_masks_sensitive_headers(mock_dns):
    reg_mgr = get_registry_manager()
    res = reg_mgr.execute_tool(
        "http_get",
        {
            "url": "https://api.example.org/secure",
            "headers": {"Authorization": "Bearer confidential123456", "X-Trace": "trace-ident-9999"}
        },
        allowed_registries=["web"],
        thread_id="t-http-3"
    )
    assert res.get("approval_required") is True
    preview = res.get("command_preview", "")
    assert "Authorization: ••••" in preview
    assert "confidential123456" not in preview
    assert "X-Trace: trace-ident-9999" in preview


def test_http_get_internal_unlisted_blocked(fake_open, mock_dns):
    reg_mgr = get_registry_manager()
    res = reg_mgr.execute_tool(
        "http_get",
        {"url": "http://10.0.0.5/admin"},
        allowed_registries=["web"],
        thread_id="t-http-4"
    )
    assert res.get("blocked") is True
    assert "error" in res
    assert not res.get("approval_required")
    assert len(fake_open.requests) == 0


def test_http_get_dangerous_mode(fake_open, mock_dns):
    reg_mgr = get_registry_manager()
    # Host pubblico non in lista in dangerous mode: parte senza approvazione
    res_pub = reg_mgr.execute_tool(
        "http_get",
        {"url": "https://api.example.org/data"},
        allowed_registries=["web"],
        thread_id="t-http-5",
        security_mode="dangerous"
    )
    assert res_pub.get("status") == 200
    assert not res_pub.get("approval_required")

    # Host interno in dangerous mode: resta bloccato (protezione SSRF invariabile)
    res_int = reg_mgr.execute_tool(
        "http_get",
        {"url": "http://10.0.0.5/data"},
        allowed_registries=["web"],
        thread_id="t-http-5",
        security_mode="dangerous"
    )
    assert res_int.get("blocked") is True
    assert not res_int.get("approval_required")


def test_http_get_approval_flow_one_time(fake_open, mock_dns):
    reg_mgr = get_registry_manager()
    first = reg_mgr.execute_tool(
        "http_get",
        {"url": "https://api.example.org/one-time"},
        allowed_registries=["web"],
        thread_id="t-http-6"
    )
    req_id = first["request_id"]

    resolved = approvals.resolve_approval(req_id, "approve")
    assert resolved.status == "approved"

    second = reg_mgr.execute_approved_tool(req_id)
    assert second.get("status") == 200
    assert second.get("data") == {"status": "ok", "mock": True}


def test_http_get_approval_always(fake_open, mock_dns):
    reg_mgr = get_registry_manager()
    first = reg_mgr.execute_tool(
        "http_get",
        {"url": "https://api.example.org/persistent"},
        allowed_registries=["web"],
        thread_id="t-http-7"
    )
    req_id = first["request_id"]

    approvals.resolve_approval(req_id, "approve_always")

    # Host aggiunto in allowed_hosts con origin "approval"
    allowed = list_allowed_hosts()
    entry = next((r for r in allowed if r["host"] == "api.example.org"), None)
    assert entry is not None
    assert entry["origin"] == "approval"

    # Non deve esistere una voce net: in tool_permissions
    always_perms = permissions.list_granted_permissions()["always"]
    assert not any((p.get("command_prefix") or "").startswith("net:") for p in always_perms)

    # Nuova chiamata diretta parte senza richiesta di approvazione
    second = reg_mgr.execute_tool(
        "http_get",
        {"url": "https://api.example.org/another"},
        allowed_registries=["web"],
        thread_id="t-http-other"
    )
    assert second.get("status") == 200
    assert not second.get("approval_required")


def test_http_get_approval_thread_scoped(fake_open, mock_dns):
    reg_mgr = get_registry_manager()
    thread_a = "t-scope-a"
    thread_b = "t-scope-b"
    try:
        first = reg_mgr.execute_tool(
            "http_get",
            {"url": "https://svc.example.org/first"},
            allowed_registries=["web"],
            thread_id=thread_a
        )
        approvals.resolve_approval(first["request_id"], "approve_thread")

        # Seconda chiamata nello stesso thread procede
        second = reg_mgr.execute_tool(
            "http_get",
            {"url": "https://svc.example.org/second"},
            allowed_registries=["web"],
            thread_id=thread_a
        )
        assert second.get("status") == 200
        assert not second.get("approval_required")

        # In un altro thread richiede nuovamente autorizzazione
        third = reg_mgr.execute_tool(
            "http_get",
            {"url": "https://svc.example.org/third"},
            allowed_registries=["web"],
            thread_id=thread_b
        )
        assert third.get("approval_required") is True
    finally:
        permissions.revoke_thread_permissions(thread_a)
        permissions.revoke_thread_permissions(thread_b)


def test_http_get_redirect_to_internal_blocked(fake_open, mock_dns):
    add_allowed_host("example.org")
    reg_mgr = get_registry_manager()

    def redir_internal(req):
        if req.full_url == "https://example.org/step1":
            return urllib.error.HTTPError(
                url=req.full_url,
                code=302,
                msg="Found",
                hdrs={"Location": "http://10.0.0.5/private"},
                fp=io.BytesIO(b"")
            )
        return None

    fake_open.add_handler(redir_internal)
    res = reg_mgr.execute_tool(
        "http_get",
        {"url": "https://example.org/step1"},
        allowed_registries=["web"],
        thread_id="t-redir-1"
    )
    assert res.get("blocked") is True
    assert "error" in res


def test_http_get_redirect_to_unlisted_public_strips_headers(fake_open, mock_dns):
    add_allowed_host("example.org")
    reg_mgr = get_registry_manager()

    def redir_public(req):
        if req.full_url == "https://example.org/source":
            return urllib.error.HTTPError(
                url=req.full_url,
                code=302,
                msg="Found",
                hdrs={"Location": "https://api.example.org/target"},
                fp=io.BytesIO(b"")
            )
        return None

    fake_open.add_handler(redir_public)
    res = reg_mgr.execute_tool(
        "http_get",
        {"url": "https://example.org/source", "headers": {"X-Token": "secret123"}},
        allowed_registries=["web"],
        thread_id="t-redir-2"
    )
    assert res.get("status") == 200
    assert len(fake_open.requests) == 2
    assert fake_open.requests[0].url == "https://example.org/source"
    assert fake_open.requests[0].headers.get("x-token") == "secret123"
    assert fake_open.requests[1].url == "https://api.example.org/target"
    assert "x-token" not in fake_open.requests[1].headers


def test_http_get_redirect_loop_bounded(fake_open, mock_dns):
    add_allowed_host("example.org")
    reg_mgr = get_registry_manager()

    def redir_loop(req):
        return urllib.error.HTTPError(
            url=req.full_url,
            code=302,
            msg="Found",
            hdrs={"Location": f"{req.full_url}_next"},
            fp=io.BytesIO(b"")
        )

    fake_open.add_handler(redir_loop)
    res = reg_mgr.execute_tool(
        "http_get",
        {"url": "https://example.org/loop"},
        allowed_registries=["web"],
        thread_id="t-redir-loop"
    )
    assert res.get("blocked") is True
    assert f"massimo {MAX_REDIRECTS}" in res.get("error", "")


def test_http_get_404_response(fake_open, mock_dns):
    add_allowed_host("example.org")
    reg_mgr = get_registry_manager()

    def not_found(req):
        return urllib.error.HTTPError(
            url=req.full_url,
            code=404,
            msg="Not Found",
            hdrs={"Content-Type": "text/plain"},
            fp=io.BytesIO(b"Elemento non trovato")
        )

    fake_open.add_handler(not_found)
    res = reg_mgr.execute_tool(
        "http_get",
        {"url": "https://example.org/missing"},
        allowed_registries=["web"],
        thread_id="t-404"
    )
    assert res.get("status") == 404
    assert "404" in res.get("error", "")


# --- Caso f: Policy automazioni -------------------------------------------------------------------

def test_automation_execution_policy_allowed_hosts():
    # Normalizzazione e deduplicazione
    policy = ExecutionPolicy(allowed_hosts=["API.example.org", "api.example.org", "*.example.net"])
    assert policy.allowed_hosts == ["api.example.org", "*.example.net"]

    # Stringa con virgole e a capo
    policy_str = ExecutionPolicy(allowed_hosts="a.example.org, b.example.org\nc.example.org")
    assert policy_str.allowed_hosts == ["a.example.org", "b.example.org", "c.example.org"]

    # Voce non valida solleva ValidationError
    with pytest.raises(pydantic.ValidationError):
        ExecutionPolicy(allowed_hosts=["*.org"])


def test_automation_policy_scope_hosts_end_to_end(fake_open, mock_dns):
    reg_mgr = get_registry_manager()
    auto_id = "auto_test_net_scope"
    definitions_db.save_definition({
        "id": auto_id,
        "name": "Auto Scope Net Test",
        "workflow": {"steps": []},
        "permission_policy": {
            "allowed_hosts": ["api.example.org"]
        }
    })
    try:
        # Con automation_id parte senza chiedere approvazione
        res_auto = reg_mgr.execute_tool(
            "http_get",
            {"url": "https://api.example.org/items"},
            allowed_registries=["web"],
            automation_id=auto_id
        )
        assert res_auto.get("status") == 200
        assert not res_auto.get("approval_required")

        # Senza automation_id lo stesso host chiede approvazione
        res_no_auto = reg_mgr.execute_tool(
            "http_get",
            {"url": "https://api.example.org/items"},
            allowed_registries=["web"]
        )
        assert res_no_auto.get("approval_required") is True
    finally:
        definitions_db.delete_definition(auto_id)


# --- Caso g: inspect_image ------------------------------------------------------------------------

class FakeVLProvider:
    def __init__(self):
        self.calls = []

    def effective_model(self, model=None):
        return "fake-vl"

    def chat(self, messages, **kw):
        self.calls.append((messages, kw))
        return {"content": "analisi"}


def test_inspect_image_local_path_traversal_blocked(monkeypatch):
    provider = FakeVLProvider()
    monkeypatch.setattr("app.llm.providers.get_provider", lambda: provider)
    reg_mgr = get_registry_manager()

    res1 = reg_mgr.execute_tool("inspect_image", {"image_path_or_url": "/etc/hostname"}, allowed_registries=["vision"])
    assert "Percorso non ammesso" in res1.get("error", "")

    res2 = reg_mgr.execute_tool("inspect_image", {"image_path_or_url": "../../etc/passwd"}, allowed_registries=["vision"])
    assert "Percorso non ammesso" in res2.get("error", "")

    assert len(provider.calls) == 0


def test_inspect_image_valid_local_and_upload_url(monkeypatch):
    provider = FakeVLProvider()
    monkeypatch.setattr("app.llm.providers.get_provider", lambda: provider)
    reg_mgr = get_registry_manager()

    uploads = Path(settings.uploads_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    img_file = uploads / "test_img_valid.png"
    im = Image.new("RGB", (10, 10), color="blue")
    im.save(img_file, format="PNG")

    try:
        # Percorso assoluto
        res_abs = reg_mgr.execute_tool("inspect_image", {"image_path_or_url": str(img_file)}, allowed_registries=["vision"])
        assert res_abs.get("success") is True
        assert res_abs.get("analysis") == "analisi"
        assert len(provider.calls) == 1
        msgs, _ = provider.calls[0]
        content_items = msgs[0]["content"]
        img_item = next(item for item in content_items if item.get("type") == "image_url")
        assert img_item["image_url"]["url"].startswith("data:image/jpeg;base64,")

        # URL relativo /v1/uploads/<nome>
        res_rel = reg_mgr.execute_tool("inspect_image", {"image_path_or_url": "/v1/uploads/test_img_valid.png"}, allowed_registries=["vision"])
        assert res_rel.get("success") is True
        assert res_rel.get("analysis") == "analisi"
    finally:
        img_file.unlink(missing_ok=True)


def test_inspect_image_non_image_fails(monkeypatch):
    provider = FakeVLProvider()
    monkeypatch.setattr("app.llm.providers.get_provider", lambda: provider)
    reg_mgr = get_registry_manager()

    uploads = Path(settings.uploads_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    text_file = uploads / "corrupt.png"
    text_file.write_text("not an image binary")
    try:
        res = reg_mgr.execute_tool("inspect_image", {"image_path_or_url": str(text_file)}, allowed_registries=["vision"])
        assert "error" in res
        assert "non è un'immagine" in res["error"]
        assert len(provider.calls) == 0
    finally:
        text_file.unlink(missing_ok=True)


def test_inspect_image_remote_url_verdicts(fake_open, mock_dns):
    reg_mgr = get_registry_manager()

    # Host pubblico non in lista richiede approvazione
    res_pub = reg_mgr.execute_tool("inspect_image", {"image_path_or_url": "https://api.example.org/pic.png"}, allowed_registries=["vision"])
    assert res_pub.get("approval_required") is True

    # Host interno bloccato
    res_int = reg_mgr.execute_tool("inspect_image", {"image_path_or_url": "http://10.0.0.5/pic.png"}, allowed_registries=["vision"])
    assert res_int.get("blocked") is True


# --- Caso h: Prefetch -----------------------------------------------------------------------------

def test_web_prefetch_node_execution_and_audit():
    def fake_search(query, count=8):
        return {
            "query": query,
            "success": True,
            "provider_used": "Finto",
            "latency_ms": 1,
            "sources": [{"title": "t", "url": "https://example.org/a", "snippet": "s"}],
            "summary_text": "sintesi",
            "error": None,
        }

    with patch("app.registry.web_search.execute_search", side_effect=fake_search):
        res = web_prefetch_node({"task": "ricerca news", "web_search": "on", "thread_id": "t-prefetch", "mode": "ask"})
        meta = res.get("web_prefetch_metadata", {})
        assert meta.get("sources") == [{"title": "t", "url": "https://example.org/a", "snippet": "s"}]
        assert meta.get("success") is True

        recent = audit_log.get_recent(thread_id="t-prefetch")
        assert any(r["tool_name"] == "web_search" for r in recent)

        # Tool impostato a blocked
        save_tool_setting("web_search", ToolSetting(risk="blocked"))
        try:
            res_blocked = web_prefetch_node({"task": "ricerca news", "web_search": "on", "thread_id": "t-prefetch-blocked", "mode": "ask"})
            assert res_blocked["web_prefetch_metadata"]["success"] is False
        finally:
            save_tool_setting("web_search", ToolSetting())


# --- Caso i: run_with_event_sink ------------------------------------------------------------------

def test_run_with_event_sink_forwards_callback():
    events = []

    def sink(event_name: str, payload: Dict[str, Any]):
        events.append((event_name, payload))

    def fake_search_with_fallback(query: str, count: int = 8, time_filter=None, event_callback=None):
        if event_callback:
            event_callback("web_prefetch.provider_attempt", {"provider": "MockProvider", "query": query})
        return ([], "None")

    with patch("app.registry.web_search_service.search_with_fallback", side_effect=fake_search_with_fallback):
        res = run_with_event_sink(sink, execute_search, "query sink")
        assert res["success"] is False
        assert len(events) == 1
        assert events[0][0] == "web_prefetch.provider_attempt"
        assert events[0][1]["query"] == "query sink"
        assert events[0][1]["provider"] == "MockProvider"


# --- Caso j: execute_tools_parallel audit forwarding ----------------------------------------------

def test_execute_tools_parallel_forwards_audit_metadata():
    fake_result = {
        "query": "dummy",
        "success": True,
        "provider_used": "Finto",
        "sources": [],
        "summary_text": "sommario",
    }
    with patch("app.registry.web_search.execute_search", return_value=fake_result):
        calls = [
            {"tool_name": "web_search", "arguments": {"query": "query parallela 1"}},
            {"tool_name": "web_search", "arguments": {"query": "query parallela 2"}},
        ]
        results = get_registry_manager().execute_tools_parallel(
            calls,
            allowed_registries=["web"],
            automation_id="auto-x",
            run_id="run-x",
        )
        assert len(results) == 2
        entries = audit_log.get_recent(limit=10, automation_id="auto-x", run_id="run-x")
        matching = [e for e in entries if e["tool_name"] == "web_search"]
        assert len(matching) >= 2
        for entry in matching[:2]:
            assert entry["automation_id"] == "auto-x"
            assert entry["run_id"] == "run-x"


# --- Caso k: API REST allowed-hosts ---------------------------------------------------------------

def test_api_allowed_hosts_endpoints():
    client = TestClient(api)

    # 1. GET lista
    res_get = client.get("/v1/security/allowed-hosts")
    assert res_get.status_code == 200
    data = res_get.json()
    assert "hosts" in data
    assert "defaults" in data
    assert any(h["host"] == "pypi.org" for h in data["hosts"])

    # 2. POST con normalizzazione lowercase
    res_post = client.post("/v1/security/allowed-hosts", json={"host": "Svc.Example.org", "note": "n"})
    assert res_post.status_code == 200
    assert res_post.json()["host"] == "svc.example.org"
    assert res_post.json()["note"] == "n"

    # 3. POST non valido (*.org richiede almeno due livelli)
    res_post_bad = client.post("/v1/security/allowed-hosts", json={"host": "*.org", "note": ""})
    assert res_post_bad.status_code == 422

    # 4. DELETE host aggiunto
    res_del = client.delete("/v1/security/allowed-hosts/svc.example.org")
    assert res_del.status_code == 200
    assert res_del.json() == {"removed": "svc.example.org"}

    # 5. DELETE di nuovo -> 404
    res_del_404 = client.delete("/v1/security/allowed-hosts/svc.example.org")
    assert res_del_404.status_code == 404

    # 6. POST defaults
    res_defaults = client.post("/v1/security/allowed-hosts/defaults")
    assert res_defaults.status_code == 200
    assert "added" in res_defaults.json()
