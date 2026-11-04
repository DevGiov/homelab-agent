"""Il watchdog informa l'agent sui modelli, ma non deve mai poterlo fermare."""
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.core.config import settings
from app.llm import model_availability
from app.llm.providers import OpenAICompatProvider

BLOCKED = {"available": False, "would_block": False, "reason": "Purpur è acceso", "memory_class": "spills"}
SIMULATED = {"available": True, "would_block": True, "reason": "Purpur è acceso", "memory_class": "unknown"}
FREE = {"available": True, "would_block": False, "reason": None, "memory_class": "vram"}


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(settings, "watchdog_url", "http://watchdog.test")
    model_availability.clear_cache()
    yield
    model_availability.clear_cache()


def _response(models):
    res = MagicMock(status_code=200)
    res.json.return_value = {"rule": {}, "models": models}
    return res


def test_blocked_model_has_a_reason():
    with patch("httpx.Client.get", return_value=_response({"big": BLOCKED})):
        assert model_availability.unavailable_reason("big") == "Purpur è acceso"


def test_simulation_does_not_block_but_warns():
    with patch("httpx.Client.get", return_value=_response({"m": SIMULATED})):
        assert model_availability.unavailable_reason("m") is None
        fields = model_availability.availability_fields("m")
    assert fields == {"available": True, "would_block": True, "availability_note": "Purpur è acceso", "memory_class": "unknown"}


@pytest.mark.parametrize("failure", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
def test_watchdog_down_means_no_restrictions(failure):
    with patch("httpx.Client.get", side_effect=failure):
        assert model_availability.unavailable_reason("big") is None
        assert model_availability.availability_fields("big")["available"] is True


@pytest.mark.parametrize("body", [{}, {"models": None}, {"models": []}])
def test_unexpected_answer_means_no_restrictions(body):
    res = MagicMock(status_code=200)
    res.json.return_value = body
    with patch("httpx.Client.get", return_value=res):
        assert model_availability.unavailable_reason("big") is None


def test_unknown_model_is_not_restricted():
    with patch("httpx.Client.get", return_value=_response({"big": BLOCKED})):
        assert model_availability.unavailable_reason("altro") is None


def test_disabled_without_url(monkeypatch):
    monkeypatch.setattr(settings, "watchdog_url", "")
    with patch("httpx.Client.get") as get:
        assert model_availability.unavailable_reason("big") is None
    get.assert_not_called()


def test_answers_are_cached_even_when_the_watchdog_is_down():
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("refused")) as get:
        for _ in range(5):
            model_availability.unavailable_reason("big")
    assert get.call_count == 1


def test_load_of_blocked_model_never_reaches_llama_swap():
    provider = OpenAICompatProvider("http://llama.test/v1", "default")
    with patch("httpx.Client.get", return_value=_response({"big": BLOCKED})) as get:
        result = provider.load_model("big")
    assert result == {"status": "error", "code": 409, "detail": "Purpur è acceso"}
    assert all("llama.test" not in str(call.args[0]) for call in get.call_args_list)


def test_chat_with_blocked_model_returns_the_reason_without_calling_the_server():
    provider = OpenAICompatProvider("http://llama.test/v1", "default")
    with patch("httpx.Client.get", return_value=_response({"big": BLOCKED})), patch("httpx.Client.stream") as stream:
        result = provider._chat([{"role": "user", "content": "x"}], model="big", reasoning=MagicMock())
    assert result["error"] == "Purpur è acceso"
    stream.assert_not_called()


def test_model_details_carry_availability():
    provider = OpenAICompatProvider("http://llama.test/v1", "default")
    models = MagicMock(status_code=200)
    models.json.return_value = {"data": [{"id": "big"}, {"id": "small"}]}
    running = MagicMock(status_code=200)
    running.json.return_value = {"running": []}

    def fake_get(url):
        if url.endswith("/v1/availability"):
            return _response({"big": BLOCKED, "small": FREE})
        return running if url.endswith("/running") else models

    with patch("httpx.Client.get", side_effect=fake_get):
        details = {d["id"]: d for d in provider.list_models_with_details()}
    assert details["big"]["available"] is False
    assert details["big"]["availability_note"] == "Purpur è acceso"
    assert details["small"]["available"] is True
    assert details["small"]["availability_note"] is None


def test_model_details_survive_a_watchdog_failure():
    provider = OpenAICompatProvider("http://llama.test/v1", "default")
    models = MagicMock(status_code=200)
    models.json.return_value = {"data": [{"id": "big"}]}
    running = MagicMock(status_code=200)
    running.json.return_value = {"running": []}

    def fake_get(url):
        if url.endswith("/v1/availability"):
            raise httpx.ConnectError("refused")
        return running if url.endswith("/running") else models

    with patch("httpx.Client.get", side_effect=fake_get):
        details = provider.list_models_with_details()
    assert details[0]["id"] == "big"
    assert details[0]["available"] is True
