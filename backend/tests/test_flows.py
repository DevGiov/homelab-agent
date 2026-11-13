"""Sensibilità dei dati, fase S1: etichette, propagazione e controllo delle uscite (app.security.flows).

Valori inventati: nessun indirizzo o nome di un'installazione reale."""
import ipaddress
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from app.agent.agent_loop import AgentLoop
from app.agent.nodes import retrieve_memory as memory_node
from app.agent.nodes.web_prefetch import web_prefetch_node
from app.agent.tool_schemas import ToolSelection
from app.api import agent_runner
from app.automations.models import AutomationRun, StepRun
from app.automations.runner import _step_tag, _trigger_tag
from app.core.config import settings
from app.llm.providers import LLMProvider
from app.memory import profile, thread_store
from app.registry.manager import get_registry_manager
from app.security import approvals, audit_log, flows, permissions
from app.security.flows import PUBLIC_TAG, FlowDenied, Label, Tag, join, tag_of

PRIVATE = tag_of("private", "memoria:fatto")
INTERNAL = tag_of("internal", "tool:list_things")
FAKE_SEARCH = {"query": "q", "success": True, "provider_used": "Finto", "latency_ms": 1,
               "sources": [{"title": "t", "url": "https://example.org/a", "snippet": "s"}],
               "summary_text": "sintesi", "error": None}


@pytest.fixture(autouse=True)
def _clean():
    flows.init_flows_db()
    yield
    with permissions._session_lock:
        permissions._SESSION_PERMISSIONS.clear()
    with approvals._approval_lock:
        approvals._APPROVALS.clear()
    for scope in list(flows.mcp_flow_settings()):
        flows.delete_mcp_flow_setting(scope)


# --- Etichette e controllo ------------------------------------------------------------------------

def test_join_keeps_the_highest_label_its_reasons_and_untrusted():
    tag = join(tag_of("public", "tool:web_search", untrusted=True), INTERNAL, PRIVATE)
    assert tag.label == Label.PRIVATE and tag.untrusted
    assert "memoria:fatto" in tag.reasons and "untrusted:tool:web_search" in tag.reasons
    assert "tool:list_things" not in tag.reasons  # motivo di un'etichetta più bassa
    assert join() == PUBLIC_TAG and join(None, {}) == PUBLIC_TAG
    assert join(tag.to_dict()) == tag


def test_can_flow_respects_clearance_and_never_lets_a_secret_out():
    assert flows.can_flow(INTERNAL, flows.SEARCH_DESTINATION).allowed is False
    assert flows.can_flow(PUBLIC_TAG, flows.SEARCH_DESTINATION).allowed is True
    secret = tag_of("secret", "segreto")
    assert flows.can_flow(secret, flows.Destination("x", "model", Label.PRIVATE)).allowed is False
    assert "ammette al massimo public" in flows.can_flow(PRIVATE, flows.SEARCH_DESTINATION).reason


def test_label_parse():
    assert Label.parse("Private") == Label.PRIVATE and Label.parse(1) == Label.INTERNAL
    assert Label.parse("boh", Label.PUBLIC) == Label.PUBLIC
    with pytest.raises(ValueError):
        Label.parse("boh")


# --- Provider -------------------------------------------------------------------------------------

class _FakeProvider(LLMProvider):
    name = "llamacpp"

    def __init__(self):
        self.calls = []

    def _chat(self, messages, **kw):
        self.calls.append(messages)
        return {"content": "ok", "reasoning_content": "", "metrics": {}}

    def health(self):
        return True

    def list_models(self):
        return []


def test_provider_refuses_a_secret_and_records_label_and_destination():
    provider = _FakeProvider()
    with pytest.raises(FlowDenied):
        provider.chat([{"role": "user", "content": "x"}], tag=tag_of("secret", "segreto"), model="m")
    assert provider.calls == []

    provider.chat([{"role": "user", "content": "x"}], tag=PRIVATE, model="m-flows-test")
    with sqlite3.connect(settings.metrics_db_path) as conn:
        row = conn.execute("SELECT label, destination FROM llm_calls WHERE model = 'm-flows-test' ORDER BY id DESC").fetchone()
    assert row == ("private", "provider:llamacpp")


