from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.mcp.client import MCPClient, _normalize_result


def _text_result(text, is_error=False, structured=None):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], is_error=is_error, structured_content=structured)


def test_tool_error_becomes_error_key():
    assert _normalize_result(_text_result("container 999 non trovato", is_error=True)) == {"error": "container 999 non trovato"}


def test_json_object_text_is_parsed():
    assert _normalize_result(_text_result('{"vmid": 250, "status": "created"}')) == {"vmid": 250, "status": "created"}


def test_non_object_text_stays_in_content():
    assert _normalize_result(_text_result('[{"vmid": 100}]')) == {"content": '[{"vmid": 100}]'}


def test_structured_content_without_text():
    result = SimpleNamespace(content=[], is_error=False, structured_content={"ok": True})
    assert _normalize_result(result) == {"ok": True}


def _client(run_side_effect, session_alive):
    """MCPClient senza rete: sessione finta, _run e stato della sessione controllati dal test."""
    client = MCPClient("http://mcp.test/mcp")
    run = MagicMock(side_effect=run_side_effect)
    patches = [
        patch.object(client, "_connect", return_value=MagicMock()),
        patch.object(client, "_reset"),
        patch.object(client, "_run", run),
        patch.object(client, "_session_alive", side_effect=session_alive),
    ]
    for p in patches:
        p.start()
    return client, run, patches


@pytest.fixture
def stop_patches():
    started = []
    yield started
    for p in started:
        p.stop()


def test_list_tools_retries_once_after_reset(stop_patches):
    tool = SimpleNamespace(name="list_containers", description=None, input_schema={})
    client, run, patches = _client([ConnectionError("sessione scaduta"), SimpleNamespace(tools=[tool])], session_alive=[True, False])
    stop_patches.extend(patches)

    tools = client.list_tools()

    assert run.call_count == 2
    assert tools == [{"name": "list_containers", "description": "", "inputSchema": {"type": "object", "properties": {}}}]


def test_call_tool_retries_on_stale_session(stop_patches):
    client, run, patches = _client([ConnectionError("sessione scaduta"), _text_result('{"ok": true}')], session_alive=[True, False])
    stop_patches.extend(patches)

    assert client.call_tool("stop_container", {"vmid": 1}) == {"ok": True}
    assert run.call_count == 2


def test_call_tool_not_retried_on_fresh_session(stop_patches):
    client, run, patches = _client([ConnectionError("connessione rifiutata")], session_alive=[False])
    stop_patches.extend(patches)

    with pytest.raises(RuntimeError):
        client.call_tool("stop_container", {"vmid": 1})
    assert run.call_count == 1


def test_call_tool_not_retried_on_timeout(stop_patches):
    # Il tool potrebbe essere ancora in esecuzione sul server: ritentare lo eseguirebbe due volte
    client, run, patches = _client([TimeoutError()], session_alive=[True])
    stop_patches.extend(patches)

    with pytest.raises(RuntimeError):
        client.call_tool("create_lxc_from_template", {"key": "base"})
    assert run.call_count == 1
