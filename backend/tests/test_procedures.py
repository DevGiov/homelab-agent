"""Memoria procedurale: proposte, approvazione, uso nel catalogo e nella memoria di act e plan, distillazione."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.agent import procedure_distillation
from app.agent.nodes.retrieve_memory import retrieve_memory_node
from app.agent.procedure_distillation import ProcedureProposal, distill, worth_distilling
from app.agent.tool_catalog import format_catalog_for_prompt
from app.evals.suites import memory_sandbox
from app.memory import procedures, vector_store
from app.registry.memory import MemoryRegistry

CATALOG = [{"name": "proxmox-mcp__exec_lxc_command", "description": "Esegue un comando in un container", "parameters": {"properties": {"vmid": {}, "command": {}}}}]
NOTE = "Su CT 125 i servizi girano in Docker: riavviali con docker compose, non con systemctl."
TEMPLATE = "1. proxmox-mcp__allocate_ip\n2. proxmox-mcp__create_lxc_from_template con l'IP\n3. proxmox-mcp__add_pihole_dns_record per <hostname>"


@pytest.fixture
def sandbox():
    with memory_sandbox():
        yield


def _memory(mode, task="Crea un nuovo container per Jellyfin con DNS"):
    return retrieve_memory_node({"thread_id": "t", "task": task, "mode": mode})["memory_context"]


def test_proposals_are_not_used_until_approved(sandbox):
    note_id, created = procedures.propose("tool_note", "Riavvio su CT 125", NOTE, tool_name="proxmox-mcp__exec_lxc_command")
    template_id, _ = procedures.propose("plan_template", "Nuovo container con DNS", TEMPLATE)
    assert created and procedures.get_procedure(note_id)["status"] == "proposed"
    assert "NOTA APPROVATA" not in format_catalog_for_prompt(CATALOG)
    assert "Procedure approvate" not in _memory("plan")

    procedures.approve(note_id)
    procedures.approve(template_id)
    assert f"  NOTA APPROVATA: {NOTE}" in format_catalog_for_prompt(CATALOG)
    plan = _memory("plan")
    assert "**Nuovo container con DNS**" in plan and "<hostname>" in plan
    assert "Nuovo container con DNS" in _memory("act")
    assert "Procedure approvate" not in _memory("ask") and "Procedure approvate" not in (_memory("chat") or "")


def test_rejected_proposals_leave_memory_and_do_not_come_back(sandbox):
    template_id, _ = procedures.propose("plan_template", "Nuovo container con DNS", TEMPLATE)
    procedures.approve(template_id)
    assert vector_store.count_memory("procedure") == 1
    procedures.reject(template_id)
    assert vector_store.count_memory("procedure") == 0 and "Procedure approvate" not in _memory("plan")
    assert procedures.propose("plan_template", "Nuovo container con DNS", TEMPLATE) == (template_id, False)


def test_update_and_delete_keep_the_search_record_aligned(sandbox):
    procedure = procedures.create("plan_template", "Nuovo container con DNS", TEMPLATE)
    assert procedure["status"] == "approved" and procedure["source"] == "user"
    procedures.update(procedure["id"], "Backup notturno con vzdump", "1. vzdump su PBS alle 3:30", None)
    assert "Backup notturno" in _memory("plan", "Configura il backup notturno dei container")
    assert procedures.delete(procedure["id"]) and vector_store.count_memory("procedure") == 0
    with pytest.raises(ValueError):
        procedures.propose("tool_note", "Senza tool", NOTE)


def test_procedures_api_and_stats(sandbox):
    from app.api.main import api

    client = TestClient(api)
    proposed_id, _ = procedures.propose("tool_note", "Riavvio su CT 125", NOTE, tool_name="proxmox-mcp__exec_lxc_command")
    created = client.post("/v1/memory/procedures", json={"kind": "plan_template", "title": "Nuovo container", "content": TEMPLATE}).json()
    assert created["status"] == "approved"
    assert [p["id"] for p in client.get("/v1/memory/procedures").json()] == [proposed_id, created["id"]]  # proposte prima
    assert client.get("/v1/memory/stats").json()["procedures_proposed"] == 1

    assert client.post(f"/v1/memory/procedures/{proposed_id}/approve").json()["status"] == "approved"
    assert client.post(f"/v1/memory/procedures/{proposed_id}/reject").json()["status"] == "rejected"
    edited = client.put(f"/v1/memory/procedures/{created['id']}", json={"title": "Nuovo LXC", "content": TEMPLATE}).json()
    assert edited["title"] == "Nuovo LXC"
    assert client.post("/v1/memory/procedures", json={"kind": "tool_note", "title": "x", "content": "y"}).status_code == 400
    assert client.delete(f"/v1/memory/procedures/{created['id']}").status_code == 204
    assert client.post(f"/v1/memory/procedures/{created['id']}/approve").status_code == 404


def test_agent_tool_only_proposes(sandbox):
    registry = MemoryRegistry()
    result = registry.execute_tool("propose_procedure", {"kind": "tool_note", "title": "Riavvio", "content": NOTE, "tool_name": "proxmox-mcp__exec_lxc_command"})
    assert result["status"] == "proposed" and procedures.get_procedure(result["procedure_id"])["source"] == "agent"
    assert "NOTA APPROVATA" not in format_catalog_for_prompt(CATALOG)
    again = registry.execute_tool("propose_procedure", {"kind": "tool_note", "title": "Riavvio", "content": NOTE, "tool_name": "proxmox-mcp__exec_lxc_command"})
    assert again["procedure_id"] == result["procedure_id"] and "status" not in again
    assert "error" in registry.execute_tool("propose_procedure", {"kind": "tool_note", "title": "x", "content": "y"})


RECOVERED = [
    {"tool_name": "proxmox-mcp__exec_lxc_command", "args": {"vmid": 125, "command": "systemctl restart agent"}, "error": "Unit agent.service not found"},
    {"tool_name": "proxmox-mcp__exec_lxc_command", "args": {"vmid": 125, "command": "docker compose restart backend"}, "result": {"ok": True}},
]
READ_ONLY = [{"tool_name": "proxmox-mcp__list_containers", "args": {}}, {"tool_name": "proxmox-mcp__get_container_status", "args": {"vmid": 1}}]
CHANGE = [{"tool_name": "proxmox-mcp__allocate_ip", "args": {}}, {"tool_name": "proxmox-mcp__create_lxc_from_template", "args": {}}]


def test_only_instructive_executions_are_distilled():
    assert worth_distilling(RECOVERED) and worth_distilling(CHANGE)
    assert not worth_distilling(READ_ONLY)  # solo letture
    assert not worth_distilling(CHANGE[:1])  # un solo passo
    assert not worth_distilling([{**RECOVERED[0]}])  # errore non superato


def test_distillation_proposes_and_validates_the_tool(sandbox):
    note = ProcedureProposal(kind="tool_note", title="Riavvio su CT 125", content=NOTE, tool_name="proxmox-mcp__exec_lxc_command")
    with patch.object(procedure_distillation.llm_calls, "call_llm_structured", return_value=note) as llm:
        procedure_id = distill("Riavvia il backend", RECOVERED, "t1")
    assert "systemctl restart agent" in llm.call_args.args[0]
    procedure = procedures.get_procedure(procedure_id)
    assert (procedure["status"], procedure["source"], procedure["thread_id"]) == ("proposed", "execution", "t1")

    wrong_tool = ProcedureProposal(kind="tool_note", title="x", content="y", tool_name="proxmox-mcp__stop_container")
    with patch.object(procedure_distillation.llm_calls, "call_llm_structured", return_value=wrong_tool):
        assert distill("Riavvia il backend", RECOVERED, "t1") is None
    with patch.object(procedure_distillation.llm_calls, "call_llm_structured", return_value=ProcedureProposal(kind="none")):
        assert distill("Crea un container", CHANGE, "t1") is None
    with patch.object(procedure_distillation.llm_calls, "call_llm_structured") as llm:
        assert distill("Elenca i container", READ_ONLY, "t1") is None
    llm.assert_not_called()
