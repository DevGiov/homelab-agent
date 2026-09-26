import pytest
from unittest.mock import MagicMock, patch
import json

from stream_session import StreamSession
import thread_store
from providers import OpenAICompatProvider


def test_stream_session_metrics_preserves_tok_per_s():
    sess = StreamSession("thread_test")
    sess.record_metrics({
        "prompt_tokens": 15,
        "completion_tokens": 50,
        "total_tokens": 65,
        "duration_s": 2.5,
        "tok_per_s": 65.4,
    })
    metrics = sess.get_metrics()
    assert metrics["tok_per_s"] == 65.4
    assert metrics["completion_tokens"] == 50
    assert metrics["prompt_tokens"] == 15


def test_thread_store_message_model(tmp_path):
    # In-memory or temp sqlite test
    db_file = str(tmp_path / "test_threads.db")
    with patch("config.CHECKPOINT_DB_PATH", db_file):
        thread_store.init_db()
        t_id = "thread_model_test"
        thread_store.save_user_message(t_id, "ciao")
        msg_id = thread_store.save_assistant_message(t_id, {
            "response": "Ciao!",
            "mode": "chat",
            "model": "Gemma-4-26B-Q3",
            "metrics": {"tok_per_s": 62.5, "completion_tokens": 10}
        })
        msgs = thread_store.get_thread_messages(t_id)
        assert len(msgs) == 2
        ast_msg = msgs[1]
        assert ast_msg["sender"] == "assistant"
        assert ast_msg["model"] == "Gemma-4-26B-Q3"
        assert ast_msg["metrics"]["tok_per_s"] == 62.5


def test_openai_compat_list_models_with_details():
    provider = OpenAICompatProvider("http://localhost:8080/v1", default_model="Gemma-4-26B-Q3")
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "data": [
            {
                "id": "Gemma-4-26B-Q3",
                "status": {"value": "loaded", "args": []},
                "architecture": {"input_modalities": ["text", "image"]}
            },
            {
                "id": "Qwen3.8-27B",
                "status": {"value": "unloaded", "args": []},
                "architecture": {"input_modalities": ["text"]}
            }
        ]
    }

    with patch("httpx.Client.get", return_value=fake_response):
        details = provider.list_models_with_details()
        assert len(details) == 2
        m1 = details[0]
        assert m1["id"] == "Gemma-4-26B-Q3"
        assert m1["is_loaded"] is True
        assert m1["is_loading"] is False
        assert m1["is_vision"] is True

        m2 = details[1]
        assert m2["id"] == "Qwen3.8-27B"
        assert m2["is_loaded"] is False
        assert m2["is_loading"] is False


def test_openai_compat_chat_timings_non_stream():
    provider = OpenAICompatProvider("http://localhost:8080/v1", default_model="Gemma-4-26B-Q3")
    fake_post_response = MagicMock()
    fake_post_response.status_code = 200
    fake_post_response.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "Hello world"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        "timings": {
            "predicted_per_second": 58.7,
            "predicted_n": 20,
            "prompt_n": 10,
        }
    }

    with patch.object(provider, "ensure_model_loaded", return_value=True):
        with patch("httpx.Client.post", return_value=fake_post_response):
            res = provider.chat([{"role": "user", "content": "hi"}], stream_callback=None)
            assert res["content"] == "Hello world"
            assert res["metrics"]["tok_per_s"] == 58.7
            assert res["metrics"]["completion_tokens"] == 20
            assert res["metrics"]["prompt_tokens"] == 10


def test_openai_compat_chat_timings_stream():
    provider = OpenAICompatProvider("http://localhost:8080/v1", default_model="Gemma-4-26B-Q3")
    
    # Simulate SSE chunks
    lines = [
        'data: {"choices":[{"delta":{"content":"Hi"}}]}',
        'data: {"choices":[{"delta":{"content":" there"}}]}',
        'data: {"choices":[],"timings":{"predicted_per_second":64.2,"predicted_n":5,"prompt_n":8,"cache_n":2}}',
        'data: [DONE]'
    ]
    fake_stream_context = MagicMock()
    fake_stream_response = MagicMock()
    fake_stream_response.status_code = 200
    fake_stream_response.iter_lines.return_value = lines
    fake_stream_context.__enter__.return_value = fake_stream_response

    events = []
    def _cb(ev):
        events.append(ev)

    with patch.object(provider, "ensure_model_loaded", return_value=True):
        with patch("httpx.Client.stream", return_value=fake_stream_context):
            res = provider.chat([{"role": "user", "content": "hi"}], stream_callback=_cb)
            assert res["content"] == "Hi there"
            assert res["metrics"]["tok_per_s"] == 64.2
            assert res["metrics"]["completion_tokens"] == 5
            assert res["metrics"]["prompt_tokens"] == 10  # 8 + 2
            assert any(e.get("type") == "metrics" and e["metrics"]["tok_per_s"] == 64.2 for e in events)


def test_openai_compat_ensure_model_loaded():
    provider = OpenAICompatProvider("http://localhost:8080/v1", default_model="Gemma-4-26B-Q3")

    # If already loaded: returns True immediately without calling load_model
    with patch.object(provider, "list_models_with_details", return_value=[{"id": "Gemma-4-26B-Q3", "is_loaded": True}]):
        with patch.object(provider, "load_model") as mock_load:
            assert provider.ensure_model_loaded("Gemma-4-26B-Q3") is True
            mock_load.assert_not_called()

    # If unloaded: calls load_model and waits until loaded
    call_counts = {"count": 0}
    def mock_list():
        call_counts["count"] += 1
        is_now_loaded = call_counts["count"] >= 2
        return [{"id": "Qwen3.8-27B", "is_loaded": is_now_loaded}]

    with patch.object(provider, "list_models_with_details", side_effect=mock_list):
        with patch.object(provider, "load_model", return_value={"status": "ok"}) as mock_load:
            with patch("time.sleep", return_value=None):
                assert provider.ensure_model_loaded("Qwen3.8-27B", timeout=5.0) is True
                mock_load.assert_called_once_with("Qwen3.8-27B")
