"""Test del motore di rollback transazionale (Saga/WAL) dei piani multi-step."""
import time
from unittest.mock import patch

from app.agent.execution_log import ExecutionLog, execute_rollback_for_step, generate_rollback_plan_with_llm
from app.agent.graph import build_graph
from app.agent.tool_catalog import get_tool_catalog

PLAN_WITH_FAILING_LAST_STEP = {
    "steps": [
        {
            "id": 1,
            "tool": "proxmox-mcp__allocate_ip",
            "args": {"vmid": 200, "hostname": "test-rollback"},
            "output_var": "allocated_ip",
            "description": "Allocazione IP statico",
        },
        {
            "id": 2,
            "tool": "proxmox-mcp__create_lxc_from_template",
            "args": {"template_vmid": 100, "name": "test-rollback"},
            "output_var": "vmid",
            "depends_on": 1,
            "description": "Creazione container LXC",
        },
        {
            "id": 3,
            "tool": "proxmox-mcp__add_pihole_dns_record",
            "args": {"domain": "test-rollback.lab", "target_ip": "{{allocated_ip}}"},
            "depends_on": 2,
            "description": "Configurazione DNS Pi-hole",
        },
    ]
}


def _plan_state(thread_id: str, security_mode: str) -> dict:
    return {
        "task": "Test Rollback Execution",
        "thread_id": thread_id,
        "force_mode": "act",
        "execute": True,
        "security_mode": security_mode,
        "plan_structure": PLAN_WITH_FAILING_LAST_STEP,
        "memory_context": None,
        "mode": "",
        "plan": {},
        "tool_result": None,
        "final_response": "",
    }


def _run_plan(security_mode: str):
    """Esegue il piano con MetaMCP mockato; ritorna (tool forward chiamati, tool di rollback chiamati)."""
    forward_calls, rollback_calls = [], []

    def mock_call_tool(tool_name, arguments):
        if tool_name == "proxmox-mcp__allocate_ip":
            forward_calls.append(tool_name)
            return {"ip": "192.168.1.250", "status": "allocated"}
        if tool_name == "proxmox-mcp__create_lxc_from_template":
            forward_calls.append(tool_name)
            return {"vmid": 250, "status": "created"}
        if tool_name == "proxmox-mcp__add_pihole_dns_record":
            forward_calls.append(tool_name)
            return {"error": "Simulated Pi-hole API Timeout"}
        rollback_calls.append((tool_name, arguments))
        return {"status": "success"}

    thread_id = f"test_rollback_{security_mode}_{time.time_ns()}"
    with patch("app.agent.execution_log.get_mcp_hub") as get_hub:
        get_hub.return_value.call_tool.side_effect = mock_call_tool
        build_graph().invoke(_plan_state(thread_id, security_mode), config={"configurable": {"thread_id": thread_id}})
    return forward_calls, rollback_calls


def test_failed_plan_rolls_back_completed_steps_in_reverse_order():
    forward_calls, rollback_calls = _run_plan(security_mode="dangerous")

    assert len(forward_calls) == 3
    assert [name for name, _ in rollback_calls] == ["proxmox-mcp__stop_container", "proxmox-mcp__release_ip"]
    assert str(rollback_calls[0][1].get("vmid")) == "250"
    assert rollback_calls[1][1].get("ip") == "192.168.1.250"


def test_plan_respects_security_mode_approval_gate():
    # In modalità normal allocate_ip richiede approvazione: il piano si ferma prima di eseguire tool
    forward_calls, rollback_calls = _run_plan(security_mode="normal")

    assert forward_calls == []
    assert rollback_calls == []


def test_non_reversible_tool_is_skipped():
    log = ExecutionLog({"id": 1}, "proxmox-mcp__exec_lxc_command", {"vmid": 100, "command": "rm -rf /tmp/test"})
    log.result = {"output": "ok"}

    assert execute_rollback_for_step(log, get_tool_catalog()) is False
    assert log.rollback_error == "Tool non reversibile"


def test_llm_rollback_plan_uses_model_output():
    log = ExecutionLog({"id": 1}, "proxmox-mcp__exec_lxc_command", {"vmid": 100, "command": "rm -rf /tmp/test"})
    with patch("app.agent.llm_calls.call_llm", return_value={"content": "  1. Ripristina i file da backup  "}) as mock_llm:
        plan = generate_rollback_plan_with_llm([log], "Pulizia file temporanei", "Comando fallito a metà")

    mock_llm.assert_called_once()
    assert plan == "1. Ripristina i file da backup"


def test_execution_log_wal_structure():
    log = ExecutionLog({"id": 1}, "proxmox-mcp__exec_lxc_command", {"vmid": 100})
    data = log.to_dict()

    assert data["timestamp_start"] is not None
    assert data["tool_name"] == "proxmox-mcp__exec_lxc_command"
