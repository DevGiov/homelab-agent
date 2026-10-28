"""Osservabilità: turni e chiamate LLM registrati, aggregazioni della dashboard, campioni di salute e API."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.automations.models import RunStatus
from app.automations.runner import AutomationRunner
from app.core.config import settings
from app.llm.providers import OpenAICompatProvider
from app.observability import health, report, store
from app.observability.turns import observe_turn, record_llm_call
from app.security import audit_log


@pytest.fixture(autouse=True)
def metrics_db():
    Path(settings.metrics_db_path).unlink(missing_ok=True)
    store.init_metrics_db()
    yield


def turns():
    return store.select("SELECT * FROM turns ORDER BY id")


def llm_calls():
    return store.select("SELECT * FROM llm_calls ORDER BY id")


def ago(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def llm_row(**overrides):
    row = {"ts": store.now_iso(), "turn_key": "t", "provider": "llamacpp", "model": "m", "prompt_tokens": 0,
           "cached_tokens": 0, "completion_tokens": 0, "prompt_ms": None, "completion_ms": None, "duration_ms": 100,
           "error": None}
    row.update(overrides)
    store._insert("llm_calls", row)


def turn_row(**overrides):
    row = {"ts": store.now_iso(), "turn_key": "t", "source": "chat", "mode": "chat", "model": "m", "status": "ok",
           "duration_ms": 1000, "llm_ms": 0, "llm_calls": 0, "prompt_tokens": 0, "cached_tokens": 0,
           "completion_tokens": 0, "tool_calls": 0, "tool_errors": 0, "error": None}
    row.update(overrides)
    store.insert_turn(row)


# --- Turni e chiamate LLM ---


def test_turn_sums_llm_calls_and_counts_tools_from_audit_log():
    with observe_turn("thread-obs-1", "chat") as turn:
        record_llm_call(provider="llamacpp", model="m1", duration_ms=300, prompt_tokens=100, cached_tokens=60,
                        completion_tokens=20, prompt_ms=40, completion_ms=200)
        record_llm_call(provider="llamacpp", model="m1", duration_ms=200, prompt_tokens=50, completion_tokens=10)
        audit_log.log_tool_call("web_search", {}, thread_id="thread-obs-1", duration_ms=50)
        audit_log.log_tool_call("web_fetch", {}, thread_id="thread-obs-1", is_error=True, duration_ms=10)
        audit_log.log_tool_call("web_fetch", {}, thread_id="altro-thread", duration_ms=10)
        turn.mode = "research"

    [row] = turns()
    assert row["status"] == "ok" and row["mode"] == "research" and row["model"] == "m1"
    assert (row["llm_calls"], row["llm_ms"]) == (2, 500)
    assert (row["prompt_tokens"], row["cached_tokens"], row["completion_tokens"]) == (150, 60, 30)
    assert (row["tool_calls"], row["tool_errors"]) == (2, 1)
    assert [c["turn_key"] for c in llm_calls()] == ["thread-obs-1", "thread-obs-1"]


def test_turn_exception_is_recorded_and_reraised():
    with pytest.raises(RuntimeError):
        with observe_turn("thread-obs-2", "chat"):
            raise RuntimeError("grafo rotto")
    [row] = turns()
    assert row["status"] == "error" and row["error"] == "grafo rotto"


def test_turn_stopped_by_user():
    with observe_turn("thread-obs-3", "chat", stopped=lambda: True):
        pass
    assert turns()[0]["status"] == "stopped"


def test_llm_call_outside_turn_is_recorded_without_key():
    record_llm_call(provider="llamacpp", model="m", duration_ms=10)
    assert llm_calls()[0]["turn_key"] is None
    assert turns() == []


def test_provider_chat_records_metrics_and_errors():
    provider = OpenAICompatProvider("http://localhost:8080/v1", default_model="def-model")
    provider._chat = lambda *a, **k: {
        "content": "ok",
        "metrics": {"prompt_tokens": 80, "cached_tokens": 30, "completion_tokens": 12, "prompt_ms": 25, "completion_ms": 120},
    }
    with observe_turn("thread-obs-4", "chat"):
        provider.chat([{"role": "user", "content": "ciao"}])
        provider._chat = lambda *a, **k: {"content": "", "error": "timeout", "metrics": {}}
        provider.chat([{"role": "user", "content": "ciao"}], model="altro")

    first, second = llm_calls()
    assert (first["model"], first["prompt_tokens"], first["cached_tokens"], first["prompt_ms"], first["completion_ms"]) == (
        "def-model", 80, 30, 25, 120
    )
    assert (second["model"], second["error"]) == ("altro", "timeout")
    assert turns()[0]["error"] == "LLM: timeout"


@pytest.mark.parametrize(
    "run_status, expected",
    [(RunStatus.COMPLETED, "ok"), (RunStatus.FAILED, "error"), (RunStatus.BLOCKED, "error"),
     (RunStatus.WAITING_APPROVAL, "stopped"), (RunStatus.CANCELLED, "stopped")],
)
def test_automation_run_status_maps_to_turn_status(tmp_path, run_status, expected):
    runner = AutomationRunner(db_path=str(tmp_path / "automations.db"))
    runner._execute_steps = lambda run_id: SimpleNamespace(automation_id="auto-x", status=run_status)
    runner.execute_run("run-obs")
    [row] = turns()
    assert (row["turn_key"], row["source"], row["mode"], row["status"]) == ("run-obs", "automation", "auto-x", expected)


# --- Aggregazioni ---


def test_summary_aggregates_turns_llm_speed_and_health():
    for duration in (1000, 2000, 3000, 4000):
        turn_row(duration_ms=duration)
    turn_row(source="automation", status="error", duration_ms=10_000, tool_calls=3, tool_errors=1)
    turn_row(ts=ago(hours=30), duration_ms=99_000)  # fuori finestra
    # 100 token nuovi in 50 ms (2000 tok/s), 40 generati in 400 ms (100 tok/s), metà del prompt dalla cache
    llm_row(prompt_tokens=200, cached_tokens=100, completion_tokens=40, prompt_ms=50, completion_ms=400)
    llm_row(model="ollama-m", completion_tokens=5, error="boom")  # senza tempi di llama.cpp
    store.insert_health_samples([{"service": "llamacpp", "ok": True, "latency_ms": 20}, {"service": "letta", "ok": False, "error": "giù"}])
    store.insert_health_samples([{"service": "llamacpp", "ok": False, "error": "HTTP 503"}, {"service": "letta", "ok": False, "error": "giù"}])

    data = report.summary(24)
    t = data["turns"]
    assert (t["total"], t["by_status"], t["by_source"]) == (5, {"ok": 4, "error": 1}, {"chat": 4, "automation": 1})
    assert (t["p50_ms"], t["max_ms"], t["tool_calls"], t["tool_errors"]) == (3000, 10_000, 3, 1)
    llm = data["llm"]
    assert (llm["calls"], llm["errors"], llm["prompt_tok_s"], llm["gen_tok_s"], llm["cache_hit_pct"]) == (2, 1, 2000.0, 100.0, 50.0)
    by_model = {m["model"]: m for m in data["models"]}
    assert by_model["ollama-m"]["gen_tok_s"] is None and by_model["ollama-m"]["errors"] == 1
    by_service = {h["service"]: h for h in data["health"]}
    assert (by_service["llamacpp"]["uptime_pct"], by_service["llamacpp"]["ok"], by_service["llamacpp"]["avg_latency_ms"]) == (50.0, False, 20)
    assert by_service["letta"]["last_error"] == "giù"


def test_timeseries_places_rows_in_buckets():
    turn_row(ts=ago(minutes=50), status="error")
    turn_row(ts=ago(minutes=10))
    turn_row(ts=ago(minutes=5), status="stopped")
    store._insert("health_samples", {"ts": ago(minutes=50), "service": "searxng", "ok": 0, "latency_ms": None, "error": "x"})
    store._insert("health_samples", {"ts": ago(minutes=5), "service": "searxng", "ok": 1, "latency_ms": 30, "error": None})

    data = report.timeseries(1, 4)  # intervalli da 15 minuti
    assert data["bucket_minutes"] == 15.0
    assert [p["turns"] for p in data["points"]] == [1, 0, 0, 2]
    assert [p["errors"] for p in data["points"]] == [1, 0, 0, 0]
    assert [p["stopped"] for p in data["points"]] == [0, 0, 0, 1]
    assert [p["uptime_pct"] for p in data["health"]["searxng"]] == [0.0, None, None, 100.0]


def test_purge_removes_only_expired_rows():
    turn_row(ts=ago(days=40))
    turn_row()
    llm_row(ts=ago(days=40))
    store._insert("health_samples", {"ts": ago(days=40), "service": "s", "ok": 1, "latency_ms": 1, "error": None})
    assert store.purge_older_than(30) == 3
    assert len(turns()) == 1 and llm_calls() == []


def test_percentile_nearest_rank():
    assert report.percentile([], 0.5) is None
    assert report.percentile([5], 0.95) == 5
    assert report.percentile(list(range(1, 101)), 0.95) == 95


# --- Salute dei servizi ---


def test_probe_reports_unreachable_service():
    sample = health.probe(health.Target("chiuso", "http://127.0.0.1:9/"))
    assert sample["ok"] is False and sample["error"]


def test_sample_once_stores_every_target(monkeypatch):
    monkeypatch.setattr(health, "targets", lambda: [health.Target("a", "http://a"), health.Target("b", "http://b")])
    monkeypatch.setattr(health, "probe", lambda t: {"service": t.service, "ok": t.service == "a", "latency_ms": 5, "error": None})
    health.sample_once()
    rows = store.select("SELECT service, ok FROM health_samples ORDER BY service")
    assert rows == [{"service": "a", "ok": 1}, {"service": "b", "ok": 0}]


# --- API ---


@pytest.fixture
def api():
    from app.api.main import api as app

    return TestClient(app)


def test_metrics_api(api):
    turn_row(turn_key="chat-1")
    turn_row(turn_key="run-1", source="automation")

    summary = api.get("/v1/metrics/summary", params={"hours": 1}).json()
    assert summary["window_hours"] == 1 and summary["turns"]["total"] == 2
    series = api.get("/v1/metrics/timeseries", params={"hours": 2, "buckets": 8}).json()
    assert len(series["points"]) == 8 and sum(p["turns"] for p in series["points"]) == 2
    assert [t["turn_key"] for t in api.get("/v1/metrics/turns", params={"source": "automation"}).json()] == ["run-1"]
    assert api.get("/v1/metrics/summary", params={"hours": 0}).status_code == 422