def test_provider_clearance_comes_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "llama_cpp_clearance", "internal")
    with pytest.raises(FlowDenied):
        _FakeProvider().chat([{"role": "user", "content": "x"}], tag=PRIVATE, model="m")
    _FakeProvider().chat([{"role": "user", "content": "x"}], tag=INTERNAL, model="m")


# --- Regole dei tool ------------------------------------------------------------------------------

def test_result_tags_of_builtin_tools():
    assert flows.result_tag("web_search") == Tag(Label.PUBLIC, True, ("tool:web_search", "untrusted:tool:web_search"))
    assert flows.result_tag("recall_memory").label == Label.PRIVATE
    assert flows.result_tag("email_fetch_unread").untrusted
    kb = {"results": [{"filename": "a", "sensitivity": "public"}, {"filename": "b", "sensitivity": "private"}]}
    assert flows.result_tag("knowledge_search", {}, kb).label == Label.PRIVATE
    assert flows.result_tag("knowledge_search", {}, {"results": []}).label == Label.INTERNAL


def test_unclassified_mcp_server_is_the_strictest_and_classification_changes_it():
    assert flows.result_tag("files__read").label == Label.PRIVATE
    assert flows.destination_for_tool("files__read", {}).clearance == Label.PUBLIC

    flows.save_mcp_flow_setting("files", "internal", "private")
    assert flows.result_tag("files__read").label == Label.INTERNAL
    assert flows.destination_for_tool("files__read", {}) == flows.Destination("mcp:files", "mcp", Label.PRIVATE)
    # Output di comandi e log restano privati anche con il server classificato più in basso (decisione 2)
    assert flows.result_tag("files__exec_lxc_command").label == Label.PRIVATE
    # La regola per tool vince su quella del server
    flows.save_mcp_flow_setting("files__read", "public", "public", untrusted=True)
    assert flows.result_tag("files__read") == tag_of("public", "tool:files__read", untrusted=True)
    with pytest.raises(ValueError):
        flows.save_mcp_flow_setting("files", "private", "secret")


def test_destinations_of_builtin_tools(monkeypatch):
    monkeypatch.setattr("app.registry.search_security.resolve_hostname_ips",
                        lambda h: [ipaddress.ip_address("192.168.50.10" if h.endswith(".home.example") else "93.184.216.34")])
    assert flows.destination_for_tool("web_search", {"query": "x"}) == flows.SEARCH_DESTINATION
    assert flows.destination_for_tool("http_get", {"url": "https://api.example.org/x"}).clearance == Label.PUBLIC
    assert flows.destination_for_tool("http_get", {"url": "http://nas.home.example/"}).clearance == Label.PRIVATE
    assert flows.destination_for_tool("inspect_image", {"image_path_or_url": "/v1/uploads/a.png"}) is None
    assert flows.destination_for_tool("recall_memory", {"query": "x"}) is None


# --- Controllo nel gestore dei tool ---------------------------------------------------------------

def _search(tag, thread_id="t-flows", **kw):
    with patch("app.registry.web_search.execute_search", return_value=FAKE_SEARCH) as fake:
        res = get_registry_manager().execute_tool("web_search", {"query": "nome della persona"}, ["web"],
                                                  thread_id=thread_id, tag=tag, **kw)
    return res, fake


def test_public_data_goes_to_the_search_and_the_audit_records_the_flow():
    res, fake = _search(PUBLIC_TAG, thread_id="t-flow-allow")
    assert fake.called and "result" in res
    row = audit_log.get_recent(limit=1, thread_id="t-flow-allow")[0]
    assert (row["label"], row["destination"], row["flow"]) == ("public", "search:web", "allow")


def test_private_data_asks_before_reaching_the_search_showing_the_query():
    res, fake = _search(PRIVATE, thread_id="t-flow-ask")
    assert not fake.called
    assert res["approval_required"] and res["command_prefix"] == "flow:search:web:private"
    assert res["command_preview"] == "Ricerca: nome della persona"
    assert "memoria:fatto" in res["risk_reason"]
    row = audit_log.get_recent(limit=1, thread_id="t-flow-ask")[0]
    assert row["flow"] == "ask"


