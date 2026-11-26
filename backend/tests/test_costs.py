"""Costo per chiamata, prezzi dei modelli, tetti di spesa e le loro API."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.llm import costs, providers
from app.llm.providers import OpenAICompatProvider
from app.observability import report, store
from app.observability.turns import record_llm_call
from app.security.flows import PUBLIC_TAG

NOVEMBER = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean_db():
    Path(settings.metrics_db_path).unlink(missing_ok=True)
    store.init_metrics_db()
    costs.init_costs_db()
    for p in costs.list_prices():
        costs.delete_price(p["provider"], p["model"])
    for scope in costs.list_ceilings():
        costs.delete_ceiling(scope)
    yield


def call_row(ts, provider="cloud", cost=1.0, **kw):
    row = {"ts": ts, "turn_key": "t", "provider": provider, "model": "m", "prompt_tokens": 0, "cached_tokens": 0,
           "completion_tokens": 0, "prompt_ms": None, "completion_ms": None, "duration_ms": 10, "error": None,
           "cost_usd": cost}
    store._insert("llm_calls", {**row, **kw})


# --- Prezzi ---------------------------------------------------------------------------------------

def test_a_price_is_stored_replaced_and_deleted():
    saved = costs.set_price("cloud", "vendor/model:1.0", 3, 0.3, 15)
    assert saved["input_per_mtok"] == 3 and saved["cached_per_mtok"] == 0.3 and saved["output_per_mtok"] == 15
    assert saved["updated_at"]
    costs.set_price("cloud", "vendor/model:1.0", 4, 0, 16)
    [row] = costs.list_prices()
    assert (row["input_per_mtok"], row["cached_per_mtok"], row["output_per_mtok"]) == (4, 0, 16)
    assert costs.delete_price("cloud", "vendor/model:1.0") is True
    assert costs.delete_price("cloud", "vendor/model:1.0") is False
    assert costs.list_prices() == []


@pytest.mark.parametrize("args", [
    ("cloud", "m", -1, 0, 0), ("cloud", "m", 0, -0.01, 0), ("cloud", "m", 0, 0, -5),
    ("cloud", "m", float("nan"), 0, 0), ("cloud", "m", 0, float("inf"), 0), ("cloud", "m", "3", 0, 0),
    ("cloud", "m", True, 0, 0), ("cloud", "m", None, 0, 0), ("", "m", 1, 1, 1), ("cloud", "  ", 1, 1, 1),
])
def test_invalid_prices_are_refused_and_nothing_is_stored(args):
    with pytest.raises(ValueError):
        costs.set_price(*args)
    assert costs.list_prices() == []


def test_zero_prices_are_allowed_and_the_table_itself_refuses_negatives():
    costs.set_price("cloud", "free", 0, 0, 0)
    assert costs.get_price("cloud", "free")["output_per_mtok"] == 0
    with sqlite3.connect(settings.mcp_db_path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO model_prices VALUES ('cloud', 'x', -1, 0, 0, 'now')")
    with sqlite3.connect(settings.mcp_db_path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO spend_ceilings VALUES ('cloud', 0, 'now')")


# --- Costo di una chiamata ----------------------------------------------------------------------------

def test_cost_charges_cached_tokens_at_the_cached_price_and_the_rest_of_the_prompt_at_the_input_price():
    costs.set_price("cloud", "m", 3, 0.3, 15)
    # prompt_tokens comprende quelli in cache: 400 nuovi a 3, 600 in cache a 0,3, 200 di risposta a 15
    assert costs.call_cost("cloud", "m", 1000, 600, 200) == pytest.approx((400 * 3 + 600 * 0.3 + 200 * 15) / 1e6)


def test_cost_without_cache_charges_the_whole_prompt_at_the_input_price():
    costs.set_price("cloud", "m", 3, 0.3, 15)
    assert costs.call_cost("cloud", "m", 1000, 0, 200) == pytest.approx((1000 * 3 + 200 * 15) / 1e6)
    assert costs.call_cost("cloud", "m", 0, 0, 0) == 0


def test_cost_never_counts_more_cached_tokens_than_the_prompt_has():
    costs.set_price("cloud", "m", 3, 0.3, 15)
    assert costs.call_cost("cloud", "m", 100, 500, 0) == pytest.approx(100 * 0.3 / 1e6)


def test_a_model_without_a_price_or_a_name_costs_nothing_and_prices_are_per_provider():
    costs.set_price("cloud", "m", 3, 0.3, 15)
    assert costs.call_cost("cloud", "other", 1000, 0, 1000) == 0
    assert costs.call_cost("llamacpp", "m", 1000, 0, 1000) == 0
    assert costs.call_cost("cloud", None, 1000, 0, 1000) == 0
    costs.set_price("llamacpp", "only-local", 1, 1, 1)
    assert costs.call_cost("cloud", "only-local", 1000, 0, 1000) == 0


def test_the_cost_is_stored_with_the_call_and_a_later_price_change_does_not_rewrite_it():
    costs.set_price("cloud", "m", 10, 1, 20)
    record_llm_call(provider="cloud", model="m", duration_ms=5, prompt_tokens=1000, cached_tokens=500, completion_tokens=100,
                    role="answer")
    before = store.select("SELECT cost_usd FROM llm_calls")[0]["cost_usd"]
    assert before == pytest.approx((500 * 10 + 500 * 1 + 100 * 20) / 1e6)
    costs.set_price("cloud", "m", 1000, 1000, 1000)
    record_llm_call(provider="cloud", model="m", duration_ms=5, prompt_tokens=1000, completion_tokens=0, role="answer")
    costs.delete_price("cloud", "m")
    first, second = [r["cost_usd"] for r in store.select("SELECT cost_usd FROM llm_calls ORDER BY id")]
    assert first == before and second == pytest.approx(1.0)


def test_a_call_without_price_is_recorded_with_zero_cost():
    record_llm_call(provider="llamacpp", model="m", duration_ms=5, prompt_tokens=1000, completion_tokens=10, role="answer")
    assert store.select("SELECT cost_usd FROM llm_calls")[0]["cost_usd"] == 0


def test_a_failed_call_that_reported_tokens_still_costs_what_it_used():
    costs.set_price("cloud", "m", 2, 0, 4)
    record_llm_call(provider="cloud", model="m", duration_ms=5, prompt_tokens=1000, completion_tokens=50, error="troncato",
                    role="answer")
    [row] = store.select("SELECT * FROM llm_calls")
    assert row["error"] and row["cost_usd"] == pytest.approx((1000 * 2 + 50 * 4) / 1e6)


def test_provider_chat_records_the_cost_of_the_call():
    costs.set_price("cc", "m", 1, 0.5, 2)
    provider = OpenAICompatProvider("http://localhost:8080/v1", default_model="m", name="cc")
    provider._chat = lambda *a, **k: {"content": "ok", "metrics": {"prompt_tokens": 100, "cached_tokens": 40,
                                                                   "completion_tokens": 10}}
    provider.chat([{"role": "user", "content": "x"}], tag=PUBLIC_TAG, role="answer")
    assert store.select("SELECT cost_usd FROM llm_calls")[0]["cost_usd"] == pytest.approx((60 + 20 + 20) / 1e6)


def test_old_databases_get_the_cost_column_and_null_costs_count_as_zero():
    Path(settings.metrics_db_path).unlink()
    conn = sqlite3.connect(settings.metrics_db_path)
    conn.execute("CREATE TABLE llm_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, turn_key TEXT, provider TEXT,"
                 " model TEXT, prompt_tokens INTEGER NOT NULL DEFAULT 0, cached_tokens INTEGER NOT NULL DEFAULT 0,"
                 " completion_tokens INTEGER NOT NULL DEFAULT 0, prompt_ms INTEGER, completion_ms INTEGER,"
                 " duration_ms INTEGER NOT NULL, error TEXT)")
    conn.execute(f"INSERT INTO llm_calls (ts, duration_ms) VALUES ('{store.now_iso()}', 5)")
    conn.commit()
    conn.close()
    store.init_metrics_db()
    assert store.select("SELECT cost_usd FROM llm_calls")[0]["cost_usd"] is None
    assert report.summary(1)["llm"]["cost_usd"] == 0


# --- Spesa del mese e tetti --------------------------------------------------------------------------------

def test_month_spend_sums_the_calendar_month_in_utc_and_respects_the_boundaries():
    call_row("2026-10-31T23:59:59+00:00", cost=100)          # ultimo secondo del mese prima: fuori
    call_row("2026-11-01T00:00:00+00:00", cost=1)            # primo istante: dentro
    call_row("2026-11-20T10:00:00.5+00:00", cost=2, provider="other")
    call_row("2026-11-30T23:59:59.999999+00:00", cost=4)     # ultimo istante: dentro
    call_row("2026-12-01T00:00:00+00:00", cost=1000)         # mese dopo: fuori
    call_row("2026-11-10T00:00:00+00:00", cost=None)         # senza costo (righe vecchie): ignorata
    spend = costs.month_spend(NOVEMBER)
    assert spend == {"cloud": 5, "other": 2, "total": 7}
    assert costs.month_spend(datetime(2026, 12, 31, 23, 0, tzinfo=timezone.utc)) == {"cloud": 1000, "total": 1000}
    assert costs.month_spend(datetime(2026, 1, 3, tzinfo=timezone.utc)) == {"total": 0}


def test_month_bounds_wrap_the_year_and_convert_to_utc():
    start, end = costs.month_bounds(datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc))
    assert (start.isoformat(), end.isoformat()) == ("2026-12-01T00:00:00+00:00", "2027-01-01T00:00:00+00:00")
    # 2026-12-01 00:30 a +01:00 è ancora novembre in UTC
    from datetime import timedelta
    local = datetime(2026, 12, 1, 0, 30, tzinfo=timezone(timedelta(hours=1)))
    assert costs.month_bounds(local)[0].isoformat() == "2026-11-01T00:00:00+00:00"


def test_no_ceiling_means_never_reached():
    call_row("2026-11-02T00:00:00+00:00", cost=1e6)
    assert costs.ceiling_reached("cloud", NOVEMBER) is None


def test_the_provider_ceiling_is_reached_when_its_spend_equals_or_passes_it():
    call_row("2026-11-02T00:00:00+00:00", cost=4.99)
    costs.set_ceiling("cloud", 5)
    assert costs.ceiling_reached("cloud", NOVEMBER) is None
    call_row("2026-11-03T00:00:00+00:00", cost=0.01)
    assert costs.ceiling_reached("cloud", NOVEMBER) == "provider"
    assert costs.ceiling_reached("other", NOVEMBER) is None      # il tetto è del suo provider
    call_row("2026-11-04T00:00:00+00:00", cost=3)
    assert costs.ceiling_reached("cloud", NOVEMBER) == "provider"


def test_the_total_ceiling_counts_every_provider_and_does_not_need_a_provider_one():
    call_row("2026-11-02T00:00:00+00:00", cost=3, provider="a")
    call_row("2026-11-02T00:00:00+00:00", cost=3, provider="b")
    costs.set_ceiling("total", 6)
    costs.set_ceiling("a", 100)
    assert costs.ceiling_reached("a", NOVEMBER) == "total"
    assert costs.ceiling_reached("b", NOVEMBER) == "total"
    costs.set_ceiling("a", 3)
    assert costs.ceiling_reached("a", NOVEMBER) == "provider"    # il suo tetto vince sul totale
    costs.set_ceiling("total", 6.01)
    assert costs.ceiling_reached("b", NOVEMBER) is None


def test_a_new_month_starts_from_zero_and_a_deleted_ceiling_is_gone():
    call_row("2026-10-31T23:59:59+00:00", cost=50)
    costs.set_ceiling("cloud", 5)
    assert costs.ceiling_reached("cloud", NOVEMBER) is None
    call_row("2026-11-01T00:00:00+00:00", cost=5)
    assert costs.ceiling_reached("cloud", NOVEMBER) == "provider"
    assert costs.delete_ceiling("cloud") is True and costs.delete_ceiling("cloud") is False
    assert costs.ceiling_reached("cloud", NOVEMBER) is None


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), "5", True, None])
def test_invalid_ceilings_are_refused(value):
    with pytest.raises(ValueError):
        costs.set_ceiling("cloud", value)
    assert costs.list_ceilings() == {}


# --- Riepilogo ------------------------------------------------------------------------------------------

def test_report_shows_the_cost_in_total_per_model_per_role_and_per_bucket():
    now = store.now_iso()
    call_row(now, cost=0.25, model="m1", role="answer")
    call_row(now, cost=0.5, model="m1", role="plan")
    call_row(now, cost=0.125, model="m2", role="answer")
    call_row(now, cost=None, model="m2", role=None)
    summary = report.summary(1)
    assert summary["llm"]["cost_usd"] == 0.875
    assert {m["model"]: m["cost_usd"] for m in summary["models"]} == {"m1": 0.75, "m2": 0.125}
    assert {r["role"]: r["cost_usd"] for r in summary["roles"]} == {"answer": 0.375, "plan": 0.5, "?": 0}
    points = report.timeseries(1, 4)["points"]
    assert sum(p["cost_usd"] for p in points) == 0.875 and len(points) == 4


# --- API --------------------------------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    from app.api import main as api_module
    monkeypatch.setitem(providers._PROVIDERS, "cloudx", MagicMock())
    return TestClient(api_module.api)


MODEL_IDS = ["plain", "openai.gpt-oss-120b-1:0", "vendor/model", "meta/llama-3.1:70b/instruct", "a.b/c:d-1.0"]


@pytest.mark.parametrize("model", MODEL_IDS)
def test_price_routes_handle_model_ids_with_slashes_colons_and_dots(client, model):
    r = client.put(f"/v1/providers/cloudx/models/{model}/price",
                   json={"input_per_mtok": 1.5, "cached_per_mtok": 0.15, "output_per_mtok": 6})
    assert r.status_code == 200, r.text
    assert (r.json()["provider"], r.json()["model"], r.json()["input_per_mtok"]) == ("cloudx", model, 1.5)
    assert costs.get_price("cloudx", model)["output_per_mtok"] == 6
    d = client.delete(f"/v1/providers/cloudx/models/{model}/price")
    assert d.status_code == 200 and d.json() == {"provider": "cloudx", "model": model, "deleted": True}
    assert costs.get_price("cloudx", model) is None
    assert client.delete(f"/v1/providers/cloudx/models/{model}/price").json()["deleted"] is False


def test_the_existing_model_routes_still_work_next_to_the_price_routes(client):
    assert client.get("/v1/providers/nonexistent_provider_xyz/models").status_code == 404
    assert client.get("/v1/providers/cloudx/models/x/price").status_code in (404, 405)
    assert client.get("/v1/providers/costs").status_code == 200
    # Il provider attivo globale non c'è più: ogni richiesta porta il suo (5.8.1)
    assert client.put("/v1/providers/default", json={"provider": "nope"}).status_code in (404, 405)


def test_price_routes_refuse_unknown_providers_and_invalid_bodies(client):
    ok = {"input_per_mtok": 1, "cached_per_mtok": 0, "output_per_mtok": 2}
    assert client.put("/v1/providers/ghost/models/m/price", json=ok).status_code == 404
    assert client.delete("/v1/providers/ghost/models/m/price").status_code == 404
    for bad in ({**ok, "input_per_mtok": -1}, {**ok, "output_per_mtok": "x"}, {"input_per_mtok": 1}, {}):
        assert client.put("/v1/providers/cloudx/models/m/price", json=bad).status_code == 422
    assert costs.list_prices() == []


def test_ceiling_routes_accept_providers_and_total_and_refuse_the_rest(client):
    r = client.put("/v1/providers/ceilings/cloudx", json={"monthly_usd": 12.5})
    assert r.status_code == 200 and r.json() == {"scope": "cloudx", "monthly_usd": 12.5}
    assert client.put("/v1/providers/ceilings/total", json={"monthly_usd": 20}).status_code == 200
    assert costs.list_ceilings() == {"cloudx": 12.5, "total": 20}
    assert client.put("/v1/providers/ceilings/ghost", json={"monthly_usd": 1}).status_code == 404
    assert client.delete("/v1/providers/ceilings/ghost").status_code == 404
    for bad in (0, -3, "x", None):
        assert client.put("/v1/providers/ceilings/cloudx", json={"monthly_usd": bad}).status_code == 422
    assert client.put("/v1/providers/ceilings/cloudx", json={}).status_code == 422
    assert client.delete("/v1/providers/ceilings/cloudx").json() == {"scope": "cloudx", "deleted": True}
    assert client.delete("/v1/providers/ceilings/total").json()["deleted"] is True
    assert client.delete("/v1/providers/ceilings/total").json()["deleted"] is False
    assert costs.list_ceilings() == {}


def test_costs_route_reports_prices_ceilings_spend_of_the_month_and_reached_ceilings(client):
    month = datetime.now(timezone.utc)
    call_row(month.isoformat(), cost=3.0, provider="cloudx")
    call_row(month.isoformat(), cost=1.0, provider="llamacpp")
    call_row("2000-01-01T00:00:00+00:00", cost=999, provider="cloudx")
    client.put("/v1/providers/cloudx/models/vendor/m:1/price", json={"input_per_mtok": 1, "cached_per_mtok": 0.5, "output_per_mtok": 2})
    client.put("/v1/providers/ceilings/cloudx", json={"monthly_usd": 3})
    client.put("/v1/providers/ceilings/total", json={"monthly_usd": 10})
    body = client.get("/v1/providers/costs").json()
    assert set(body) == {"prices", "ceilings", "spend", "reached"}
    [price] = body["prices"]
    assert (price["provider"], price["model"], price["input_per_mtok"], price["cached_per_mtok"], price["output_per_mtok"]) == (
        "cloudx", "vendor/m:1", 1, 0.5, 2)
    assert body["ceilings"] == {"cloudx": 3, "total": 10}
    assert body["spend"] == {"month": month.strftime("%Y-%m"), "by_provider": {"cloudx": 3.0, "llamacpp": 1.0}, "total": 4.0}
    assert body["reached"] == {"cloudx": True, "total": False}
    client.put("/v1/providers/ceilings/total", json={"monthly_usd": 4})
    assert client.get("/v1/providers/costs").json()["reached"] == {"cloudx": True, "total": True}


def test_costs_route_on_an_empty_installation(client):
    body = client.get("/v1/providers/costs").json()
    assert body["prices"] == [] and body["ceilings"] == {} and body["reached"] == {}
    assert body["spend"]["by_provider"] == {} and body["spend"]["total"] == 0
