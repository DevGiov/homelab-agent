"""Impostazioni modificabili dalla Web UI (docs/settings/RUNTIME_SETTINGS_DESIGN.md, 5).

Tutte le route sono dell'utente, dietro `verify_api_key`: nessun tool dell'agente le raggiunge. Una sezione che non
esiste (o che è una parte di un'altra, come `telegram` dentro `channels`) risponde 404. Errori come i provider:
`{"detail": {"code", "message"}}`.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from app.api.deps import verify_api_key
from app.channels import telegram
from app.core import runtime_settings
from app.core.runtime_settings import SettingsError

router = APIRouter(tags=["settings"])
AUTH = [Depends(verify_api_key)]


def _call(fn, *args):
    try:
        return fn(*args)
    except SettingsError as e:
        raise HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message}) from e


@router.get("/v1/settings/{section}", dependencies=AUTH)
def get_settings(section: str):
    """Ogni campo con il valore effettivo e l'origine (`env`, `ui`, `default`); le credenziali solo `{set, source}`."""
    return _call(runtime_settings.view, section)


@router.patch("/v1/settings/{section}", dependencies=AUTH)
def patch_settings(section: str, body: Dict[str, Any] = Body(default_factory=dict)):
    """Cambia campi e credenziali; `null` toglie il valore della UI (torna al `.env`). Alzare un livello o ammettere
    qualcuno vuole `confirm: true` (409 `confirm_required`)."""
    return _call(runtime_settings.update, section, body)


@router.post("/v1/settings/{section}/reset", dependencies=AUTH)
def reset_settings(section: str):
    """Toglie ogni valore della UI della sezione e delle sue parti: tutto torna al `.env`."""
    return _call(runtime_settings.reset, section)


def _test_token(body: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    secrets = (body or {}).get("secrets")
    secrets = {} if secrets is None else secrets
    if not isinstance(secrets, dict) or set(secrets) - {"bot_token"}:
        raise runtime_settings.invalid("Il corpo accetta solo {\"secrets\": {\"bot_token\": ...}}.")
    draft = secrets.get("bot_token")
    if draft is not None:
        token = runtime_settings.validate_secret("telegram", "bot_token", draft)
    else:
        saved = runtime_settings.snapshot("telegram")
        if saved.secrets_unreadable:
            return {"ok": False, "bot_username": None, "error": telegram.config_problem(saved)}
        token = saved.secret("bot_token").strip()
        if not token:
            return {"ok": False, "bot_username": None, "error": "Nessun token: scrivilo qui o in TELEGRAM_BOT_TOKEN."}
    return telegram.probe(token)


@router.post("/v1/settings/channels/telegram/test", dependencies=AUTH)
def test_telegram(body: Optional[Dict[str, Any]] = Body(default=None)):
    """"Prova il bot": `getMe` con il token della bozza o con quello salvato. Solo `{ok, bot_username, error}`."""
    return _call(_test_token, body)
