import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import startup
from app.agent.graph import get_checkpointer
from app.api.main import api
from app.core.config import settings
from app.memory import thread_store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    get_checkpointer.cache_clear()
    startup.init_storage()
    yield TestClient(api)
    get_checkpointer.cache_clear()


def _add_checkpoint(thread_id):
    with sqlite3.connect(settings.checkpoint_db_path) as conn:
        conn.execute(
            "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id) VALUES (?, '', ?)",
            (thread_id, f"cp_{thread_id}"),
        )


def test_thread_list_comes_from_message_store(client):
    thread_store.save_user_message("t_saved", "ciao")
    thread_store.save_assistant_message("t_saved", {"response": "ciao a te", "mode": "chat"})
    _add_checkpoint("t_saved")
    _add_checkpoint("t_incognito")  # turno incognito: checkpoint LangGraph ma nessun messaggio salvato

    threads = client.get("/v1/threads").json()

    assert [t["thread_id"] for t in threads] == ["t_saved"]
    assert threads[0]["checkpoint_count"] == 1
    assert threads[0]["last_message"] == "ciao a te"


def test_thread_without_messages_is_not_rebuilt_from_checkpoints(client):
    _add_checkpoint("t_incognito")

    body = client.get("/v1/threads/t_incognito").json()

    assert body["messages"] == []
    assert thread_store.get_thread_messages("t_incognito") == []
