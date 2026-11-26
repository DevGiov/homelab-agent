"""Ruoli delle chiamate al modello: obbligatori, validati, controllati nel codice, nelle metriche e nel riepilogo."""
import ast
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.agent import llm_calls
from app.agent.agent_loop import AgentLoop, ToolSelection
from app.core.config import settings
from app.llm import roles
from app.llm.providers import OpenAICompatProvider
from app.observability import report, store
from app.observability.turns import record_llm_call
from app.security.flows import PUBLIC_TAG

APP = Path(__file__).resolve().parents[1] / "app"
MESSAGES = [{"role": "user", "content": "ciao"}]


@pytest.fixture(autouse=True)
def metrics_db():
    Path(settings.metrics_db_path).unlink(missing_ok=True)
    store.init_metrics_db()


def _provider():
    provider = OpenAICompatProvider("http://localhost:8080/v1", default_model="m")
    provider._chat = lambda *a, **k: {"content": "ok", "metrics": {}}
    return provider


def llm_rows():
    return store.select("SELECT * FROM llm_calls ORDER BY id")


# --- Obbligatorio e validato ---------------------------------------------------------------------

def test_role_names_cover_the_design_table():
    assert roles.VALID_ROLES == {"route", "plan", "select_tool", "rewrite_exit", "answer", "prefetch", "summarize",
                                 "consolidate", "title", "vision", "rollback", "eval"}
    assert all(roles.ROLE_DESCRIPTIONS[r].strip() for r in roles.VALID_ROLES)


def test_chat_without_a_role_fails():
    with pytest.raises(TypeError):
        _provider().chat(MESSAGES, tag=PUBLIC_TAG)


def test_chat_with_an_unknown_role_fails_before_the_request():
    provider = _provider()
    provider._chat = MagicMock()
    with pytest.raises(ValueError, match="sconosciuto"):
        provider.chat(MESSAGES, tag=PUBLIC_TAG, role="boh")
    provider._chat.assert_not_called()
    assert llm_rows() == []


def test_call_llm_and_structured_without_a_role_fail():
    with patch.object(llm_calls, "get_provider", return_value=MagicMock()):
        with pytest.raises(TypeError):
            llm_calls.call_llm("ciao", tag=PUBLIC_TAG)
        with pytest.raises(TypeError):
            llm_calls.call_llm_structured("ciao", "sys", ToolSelection, tag=PUBLIC_TAG)


def test_call_llm_passes_the_role_to_the_provider_and_unknown_ones_fail():
    provider = MagicMock()
    provider.effective_model.return_value = "m"
    provider.chat.return_value = {"content": "ok"}
    with patch.object(llm_calls, "get_provider", return_value=provider):
        llm_calls.call_llm("ciao", stream_mode="none", tag=PUBLIC_TAG, role="plan")
        assert provider.chat.call_args.kwargs["role"] == "plan"
        llm_calls.call_llm_structured("ciao", "sys", ToolSelection, tag=PUBLIC_TAG, role="select_tool", max_retries=1)
        assert provider.chat.call_args.kwargs["role"] == "select_tool"
    with pytest.raises(ValueError):
        _provider().chat(MESSAGES, tag=PUBLIC_TAG, role="")


def test_loop_functions_forward_the_role_chosen_at_each_call():
    provider = MagicMock()
    provider.effective_model.return_value = "m"
    provider.chat.return_value = {"content": "{}"}
    with patch.object(llm_calls, "get_provider", return_value=provider):
        fns = llm_calls.agent_loop_llm_fns(None, None, None)
        fns["call_llm_fn"]("x", tag=PUBLIC_TAG, role="eval")
        assert provider.chat.call_args.kwargs["role"] == "eval"
        fns["call_llm_structured_fn"]("x", "sys", ToolSelection, max_retries=1, tag=PUBLIC_TAG, role="rewrite_exit")
        assert provider.chat.call_args.kwargs["role"] == "rewrite_exit"
        with pytest.raises(TypeError):
            fns["call_llm_fn"]("x", tag=PUBLIC_TAG)
        with pytest.raises(TypeError):
            fns["call_llm_structured_fn"]("x", "sys", ToolSelection, tag=PUBLIC_TAG)


def test_agent_loop_declares_select_tool_then_answer():
    seen = []

    def structured(**kwargs):
        seen.append(("structured", kwargs["role"]))
        return ToolSelection(tool_needed=False, tool_name=None, arguments={}, parallel_calls=None, confidence=1.0,
                             reasoning="niente", final_answer=None)

    def text(prompt, system_prompt=None, thinking="off", reasoning_phase=None, *, tag, role):
        seen.append(("text", role))
        return {"content": "risposta"}

    with patch("app.agent.agent_loop.get_registry_manager") as manager:
        manager.return_value.get_tools_for_mode.return_value = [{"name": "srv__tool", "description": "", "parameters": {}}]
        AgentLoop("fai", "act", None, text, structured, None, None, None, "normal").run()
        assert seen == [("structured", "select_tool"), ("text", "answer")]
        seen.clear()
        AgentLoop("ciao", "chat", None, text, None, None, None, None, "normal").run()
        assert seen == [("text", "answer")]


# --- Ogni chiamata nel codice dichiara il ruolo --------------------------------------------------------