def test_no_security_mode_skips_the_data_exit_check():
    res, fake = _search(PRIVATE, thread_id="t-flow-dangerous", security_mode="dangerous")
    assert res.get("approval_required") and not fake.called


def test_a_secret_is_blocked_outright():
    res, fake = _search(tag_of("secret", "segreto"), thread_id="t-flow-secret")
    assert res.get("blocked_by_flow") and not fake.called
    assert "segreto" in flows.can_flow(tag_of("secret", "x"), flows.Destination("d", "model", Label.PRIVATE)).reason


def test_an_approval_given_for_something_else_does_not_open_a_data_exit():
    """Una conferma del guardrail (o di un'altra uscita) non autorizza l'invio di questi dati a questa destinazione."""
    other = approvals.create_approval_request("web_search", {"query": "x"}, thread_id="t-flow-other-approval",
                                              command_prefix="flow:search:web:internal")
    approvals.resolve_approval(other.request_id, "approve")
    res, fake = _search(PRIVATE, thread_id="t-flow-other-approval", approved_request=approvals.get_approval_request(other.request_id))
    assert res.get("approval_required") and not fake.called


def test_approval_once_runs_that_call_only():
    res, _ = _search(PRIVATE, thread_id="t-flow-once")
    approvals.resolve_approval(res["request_id"], "approve")
    req = approvals.get_approval_request(res["request_id"])
    out, fake = _search(PRIVATE, thread_id="t-flow-once", approved_request=req)
    assert fake.called and "result" in out
    again, _ = _search(PRIVATE, thread_id="t-flow-once")
    assert again.get("approval_required")


def test_thread_permission_holds_for_that_label_and_thread_but_not_after_untrusted_content():
    res, _ = _search(PRIVATE, thread_id="t-flow-thread")
    approvals.resolve_approval(res["request_id"], "approve_thread")
    out, fake = _search(PRIVATE, thread_id="t-flow-thread")
    assert fake.called and "result" in out
    # Altro thread: chiede
    assert _search(PRIVATE, thread_id="t-flow-other")[0].get("approval_required")
    # Stesso thread, ma il turno ha letto contenuto non attendibile (decisione 6): chiede
    untrusted = join(PRIVATE, tag_of("public", "tool:web_search", untrusted=True))
    asked, _ = _search(untrusted, thread_id="t-flow-thread")
    assert asked.get("approval_required") and "non attendibile" in asked["risk_reason"]
    # Il permesso per l'uscita di dati non sblocca il tool in sé
    assert not permissions.is_tool_level_approved("web_search", thread_id="t-flow-thread")


def test_always_on_a_data_exit_counts_for_the_chat_only():
    res, _ = _search(PRIVATE, thread_id="t-flow-always")
    approvals.resolve_approval(res["request_id"], "approve_always")
    always = permissions.list_granted_permissions()["always"]
    assert not any(str(p.get("command_prefix") or "").startswith("flow:") for p in always)
    out, fake = _search(PRIVATE, thread_id="t-flow-always")
    assert fake.called


def test_tools_without_a_destination_are_not_checked():
    res = get_registry_manager().execute_tool("save_artifact", {"title": "x", "content": "y"}, ["automations"],
                                              thread_id="t-flow-local", tag=tag_of("private", "x"))
    assert not (isinstance(res, dict) and res.get("approval_required"))


# --- Agent loop -----------------------------------------------------------------------------------

TOOLS = [
    {"name": "recall_memory", "description": "", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}},
    {"name": "web_search", "description": "", "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                                                             "required": ["query"]}},
]


@pytest.fixture
def manager():
    mgr = MagicMock()
    mgr.get_tools_for_mode.return_value = TOOLS
    with patch("app.agent.agent_loop.get_registry_manager", return_value=mgr):
        yield mgr


