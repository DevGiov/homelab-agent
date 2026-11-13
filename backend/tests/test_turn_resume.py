"""Lavori sospesi su un'approvazione: il loop in chat, i piani, gli step agentici e le run riprendono da dove erano."""
import json
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.agent import turn_checkpoints
from app.agent.agent_loop import AgentLoop, run_agent_loop
from app.agent.execution_log import execute_plan, resume_plan
from app.agent.tool_schemas import ToolSelection
from app.automations.db import approvals as approvals_db
from app.automations.db import definitions as definitions_db
from app.automations.db import runs as runs_db
from app.automations.db import schema as schema_db
from app.automations.models import (
    AutomationDefinition,
    Budget,
    ExecutionPolicy,
    RunStatus,
    StepType,
    WorkflowSpec,
    WorkflowStepDefinition,
)
from app.automations.runner import AutomationRunner
from app.automations.steps import agentic
from app.automations.steps.base import StepContext
from app.evals.suites import memory_sandbox
from app.security import approvals

TOOLS = [{"name": name, "description": "", "parameters": {"type": "object", "properties": {}}}
         for name in ("list_containers", "stop_container", "start_container", "exec_command")]


@pytest.fixture
def sandbox():
    with memory_sandbox():
        yield


@pytest.fixture
def manager():
    mgr = MagicMock()
    mgr.get_tools_for_mode.return_value = TOOLS
    with patch("app.agent.agent_loop.get_registry_manager", return_value=mgr):
        yield mgr


def _approval(tool="stop_container"):
    req = approvals.create_approval_request(tool, {}, thread_id="t-1", mode="act", risk_reason="mutazione")
    return approvals.approval_response(req, "Confermi?")


def _call(tool, reasoning="serve"):
    return ToolSelection(tool_needed=True, tool_name=tool, arguments={}, reasoning=reasoning)


def _done(answer="Fatto: elencati e fermati i container."):
    return ToolSelection(tool_needed=False, final_answer=answer)


def _suspended_loop(manager, select):
    """Il loop fa `list_containers`, poi `stop_container` chiede conferma. Restituisce (richiesta, stato salvato)."""
    pending = _approval()
    manager.execute_tool.side_effect = [[{"vmid": 101}], pending]
    res = run_agent_loop("ferma il 101", "act", call_llm_fn=MagicMock(), call_llm_structured_fn=select, thread_id="t-1", meta={"model": "m"})
    assert res["approval_required"] and res["request_id"] == pending["request_id"]
    manager.execute_tool.side_effect = None
    return res["request_id"], turn_checkpoints.load(res["request_id"])


def _resume(checkpoint, select, llm=None):
    # Passa da JSON come dal database
    state = json.loads(json.dumps(checkpoint["state"]))
    return AgentLoop.restore(state, llm or MagicMock(return_value={"content": "sintesi"}), select)


# --- agent loop ---


def test_approved_tool_becomes_the_step_result_and_the_loop_continues(sandbox, manager):
    request_id, checkpoint = _suspended_loop(manager, MagicMock(side_effect=[_call("list_containers"), _call("stop_container")]))
    assert checkpoint["kind"] == "loop" and checkpoint["state"]["constructor"]["meta"] == {"model": "m"}

    manager.execute_tool.reset_mock()
    manager.execute_tool.return_value = {"status": "stopped"}
    select = MagicMock(side_effect=[_call("start_container"), _done()])
    res = _resume(checkpoint, select).resume(request_id, approved=True)

    assert res["final_response"].startswith("Fatto")
    first_call = manager.execute_tool.call_args_list[0]
    assert first_call.args[0] == "stop_container" and first_call.kwargs["approved_request"].request_id == request_id
    # Il modello riparte vedendo tutto il turno, senza richieste di approvazione aperte nella traccia
    assert "list_containers" in select.call_args_list[0].kwargs["prompt"] and "stopped" in select.call_args_list[0].kwargs["prompt"]
    assert [t["tool_name"] for t in res["execution_trace"]] == ["list_containers", "stop_container", "start_container"]
    assert not any(t.get("approval_required") for t in res["execution_trace"])


