"""Come `call_llm` mette l'immagine nel prompt: ridimensionata, e mai prima di una cronologia."""
import base64
import io
from unittest.mock import MagicMock

from PIL import Image

from app.agent import llm_calls
from app.llm import roles
from app.security import flows

_TAG = flows.tag_of(flows.Label.PUBLIC, "test")


def _photo(width: int, height: int) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (20, 40, 60)).save(buf, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _send(monkeypatch, images, history=None, model="Vision-Test"):
    provider = MagicMock()
    provider.effective_model.return_value = model
    provider.chat.return_value = {"content": "ok", "reasoning_content": "", "metrics": {}}
    monkeypatch.setattr(llm_calls, "get_provider", lambda *a: provider)
    llm_calls.call_llm("descrivi", images=images, history=history, tag=_TAG, role=roles.ANSWER)
    return provider.chat.call_args.args[0]


def _image_parts(messages):
    return [p for m in messages if isinstance(m["content"], list) for p in m["content"] if p["type"] == "image_url"]


def test_the_image_message_is_the_last_one(monkeypatch):
    messages = _send(monkeypatch, [_photo(64, 48)])

    assert len(_image_parts(messages)) == 1
    assert messages[-1]["role"] == "user" and isinstance(messages[-1]["content"], list)


def test_the_image_is_resized_before_it_reaches_the_provider(monkeypatch):
    messages = _send(monkeypatch, [_photo(2400, 1800)])

    url = _image_parts(messages)[0]["image_url"]["url"]
    sent = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert max(sent.size) <= 1920


def test_a_call_with_history_carries_no_image(monkeypatch):
    history = [{"role": "assistant", "content": "passo 1"}, {"role": "tool", "content": "risultato"}]

    messages = _send(monkeypatch, [_photo(64, 48)], history=history)

    assert _image_parts(messages) == []
    assert messages[-2:] == history


def test_a_model_without_vision_still_gets_the_note_when_there_is_history(monkeypatch):
    history = [{"role": "assistant", "content": "passo 1"}]

    messages = _send(monkeypatch, [_photo(64, 48)], history=history, model="Text-Only")

    assert "non supporta la visione" in messages[0]["content"]
    assert messages[-1] == history[0]