def _llm():
    return MagicMock(return_value={"content": "risposta finale", "reasoning_content": ""})


def test_the_loop_tag_rises_with_what_it_reads_and_goes_with_the_next_call(manager):
    manager.execute_tool.side_effect = [{"facts": ["Ada vive a Esempiopoli"]}, {"result": "ok"}]
    select = MagicMock(side_effect=[
        ToolSelection(tool_needed=True, tool_name="recall_memory", arguments={"query": "Ada"}),
        ToolSelection(tool_needed=True, tool_name="web_search", arguments={"query": "Esempiopoli"}),
        ToolSelection(tool_needed=False, final_answer="Risposta finale abbastanza lunga da essere accettata."),
    ])
    loop = AgentLoop("cerca", "ask", None, _llm(), select, "t-loop", None, None, "normal", tag=PUBLIC_TAG)
    res = loop.run()

    first, second = manager.execute_tool.call_args_list
    assert first.kwargs["tag"].label == Label.PUBLIC
    assert second.kwargs["tag"].label == Label.PRIVATE  # dopo aver letto la memoria
    assert select.call_args_list[1].kwargs["tag"].label == Label.PRIVATE
    assert res["tag"]["label"] == "private"


def test_secrets_in_tool_results_never_reach_the_context(manager):
    manager.execute_tool.return_value = {"output": "token=sk-proj-abcdefghijklmnopqrstuvwx123456"}
    select = MagicMock(side_effect=[
        ToolSelection(tool_needed=True, tool_name="recall_memory", arguments={"query": "x"}),
        ToolSelection(tool_needed=False, final_answer="Risposta finale abbastanza lunga da essere accettata."),
    ])
    loop = AgentLoop("x", "ask", None, _llm(), select, "t-loop-secret", None, None, "normal")
    loop.run()
    assert all("sk-proj-" not in o for o in loop.observations)
    assert any("[RIMOSSO: segreto]" in o for o in loop.observations)


def test_parallel_calls_that_would_need_a_data_exit_approval_run_one_at_a_time(manager):
    manager.execute_tool.return_value = {"result": "ok"}
    parallel = [{"tool_name": "web_search", "arguments": {"query": "a"}},
                {"tool_name": "web_search", "arguments": {"query": "b"}}]
    select = MagicMock(side_effect=[
        ToolSelection(tool_needed=True, tool_name="web_search", arguments={"query": "a"}, parallel_calls=parallel),
        ToolSelection(tool_needed=False, final_answer="Risposta finale abbastanza lunga da essere accettata."),
    ])
    AgentLoop("x", "ask", None, _llm(), select, "t-par", None, None, "normal", tag=PRIVATE).run()
    manager.execute_tools_parallel.assert_not_called()


def test_checkpoint_keeps_the_raised_tag(manager):
    loop = AgentLoop("x", "act", None, _llm(), MagicMock(), "t-ckpt", None, None, "normal", tag=PUBLIC_TAG)
    loop.tag = PRIVATE
    restored = AgentLoop.restore(loop.checkpoint({"step_id": 1, "tool_name": "web_search", "arguments": {}, "reasoning": None}),
                                 _llm(), MagicMock())
    assert restored.tag.label == Label.PRIVATE


# --- Prefetch e memoria ---------------------------------------------------------------------------

def test_prefetch_does_not_run_when_the_query_is_not_public():
    with patch("app.registry.web_search.execute_search", return_value=FAKE_SEARCH) as fake:
        res = web_prefetch_node({"task": "cerca", "web_search": "on", "thread_id": "t-pf", "mode": "ask",
                                 "tag": PRIVATE.to_dict()})
    assert not fake.called
    assert res["web_prefetch_data"] is None and res["web_prefetch_metadata"]["error"] == "sensitive"


def test_prefetch_with_public_data_brings_untrusted_web_content():
    with patch("app.registry.web_search.execute_search", return_value=FAKE_SEARCH):
        res = web_prefetch_node({"task": "cerca", "web_search": "on", "thread_id": "t-pf2", "mode": "ask",
                                 "tag": PUBLIC_TAG.to_dict()})
    assert res["tag"]["untrusted"] is True and res["tag"]["label"] == "public"


