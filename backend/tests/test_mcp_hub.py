"""Server MCP registrati: catalogo aggregato, instradamento, impostazioni per tool, policy e API."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.mcp import hub as hub_module
from app.mcp import store
from app.mcp.store import MCPServer, ToolSetting
from app.security.policy import enforce_guardrails, is_view_tool

EXTRA_URL = "http://creative.test/mcp"

# Server finti per URL: tool esposti, guasto simulato e chiamate ricevute
FAKE_SERVERS: dict = {}


class FakeMCPClient:
    def __init__(self, url: str, api_key: str = ""):
        self.url = url
        self.api_key = api_key

    def list_tools(self):
        server = FAKE_SERVERS[self.url]
        if server.get("down"):
            raise RuntimeError("server irraggiungibile")
        return [{"name": n, "description": f"desc {n}", "inputSchema": {"type": "object", "properties": {}}} for n in server["tools"]]

    def call_tool(self, name, arguments):
        FAKE_SERVERS[self.url]["calls"].append((name, arguments, self.api_key))
        return {"ok": name}

    def close(self):
        pass


@pytest.fixture(autouse=True)
def fake_mcp(monkeypatch):
    FAKE_SERVERS.clear()
    FAKE_SERVERS[settings.metamcp_url] = {"tools": ["proxmox-mcp__list_containers", "proxmox-mcp__stop_container"], "calls": []}
    FAKE_SERVERS[EXTRA_URL] = {"tools": ["session_status", "app_command"], "calls": []}
    Path(settings.mcp_db_path).unlink(missing_ok=True)
    store._invalidate_tool_settings()
    monkeypatch.setattr(hub_module, "MCPClient", FakeMCPClient)
    hub_module.get_mcp_hub.cache_clear()
    yield
    hub_module.get_mcp_hub.cache_clear()
    store._invalidate_tool_settings()


def add_extra_server(**overrides) -> MCPServer:
    server = MCPServer(id="creative", name="Creative", url=EXTRA_URL, token="segreto", **overrides)
    store.save_server(server)
    hub_module.get_mcp_hub().invalidate("creative")
    return server


def names(tools):
    return sorted(t["name"] for t in tools)


class TestHub:
    def test_catalog_aggregates_servers_with_prefix_only_for_added_ones(self):
        add_extra_server()
        tools = hub_module.get_mcp_hub().tools()
        assert names(tools) == ["creative__app_command", "creative__session_status", "proxmox-mcp__list_containers", "proxmox-mcp__stop_container"]
        assert {t["name"]: t["server"] for t in tools}["creative__session_status"] == "creative"

    def test_call_is_routed_to_the_owning_server_with_its_token(self):
        add_extra_server()
        hub = hub_module.get_mcp_hub()
        assert hub.call_tool("creative__session_status", {"x": 1}) == {"ok": "session_status"}
        assert FAKE_SERVERS[EXTRA_URL]["calls"] == [("session_status", {"x": 1}, "segreto")]
        assert FAKE_SERVERS[settings.metamcp_url]["calls"] == []

    def test_disabled_tool_leaves_the_catalog_and_cannot_run(self):
        store.save_tool_setting("proxmox-mcp__stop_container", ToolSetting(enabled=False))
        hub = hub_module.get_mcp_hub()
        assert "proxmox-mcp__stop_container" not in names(hub.tools())
        assert "proxmox-mcp__stop_container" in names(hub.tools(include_disabled=True))
        assert "disattivato" in hub.call_tool("proxmox-mcp__stop_container", {})["error"]

    def test_new_server_is_visible_without_waiting_for_the_cache(self):
        hub = hub_module.get_mcp_hub()
        assert len(hub.tools()) == 2
        add_extra_server()
        assert len(hub.tools()) == 4

    def test_disabled_server_is_not_queried(self):
        add_extra_server(enabled=False)
        assert all(t["server"] == "metamcp" for t in hub_module.get_mcp_hub().tools())

    def test_unreachable_server_keeps_its_last_known_tools(self):
        add_extra_server()
        hub = hub_module.get_mcp_hub()
        hub.tools()
        FAKE_SERVERS[EXTRA_URL]["down"] = True
        hub.refresh(force=True)
        assert "creative__session_status" in names(hub.tools())
        status = hub.status()["creative"]
        assert not status.ok and "irraggiungibile" in status.error

    def test_name_collision_keeps_the_first_server(self):
        FAKE_SERVERS[EXTRA_URL]["tools"] = ["session_status"]
        FAKE_SERVERS[settings.metamcp_url]["tools"].append("creative__session_status")
        add_extra_server()
        tools = hub_module.get_mcp_hub().tools()
        assert [t["server"] for t in tools if t["name"] == "creative__session_status"] == ["metamcp"]

    def test_deleting_a_server_removes_its_tool_settings(self):
        add_extra_server()
        store.save_tool_setting("creative__app_command", ToolSetting(risk="blocked"))
        store.delete_server("creative")
        assert store.tool_settings() == {}


class TestPolicy:
    def test_view_risk_makes_a_tool_read_only(self):
        assert not is_view_tool("creative__app_command")
        store.save_tool_setting("creative__app_command", ToolSetting(risk="view"))
        assert is_view_tool("creative__app_command")
        assert enforce_guardrails("creative__app_command", {}, security_mode="normal") is None

    def test_confirm_risk_asks_even_for_a_read_tool(self):
        assert is_view_tool("proxmox-mcp__list_containers")
        store.save_tool_setting("proxmox-mcp__list_containers", ToolSetting(risk="confirm"))
        assert enforce_guardrails("proxmox-mcp__list_containers", {}, security_mode="normal")["approval_required"]

    def test_blocked_risk_wins_even_in_dangerous_mode(self):
        store.save_tool_setting("proxmox-mcp__list_containers", ToolSetting(risk="blocked"))
        guard = enforce_guardrails("proxmox-mcp__list_containers", {}, security_mode="dangerous")
        assert guard["blocked"] and "bloccato" in guard["reason"]


@pytest.fixture
def api():
    from app.api.main import api as app

    return TestClient(app)


class TestApi:
    def test_create_list_update_delete(self, api):
        res = api.post("/v1/mcp/servers", json={"id": "creative", "name": "Creative", "url": EXTRA_URL, "token": "segreto"})
        assert res.status_code == 201
        assert res.json()["status"] == {"ok": True, "tool_count": 2, "error": None, "checked_at": res.json()["status"]["checked_at"]}

        servers = {s["id"]: s for s in api.get("/v1/mcp/servers").json()}
        assert servers["metamcp"]["builtin"] and servers["creative"]["has_token"]
        assert "token" not in servers["creative"]

        # token omesso: resta quello salvato
        api.put("/v1/mcp/servers/creative", json={"name": "Creative 2", "url": EXTRA_URL})
        assert store.get_server("creative").token == "segreto"
        # token vuoto: rimosso
        api.put("/v1/mcp/servers/creative", json={"name": "Creative 2", "url": EXTRA_URL, "token": ""})
        assert store.get_server("creative").token == ""

        assert api.delete("/v1/mcp/servers/creative").status_code == 200
        assert [s["id"] for s in api.get("/v1/mcp/servers").json()] == ["metamcp"]

    def test_validation(self, api):
        assert api.post("/v1/mcp/servers", json={"id": "metamcp", "name": "x", "url": EXTRA_URL}).status_code == 409
        # l'id coinciderebbe con il namespace di tool già esposti da MetaMCP
        assert api.post("/v1/mcp/servers", json={"id": "proxmox-mcp", "name": "x", "url": EXTRA_URL}).status_code == 409
        assert api.post("/v1/mcp/servers", json={"id": "Non Valido", "name": "x", "url": EXTRA_URL}).status_code == 422
        assert api.post("/v1/mcp/servers", json={"id": "ok-id", "name": "x", "url": "ftp://x"}).status_code == 422
        assert api.put("/v1/mcp/servers/metamcp", json={"name": "x", "url": EXTRA_URL}).status_code == 400
        assert api.delete("/v1/mcp/servers/metamcp").status_code == 400
        assert api.delete("/v1/mcp/servers/assente").status_code == 404

    def test_connection_test_before_saving(self, api):
        assert api.post("/v1/mcp/servers/test", json={"url": EXTRA_URL}).json()["tools"] == ["session_status", "app_command"]
        FAKE_SERVERS[EXTRA_URL]["down"] = True
        assert api.post("/v1/mcp/servers/test", json={"url": EXTRA_URL}).json()["ok"] is False

    def test_tool_settings(self, api):
        tools = {t["name"]: t for t in api.get("/v1/mcp/tools").json()}
        assert tools["proxmox-mcp__list_containers"]["access"] == "view"
        assert tools["proxmox-mcp__stop_container"]["access"] == "execute"

        res = api.put("/v1/mcp/tools/proxmox-mcp__stop_container", json={"enabled": False, "risk": "blocked"})
        assert res.json() == {"name": "proxmox-mcp__stop_container", "enabled": False, "risk": "blocked", "access": "execute"}
        assert "proxmox-mcp__stop_container" in [t["name"] for t in api.get("/v1/mcp/tools").json()]
        assert api.put("/v1/mcp/tools/assente", json={"enabled": True, "risk": "auto"}).status_code == 404
        assert api.put("/v1/mcp/tools/proxmox-mcp__stop_container", json={"enabled": True, "risk": "x"}).status_code == 422