def _llm_calls_without_role():
    """Chiamate a call_llm, call_llm_structured e .chat( in app/ senza la keyword `role=`; il codice che le definisce
    comprese quelle del loop (`call_llm_fn`, `call_llm_structured_fn`)."""
    names = {"call_llm", "call_llm_structured", "call_llm_fn", "call_llm_structured_fn"}
    missing, found = [], 0
    for path in sorted(APP.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            callee = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if callee not in names | {"chat"}:
                continue
            found += 1
            kws = {k.arg: k.value for k in node.keywords}
            valid = "role" in kws and (not isinstance(kws["role"], ast.Constant) or kws["role"].value in roles.VALID_ROLES)
            if not valid:
                missing.append(f"{path.relative_to(APP)}:{node.lineno}")
    return missing, found


# File -> ruoli passati alle chiamate che contiene (`role` = il ruolo ricevuto dal chiamante e inoltrato)
EXPECTED_ROLES = {
    "agent/agent_loop.py": {"roles.ANSWER", "roles.SELECT_TOOL", "roles.REWRITE_EXIT"},
    "agent/execution_log.py": {"roles.ROLLBACK"},
    "agent/fact_extraction.py": {"roles.CONSOLIDATE"},
    "agent/llm_calls.py": {"role"},
    "agent/memory_consolidation.py": {"roles.CONSOLIDATE"},
    "agent/mode_router.py": {"roles.ROUTE"},
    "agent/nodes/chat.py": {"roles.ANSWER"},
    "agent/nodes/plan.py": {"roles.PLAN"},
    "agent/nodes/retrieve_memory.py": {"roles.SUMMARIZE"},
    "agent/nodes/web_prefetch.py": {"roles.PREFETCH"},
    "agent/procedure_distillation.py": {"roles.CONSOLIDATE"},
    "api/routes/approvals.py": {"roles.ANSWER"},
    "evals/suites.py": {"roles.EVAL"},
    "memory/thread_store.py": {"roles.TITLE"},
    "registry/vision.py": {"roles.VISION"},
}


def test_every_call_site_has_the_role_of_its_purpose():
    found = {}
    for path in sorted(APP.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                func = node.func
                callee = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
                if callee in {"call_llm", "call_llm_structured", "chat", "call_llm_fn", "call_llm_structured_fn"}:
                    for kw in node.keywords:
                        if kw.arg == "role":
                            found.setdefault(str(path.relative_to(APP)), set()).add(ast.unparse(kw.value))
    assert found == EXPECTED_ROLES


def test_every_model_call_in_the_app_declares_a_role():
    missing, found = _llm_calls_without_role()
    assert found >= 16, "il controllo non vede più le chiamate: aggiornarlo"
    assert not missing, f"chiamate senza `role=`: {missing}"


# --- Metriche e riepilogo --------------------------------------------------------------------------

def test_the_role_is_stored_with_the_call():
    _provider().chat(MESSAGES, tag=PUBLIC_TAG, role="title")
    record_llm_call(provider="p", model="m", duration_ms=1, role="plan")
    assert [r["role"] for r in llm_rows()] == ["title", "plan"]


def test_old_databases_get_the_role_column():
    Path(settings.metrics_db_path).unlink()
    conn = sqlite3.connect(settings.metrics_db_path)
    conn.execute("CREATE TABLE llm_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, turn_key TEXT, provider TEXT,"
                 " model TEXT, prompt_tokens INTEGER NOT NULL DEFAULT 0, cached_tokens INTEGER NOT NULL DEFAULT 0,"
                 " completion_tokens INTEGER NOT NULL DEFAULT 0, prompt_ms INTEGER, completion_ms INTEGER,"
                 " duration_ms INTEGER NOT NULL, error TEXT)")
    conn.execute("INSERT INTO llm_calls (ts, duration_ms) VALUES ('2026-01-01', 5)")
    conn.commit()
    conn.close()
    store.init_metrics_db()
    assert llm_rows()[0]["role"] is None


def _row(**kw):
    row = {"ts": store.now_iso(), "turn_key": "t", "provider": "llamacpp", "model": "m", "prompt_tokens": 0, "cached_tokens": 0,
           "completion_tokens": 0, "prompt_ms": None, "completion_ms": None, "duration_ms": 100, "error": None}
    store._insert("llm_calls", {**row, **kw})


def test_summary_groups_calls_by_role_sorted_by_calls_and_unlabelled_ones_under_question_mark():
    _row(role="answer", prompt_tokens=100, cached_tokens=40, completion_tokens=10, duration_ms=100)
    _row(role="answer", prompt_tokens=50, completion_tokens=5, duration_ms=300, error="timeout")
    _row(role="answer", prompt_tokens=1, duration_ms=200)
    _row(role="plan", duration_ms=50)
    _row(role=None)
    got = {r["role"]: r for r in report.summary(24)["roles"]}
    assert list(got) == ["answer", "plan", "?"]
    assert got["answer"] == {"role": "answer", "calls": 3, "errors": 1, "prompt_tokens": 151, "cached_tokens": 40,
                             "completion_tokens": 15, "p50_ms": 200, "cost_usd": 0, "fallbacks": {}}
    assert (got["plan"]["calls"], got["?"]["calls"]) == (1, 1)