def test_router_query_uses_the_routing_tag():
    """La query scritta dal router porta il tag dei messaggi che il router ha visto."""
    state = {"task": "cerca", "web_search": "on", "thread_id": "t-pf3", "mode": "ask", "tag": PUBLIC_TAG.to_dict(),
             "routing_tag": INTERNAL.to_dict(), "route_decision": {"web_search_query": "query del router"}}
    with patch("app.registry.web_search.execute_search", return_value=FAKE_SEARCH) as fake:
        res = web_prefetch_node(state)
    assert not fake.called and res["web_prefetch_metadata"]["label"] == "internal"


def test_memory_context_tag_includes_the_profile_and_saved_message_labels():
    thread = "t-mem-flows"
    thread_store.save_user_message(thread, "messaggio interno", user_msg_id="u1", sensitivity="internal")
    thread_store.save_assistant_message(thread, {"response": "risposta", "sensitivity": {"label": "internal"}}, ast_msg_id="a1")
    state = {"thread_id": thread, "task": "nuova domanda", "mode": "chat", "tag": PUBLIC_TAG.to_dict()}
    assert memory_node.recent_turns_node(state)["routing_tag"]["label"] == "internal"

    previous = profile.get_profile()["content"]
    try:
        profile.save_profile("Profilo inventato per il test.")
        res = memory_node.retrieve_memory_node(state)
        assert res["tag"]["label"] == "private" and "memoria:profilo" in res["tag"]["reasons"]
    finally:
        profile.save_profile(previous or "")
    history = thread_store.get_history(thread)
    assert [m["sensitivity"] for m in history] == ["internal", "internal"]


def test_input_tag_uses_the_conversation_level_and_the_detectors():
    thread = "t-input-flows"
    tag = agent_runner._input_tag(thread, "ciao", None, "internal", incognito=False)
    assert tag.label == Label.INTERNAL and thread_store.get_thread_sensitivity(thread) == "internal"
    # Il livello resta per i messaggi successivi
    assert agent_runner._input_tag(thread, "ciao", None, None, incognito=False).label == Label.INTERNAL
    # Un IBAN alza il messaggio a private; un segreto scritto dall'utente resta private, non secret
    assert agent_runner._input_tag("t-input-2", "IBAN GB82 WEST 1234 5698 7654 32", None, None, False).label == Label.PRIVATE
    assert agent_runner._input_tag("t-input-3", "password=Segretissima123", None, None, False).label == Label.PRIVATE
    assert agent_runner._input_tag("t-input-4", "guarda", ["data:image/png;base64,AA"], None, False).untrusted


# --- Automazioni ----------------------------------------------------------------------------------

def test_automation_run_tag_comes_from_what_the_steps_read():
    webhook = AutomationRun(run_id="r1", automation_id="a1", trigger_type="webhook", trigger_payload={"x": 1})
    assert _trigger_tag(webhook) == tag_of("internal", "automazione:webhook", untrusted=True)
    step = StepRun(step_run_id="s1", run_id="r1", step_id="step_1", status="completed",
                   tool_calls=[{"tool_name": "email_fetch_unread", "args": {}, "result": {"emails": []}}])
    assert _step_tag(step).label == Label.PRIVATE
    agentic = StepRun(step_run_id="s2", run_id="r1", step_id="step_2", status="completed", output_payload={"sensitivity": INTERNAL.to_dict()})
    assert _step_tag(agentic).label == Label.INTERNAL


def test_calendar_feed_chosen_by_the_model_follows_the_network_rules():
    """Come http_get: un host della rete locale fuori lista è bloccato in ogni modalità."""
    with patch("app.calendar.sync.fetch_and_sync_ical_feed") as fetch:
        res = get_registry_manager().execute_tool(
            "calendar_import_feed", {"url": "webcal://10.0.0.5/feed.ics", "name": "Prova"}, ["calendar"],
            thread_id="t-feed", security_mode="dangerous")
    assert res.get("blocked") and not fetch.called