def test_a_denial_is_the_step_result_and_the_tool_does_not_run(sandbox, manager):
    request_id, checkpoint = _suspended_loop(manager, MagicMock(side_effect=[_call("list_containers"), _call("stop_container")]))
    manager.execute_tool.reset_mock()
    select = MagicMock(side_effect=[_done("Il 101 resta acceso: hai rifiutato lo stop.")])

    res = _resume(checkpoint, select).resume(request_id, approved=False)

    manager.execute_tool.assert_not_called()
    assert "DENIED" in select.call_args.kwargs["prompt"] and res["final_response"].startswith("Il 101")
    assert res["execution_trace"][-1]["error"] == "Rifiutato dall'utente"


def test_a_second_approval_suspends_the_loop_again(sandbox, manager):
    request_id, checkpoint = _suspended_loop(manager, MagicMock(side_effect=[_call("list_containers"), _call("stop_container")]))
    manager.execute_tool.return_value = {"status": "stopped"}
    second = _approval("exec_command")
    select = MagicMock(side_effect=[_call("exec_command")])
    loop = _resume(checkpoint, select)
    manager.execute_tool.side_effect = [{"status": "stopped"}, second]

    res = loop.resume(request_id, approved=True)

    assert res["approval_required"] and res["request_id"] == second["request_id"]
    assert turn_checkpoints.load(second["request_id"])["state"]["pending"]["tool_name"] == "exec_command"


def test_the_remaining_step_budget_is_kept(sandbox, manager):
    request_id, checkpoint = _suspended_loop(manager, MagicMock(side_effect=[_call("list_containers"), _call("stop_container")]))
    manager.execute_tool.return_value = {"status": "stopped"}
    checkpoint["state"]["constructor"]["max_tool_calls"] = 2  # i due passi sono già fatti: niente altre selezioni
    select, llm = MagicMock(), MagicMock(return_value={"content": "Sintesi finale."})

    res = _resume(checkpoint, select, llm).resume(request_id, approved=True)

    select.assert_not_called()
    assert res["final_response"] == "Sintesi finale."


def test_tools_outside_the_allowlist_are_hidden_and_rejected(sandbox, manager):
    manager.execute_tool.return_value = []
    select = MagicMock(side_effect=[_call("stop_container"), _call("list_containers"), _done()])
    loop = AgentLoop("elenca", "act", None, MagicMock(), select, None, None, None, "normal", allowed_tools={"list_containers"})

    assert [t["name"] for t in loop.available_tools] == ["list_containers"]
    res = loop.run()

    assert [c.args[0] for c in manager.execute_tool.call_args_list] == ["list_containers"]
    assert res["execution_trace"][0]["error"] == "Tool non consentito"


# --- API della chat ---


def _resolve(request_id, action="approve"):
    from app.api.main import api

    return TestClient(api).post(f"/v1/approvals/{request_id}/resolve", json={"action": action})


