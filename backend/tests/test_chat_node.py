"""Errori del modello sulla risposta diretta di una richiesta visiva."""
from unittest.mock import MagicMock

from app.agent.nodes import chat as chat_node

_GPU = "L'immagine non è entrata nella memoria della GPU e il modello è stato chiuso."
_GENERIC = "Il modello non ha completato la richiesta (HTTP 503). Riprova tra poco o scegli un modello più leggero."


def _state():
    return {
        "task": "Analizza e descrivi l'immagine allegata.",
        "images": ["data:image/png;base64,iVBORw0KGgo="],
        "model": "Vision-Test",
    }


def test_chat_says_the_image_did_not_fit_and_still_sends_the_image(monkeypatch):
    call = MagicMock(return_value={"content": "", "error": "gpu-memory"})
    monkeypatch.setattr(chat_node.llm_calls, "call_llm", call)

    res = chat_node.chat_graph_node(_state())

    assert res["final_response"] == _GPU
    assert call.call_args.kwargs["images"] == _state()["images"]
    assert call.call_args.kwargs["role"] == "answer"


def test_chat_keeps_the_generic_sentence_for_other_failures(monkeypatch):
    monkeypatch.setattr(chat_node.llm_calls, "call_llm", MagicMock(return_value={"content": "", "error": "HTTP 503"}))

    res = chat_node.chat_graph_node(_state())

    assert res["final_response"] == _GENERIC
