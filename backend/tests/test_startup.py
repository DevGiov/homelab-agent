import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import startup
from app.agent.graph import get_checkpointer
from app.api.main import api
from app.core.config import settings


@pytest.fixture
def fresh_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    get_checkpointer.cache_clear()
    yield tmp_path / "data"
    get_checkpointer.cache_clear()


def _tables(path):
    with sqlite3.connect(path) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_init_storage_creates_every_schema_on_empty_data_dir(fresh_data_dir):
    startup.init_storage()
    startup.init_storage()  # idempotente

    assert {"checkpoints", "writes", "thread_metadata", "thread_messages", "thread_summaries", "user_profile", "procedures", "audit_log", "tool_permissions",
            "vec_memory", "vec_memory_idx"} <= _tables(fresh_data_dir / "checkpoints.db")
    assert {"automation_definitions", "automation_runs", "automation_approvals"} <= _tables(fresh_data_dir / "automations.db")
    assert "calendars" in _tables(fresh_data_dir / "calendar.db")
    assert {"artifacts", "uploads", "knowledge_base"} <= {p.name for p in fresh_data_dir.iterdir()}


def test_thread_list_works_right_after_startup(fresh_data_dir):
    # ISS-03: la lista dei thread non deve dipendere dalla prima esecuzione del grafo
    startup.init_storage()
    assert TestClient(api).get("/v1/threads").json() == []


def test_start_refuses_unauthenticated_api(monkeypatch):
    monkeypatch.setattr(settings, "api_secret_key", "")
    monkeypatch.setattr(settings, "allow_insecure", False)
    with pytest.raises(RuntimeError, match="API_SECRET_KEY"):
        startup.start()