def _wait_for_assistant_message(thread_store, thread_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msgs = [m for m in thread_store.get_thread_messages(thread_id) if m.get("sender") == "assistant"]
        if msgs:
            return msgs[-1]
        time.sleep(0.02)
    raise AssertionError("Nessuna risposta salvata dopo la ripresa")


def _checkpointed_request():
    req = approvals.create_approval_request("stop_container", {}, thread_id="t-api", mode="act", risk_reason="mutazione")
    turn_checkpoints.save(req.request_id, "loop", {"constructor": {"meta": {"thread_id": "t-api", "task": "ferma", "mode": "act"}}})
    return req


@pytest.mark.parametrize("action, approved", [("approve", True), ("deny", False)])
def test_resolving_resumes_the_turn_in_a_stream_session(sandbox, action, approved):
    from app.memory import thread_store

    req = _checkpointed_request()
    with patch("app.api.agent_runner.resume_checkpoint", return_value={"final_response": "Turno finito.", "execution_trace": []}) as resume:
        res = _resolve(req.request_id, action)
        assert res.status_code == 200 and res.json()["resumed"] is True and res.json()["thread_id"] == "t-api"
        message = _wait_for_assistant_message(thread_store, "t-api")
    assert message["content"] == "Turno finito."
    assert resume.call_args.args[1:] == (req.request_id, approved)
    assert turn_checkpoints.load(req.request_id) is None


def test_resolving_is_refused_while_the_thread_is_busy(sandbox):
    req = _checkpointed_request()
    with patch("app.api.agent_runner.get_session", return_value=MagicMock(is_active=lambda: True)):
        assert _resolve(req.request_id).status_code == 409
    assert approvals.get_approval_request(req.request_id).status == "pending"


def test_an_expired_request_drops_the_saved_state(sandbox):
    req = _checkpointed_request()
    req.created_at -= approvals.APPROVAL_TTL_SECONDS + 1
    assert _resolve(req.request_id).status_code == 410
    assert turn_checkpoints.load(req.request_id) is None


# --- piani ---


PLAN = {"steps": [
    {"id": 1, "description": "Alloca", "tool": "proxmox-mcp__allocate_ip", "args": {}, "output_var": "ip"},
    {"id": 2, "description": "Crea", "tool": "proxmox-mcp__create_service", "args": {"ip": "{{ip}}"}},
    {"id": 3, "description": "DNS", "tool": "proxmox-mcp__add_pihole_dns_record", "args": {"ip": "{{ip}}"}},
]}


def _suspended_plan():
    """Il passo 2 chiede conferma: il passo 1 è fatto, nessun rollback."""
    guard = _approval("proxmox-mcp__create_service")
    registry = MagicMock()
    # I passi del piano passano dal ToolRegistryManager: il primo riesce, il secondo chiede conferma
    registry.execute_tool.side_effect = [{"ip": "192.168.1.50"}, guard]
    with patch("app.agent.execution_log.get_registry_manager", return_value=registry), \
            patch("app.agent.execution_log.execute_rollback_for_step") as rollback:
        res = execute_plan(PLAN, task="nuovo servizio", thread_id="t-1", security_mode="normal", model=None, meta={"thread_id": "t-1"})
    rollback.assert_not_called()
    assert res["approval_required"] and res["execution_trace"][-1]["request_id"] == guard["request_id"]
    assert "⏸️" in res["final_response"] and "Rollback" not in res["final_response"]
    return guard["request_id"], json.loads(json.dumps(turn_checkpoints.load(guard["request_id"])))


def test_an_approval_suspends_the_plan_and_it_resumes_from_that_step(sandbox):
    request_id, checkpoint = _suspended_plan()
    assert checkpoint["kind"] == "plan"
    registry = MagicMock()
    registry.execute_tool.side_effect = [{"vmid": 150}, {"status": "ok"}]
    with patch("app.agent.execution_log.get_registry_manager", return_value=registry):
        res = resume_plan(checkpoint["state"], request_id, approved=True)

    # Il passo approvato usa gli argomenti risolti, il successivo riceve la variabile del primo
    approved_call, next_call = registry.execute_tool.call_args_list
    assert approved_call.args[:2] == ("proxmox-mcp__create_service", {"ip": "192.168.1.50"})
    assert approved_call.kwargs["approved_request"].request_id == request_id
    assert next_call.args[:2] == ("proxmox-mcp__add_pihole_dns_record", {"ip": "192.168.1.50"})
    assert "approved_request" not in next_call.kwargs
    assert "Tutti i passaggi" in res["final_response"] and "⏸️" not in res["final_response"]
    assert [t["step_id"] for t in res["execution_trace"]] == [1, 2, 3] and not res.get("approval_required")


def test_a_denied_plan_step_rolls_back_the_completed_steps(sandbox):
    request_id, checkpoint = _suspended_plan()
    with patch("app.agent.execution_log.execute_rollback_for_step", return_value=True) as rollback, \
            patch("app.agent.execution_log.get_tool_catalog", return_value=[]):
        res = resume_plan(checkpoint["state"], request_id, approved=False)
    assert [c.args[0].tool_name for c in rollback.call_args_list] == ["proxmox-mcp__allocate_ip"]
    assert "Rifiutato dall'utente" in res["final_response"] and "Rollback" in res["final_response"]


# --- step agentici e run ---


@pytest.fixture
def automations_db():
    with memory_sandbox():
        schema_db.init_automations_db()
        yield


def _agentic_automation(tools=None, allowed=("list_containers", "stop_container"), budget=25):
    step = WorkflowStepDefinition(step_id="agente", name="Agente", type=StepType.AGENTIC_TASK, prompt_template="Ferma il 101", tools=tools)
    return AutomationDefinition(
        id="auto_agente", name="Agente", workflow=WorkflowSpec(initial_step_id="agente", steps=[step]),
        permission_policy=ExecutionPolicy(allowed_tools=list(allowed), allowed_registries=["mcp"]), budget=Budget(max_tool_calls=budget))


def _agentic_ctx(automation, manager):
    return StepContext(step=automation.workflow.steps[0], automation=automation, run=MagicMock(is_dry_run=False, run_id="r", associated_thread_id=None),
                       data={}, registry_manager=manager)


@pytest.fixture
def structured():
    """La selezione dei tool e la sintesi degli step agentici, senza modello."""
    select = MagicMock()
    fns = {"call_llm_fn": MagicMock(return_value={"content": "Sintesi."}), "call_llm_structured_fn": select, "interleaved": False}
    with patch.object(agentic.llm_calls, "agent_loop_llm_fns", return_value=fns), patch.object(agentic, "resolve_model", return_value=None):
        yield select


def test_agentic_step_calls_tools_within_the_policy_and_the_budget(automations_db, manager, structured):
    manager.execute_tool.return_value = [{"vmid": 101}]
    structured.side_effect = [_call("list_containers"), _done("Il 101 è attivo.")]
    automation = _agentic_automation()

    outcome = agentic.run(_agentic_ctx(automation, manager))

    assert outcome["status"] == RunStatus.COMPLETED and outcome["output"]["text"] == "Il 101 è attivo."
    assert outcome["tool_calls"][0]["tool_name"] == "list_containers"
    call = manager.execute_tool.call_args
    assert call.args[2] == ["mcp"] and call.kwargs["run_id"] == "r" and call.kwargs["automation_id"] == "auto_agente"
    assert "exec_command" not in structured.call_args.kwargs["system_prompt"]


@pytest.mark.parametrize("step_tools, allowed, expected", [
    (None, ("list_containers",), {"list_containers"}),
    (["list_containers", "exec_command"], ("list_containers", "stop_container"), {"list_containers"}),  # dentro la policy
    ([], ("list_containers",), set()),
    (None, (), {"list_containers", "stop_container", "start_container", "exec_command"}),
])
def test_step_tool_scope(manager, step_tools, allowed, expected):
    assert agentic._tool_scope(_agentic_ctx(_agentic_automation(step_tools, allowed), manager)) == expected


def test_scope_without_allowlist_excludes_automation_management(manager):
    manager.get_tools_for_mode.return_value = [*TOOLS, {"name": "trigger_automation_run"}]
    assert "trigger_automation_run" not in agentic._tool_scope(_agentic_ctx(_agentic_automation(None, ()), manager))


def test_agentic_step_without_tools_answers_directly(automations_db, manager, structured):
    outcome = agentic.run(_agentic_ctx(_agentic_automation(tools=[]), manager))
    structured.assert_not_called()
    assert outcome["output"]["text"] == "Sintesi."


def test_agentic_step_fails_when_the_model_is_unavailable(automations_db, manager, structured):
    from app.llm.providers import LLMUnavailableError

    structured.side_effect = LLMUnavailableError("timeout")
    assert agentic.run(_agentic_ctx(_agentic_automation(), manager))["status"] == RunStatus.FAILED


def _runner_with(automation, manager):
    runner = AutomationRunner()
    runner.registry_manager = manager
    definitions_db.save_definition(automation.model_dump(mode="json"))
    return runner


def test_run_suspends_inside_an_agentic_step_and_resumes_the_loop(automations_db, manager, structured):
    guard = _approval()
    manager.execute_tool.side_effect = [guard]
    structured.side_effect = [_call("stop_container")]
    runner = _runner_with(_agentic_automation(), manager)

    run = runner.execute_run(runner.start_run("auto_agente").run_id)

    assert run.status == RunStatus.WAITING_APPROVAL and run.pending_approval_id == guard["request_id"]
    # La richiesta è della run, con la sua scadenza: la UI la instrada al runner
    stored = approvals_db.get_automation_approval(guard["request_id"])
    assert stored["run_id"] == run.run_id and approvals.get_approval_request(guard["request_id"]).ttl_seconds == approvals.RUN_APPROVAL_TTL_SECONDS

    manager.execute_tool.side_effect = [{"status": "stopped"}]
    structured.side_effect = [_done("Il 101 è fermo.")]
    resumed = runner.resume_run(run.run_id, guard["request_id"], action="approve")

    assert resumed.status == RunStatus.COMPLETED
    assert manager.execute_tool.call_args.kwargs["approved_request"].request_id == guard["request_id"]
    assert resumed.step_runs[-1].output_payload["text"] == "Il 101 è fermo."
    assert turn_checkpoints.load(guard["request_id"]) is None


def test_a_denial_inside_an_agentic_step_reaches_the_model_and_the_run_completes(automations_db, manager, structured):
    guard = _approval()
    manager.execute_tool.side_effect = [guard]
    structured.side_effect = [_call("stop_container")]
    runner = _runner_with(_agentic_automation(), manager)
    run = runner.execute_run(runner.start_run("auto_agente").run_id)

    structured.side_effect = [_done("Non ho fermato il 101: azione rifiutata.")]
    resumed = runner.resume_run(run.run_id, guard["request_id"], action="deny")

    assert resumed.status == RunStatus.COMPLETED and "DENIED" in structured.call_args.kwargs["prompt"]


def _tool_automation(requires_approval):
    step = WorkflowStepDefinition(step_id="ferma", name="Ferma", type=StepType.DETERMINISTIC_ACTION, action_or_tool="stop_container",
                                  parameters={"vmid": 101}, requires_approval=requires_approval)
    after = WorkflowStepDefinition(step_id="dopo", name="Dopo", type=StepType.DETERMINISTIC_ACTION, action_or_tool="list_containers")
    return AutomationDefinition(id="auto_tool", name="Tool", workflow=WorkflowSpec(initial_step_id="ferma", steps=[step, after]),
                                permission_policy=ExecutionPolicy(allowed_tools=["stop_container", "list_containers"]))


def test_approving_a_gated_step_runs_its_tool(automations_db):
    manager = MagicMock()
    manager.execute_tool.return_value = {"status": "stopped"}
    runner = _runner_with(_tool_automation(requires_approval=True), manager)
    run = runner.execute_run(runner.start_run("auto_tool").run_id)
    assert run.status == RunStatus.WAITING_APPROVAL
    manager.execute_tool.assert_not_called()

    resumed = runner.resume_run(run.run_id, run.pending_approval_id, action="approve")

    assert resumed.status == RunStatus.COMPLETED
    assert [c.args[0] for c in manager.execute_tool.call_args_list] == ["stop_container", "list_containers"]
    assert next(s for s in resumed.step_runs if s.step_id == "ferma").output_payload == {"status": "stopped"}


def test_a_guardrail_request_belongs_to_the_run_and_approving_it_resumes_it(automations_db):
    from app.api.main import api

    guard = _approval()
    manager = MagicMock()
    manager.execute_tool.side_effect = [guard, {"status": "stopped"}, []]
    runner = _runner_with(_tool_automation(requires_approval=False), manager)
    run = runner.execute_run(runner.start_run("auto_tool").run_id)
    assert run.status == RunStatus.WAITING_APPROVAL and approvals_db.get_automation_approval(guard["request_id"])["run_id"] == run.run_id

    with patch("app.automations.routes.approvals.get_runner", return_value=runner):
        res = TestClient(api).post(f"/v1/automations/runs/{run.run_id}/approvals/{guard['request_id']}/resolve",
                                   params={"sync": True}, json={"action": "approve"})

    assert res.status_code == 200 and res.json()["status"] == RunStatus.COMPLETED.value
    assert manager.execute_tool.call_args_list[1].kwargs["approved_request"].request_id == guard["request_id"]
    assert runs_db.get_run(run.run_id)["status"] == RunStatus.COMPLETED.value


def test_denying_a_tool_step_blocks_the_run(automations_db):
    manager = MagicMock()
    runner = _runner_with(_tool_automation(requires_approval=True), manager)
    run = runner.execute_run(runner.start_run("auto_tool").run_id)
    assert runner.resume_run(run.run_id, run.pending_approval_id, action="deny").status == RunStatus.BLOCKED
    manager.execute_tool.assert_not_called()
