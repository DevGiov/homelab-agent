"""ISS-18: il codice LLM gira fuori dalla sandbox Firecracker solo dopo un'approvazione esplicita."""
import uuid
from unittest.mock import patch

import pytest

from app.registry.firecracker_sandbox import FirecrackerSandbox
from app.registry.manager import get_registry_manager
from app.security import guardrails, permissions

TOOL = "python_interpreter"


@pytest.fixture
def sandbox_down():
    with patch.object(FirecrackerSandbox, "is_available", return_value=False):
        yield


@pytest.fixture
def thread_id():
    tid = f"thread_sandbox_{uuid.uuid4().hex[:8]}"
    yield tid
    permissions.revoke_thread_permissions(tid)


def _code_writing(marker_path) -> str:
    return f"open({str(marker_path)!r}, 'w').write('ran'); print('eseguito')"


def _run(code: str, thread_id: str, security_mode: str = "normal", extra_args=None):
    args = {"code": code, **(extra_args or {})}
    return get_registry_manager().execute_tool(TOOL, args, ["code"], thread_id=thread_id, mode="act", security_mode=security_mode)


def _approve(request_id: str, action: str = "approve"):
    assert guardrails.resolve_approval(request_id, action=action).status == "approved"
    return get_registry_manager().execute_approved_tool(request_id)


def test_sandbox_down_requires_local_fallback_approval(sandbox_down, thread_id, tmp_path):
    # L'utente ha già autorizzato python_interpreter (nella sandbox) per questa chat
    permissions.grant_permission(TOOL, "thread", thread_id=thread_id)
    marker = tmp_path / "marker"

    res = _run(_code_writing(marker), thread_id)

    assert res["approval_required"] is True
    assert res["command_prefix"] == guardrails.LOCAL_CODE_FALLBACK
    assert "Sandbox Firecracker non disponibile" in res["risk_reason"]
    assert res["command_preview"] == _code_writing(marker)
    assert not marker.exists()


def test_approved_local_fallback_runs_code_unsandboxed(sandbox_down, thread_id, tmp_path):
    permissions.grant_permission(TOOL, "thread", thread_id=thread_id)
    marker = tmp_path / "marker"
    pending = _run(_code_writing(marker), thread_id)

    result = _approve(pending["request_id"])

    assert result["success"] is True
    assert result["sandboxed"] is False
    assert result["output"] == "eseguito"
    assert marker.read_text() == "ran"


def test_sandbox_approval_does_not_unlock_local_execution(sandbox_down, thread_id, tmp_path):
    # Prima richiesta: approvazione standard del tool (pensata per la sandbox)
    marker = tmp_path / "marker"
    pending = _run(_code_writing(marker), thread_id)
    assert pending["approval_required"] is True
    assert pending["command_prefix"] is None

    # Approvarla con la sandbox giù non esegue in locale: serve una nuova approvazione specifica
    result = _approve(pending["request_id"])

    assert result["approval_required"] is True
    assert result["command_prefix"] == guardrails.LOCAL_CODE_FALLBACK
    assert not marker.exists()


def test_thread_grant_for_local_fallback_skips_further_prompts(sandbox_down, thread_id, tmp_path):
    permissions.grant_permission(TOOL, "thread", thread_id=thread_id)
    pending = _run("print(1)", thread_id)
    _approve(pending["request_id"], action="approve_thread")

    marker = tmp_path / "marker"
    res = _run(_code_writing(marker), thread_id)

    assert res["output"] == "eseguito"
    assert marker.read_text() == "ran"


def test_local_fallback_grant_is_scoped_to_its_thread(sandbox_down, thread_id, tmp_path):
    permissions.grant_permission(TOOL, "thread", thread_id=thread_id)
    _approve(_run("print(1)", thread_id)["request_id"], action="approve_thread")

    other_thread = f"{thread_id}_other"
    try:
        permissions.grant_permission(TOOL, "thread", thread_id=other_thread)
        res = _run("print(2)", other_thread)
    finally:
        permissions.revoke_thread_permissions(other_thread)

    assert res["approval_required"] is True
    assert res["command_prefix"] == guardrails.LOCAL_CODE_FALLBACK


def test_llm_cannot_self_approve_with_arguments(sandbox_down, thread_id, tmp_path):
    permissions.grant_permission(TOOL, "thread", thread_id=thread_id)
    marker = tmp_path / "marker"

    res = _run(
        _code_writing(marker), thread_id,
        extra_args={"confirm": True, "approved": True, "capability": guardrails.LOCAL_CODE_FALLBACK},
    )

    assert res["approval_required"] is True
    assert not marker.exists()


def test_dangerous_mode_runs_locally_without_prompt(sandbox_down, thread_id, tmp_path):
    marker = tmp_path / "marker"

    res = _run(_code_writing(marker), thread_id, security_mode="dangerous")

    assert res["output"] == "eseguito"
    assert res["sandboxed"] is False
    assert marker.read_text() == "ran"


def test_sandbox_available_never_prompts_for_fallback(thread_id):
    permissions.grant_permission(TOOL, "thread", thread_id=thread_id)
    sandboxed = {"output": "4", "success": True, "sandboxed": True, "error": None}
    with patch.object(FirecrackerSandbox, "execute_code", return_value=sandboxed), \
         patch.object(FirecrackerSandbox, "execute_local") as local_mock:
        res = _run("print(2 + 2)", thread_id)

    assert res == sandboxed
    local_mock.assert_not_called()


def test_resolve_endpoint_surfaces_local_fallback_as_new_approval(sandbox_down, thread_id, tmp_path):
    from fastapi.testclient import TestClient

    from app.api.main import api

    client = TestClient(api)
    marker = tmp_path / "marker"
    pending = _run(_code_writing(marker), thread_id)

    with patch("app.api.routes.approvals._call_llm") as llm_mock:
        first = client.post(f"/v1/approvals/{pending['request_id']}/resolve", json={"action": "approve"}).json()
    llm_mock.assert_not_called()

    step = first["execution_trace"][0]
    assert step["approval_required"] is True
    assert step["command_prefix"] == guardrails.LOCAL_CODE_FALLBACK
    assert not marker.exists()

    with patch("app.api.routes.approvals._call_llm", return_value={"content": "Codice eseguito fuori sandbox."}):
        second = client.post(f"/v1/approvals/{step['request_id']}/resolve", json={"action": "approve"}).json()

    assert second["result"]["output"] == "eseguito"
    assert second["response"] == "Codice eseguito fuori sandbox."
    assert marker.read_text() == "ran"
