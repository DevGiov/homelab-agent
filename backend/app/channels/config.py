"""Le impostazioni dei canali (docs/settings/RUNTIME_SETTINGS_DESIGN.md, 4): sezione `channels` con la parte `telegram`.

Il valore di base viene dal `.env`, campo per campo; la UI lo sovrascrive. Dopo un salvataggio della parte `telegram`
il canale si ricostruisce e riparte da solo (`apply`), senza riavviare il backend. Alzare il livello o aggiungere un
utente ammesso va confermato: chi è ammesso comanda l'agente. `private` non si concede mai (CHANNELS_DESIGN.md,
decisione 2).

Questo modulo dichiara e legge; le modifiche passano solo dalle API dell'utente (app.core.runtime_settings).
"""
import re
from typing import Any, Dict, List, Optional

from app.core import runtime_settings as rs
from app.core.config import CHANNEL_CLEARANCES
from app.security.flows import Label

MIN_TIMEOUT, MAX_TIMEOUT = 30, 3600
MAX_ALLOWED_USERS = 100
MAX_USER_ID = 2 ** 63 - 1
_URL = re.compile(r"^https?://[^\s/?#]+[^\s]*$")
# La forma di un token di bot: id, due punti, segreto. Il token finisce nel percorso degli URL della Bot API
_TOKEN = re.compile(r"^\d{3,}:[A-Za-z0-9_-]{20,}$")


# --- Validatori dei valori della UI (i messaggi non ripetono mai il valore) ---------------------------

def _web_ui_url(value: Any) -> str:
    if not isinstance(value, str):
        raise rs.invalid("'web_ui_url' vuole un indirizzo http:// o https://, oppure vuoto.")
    value = value.strip()
    if value and not _URL.match(value):
        raise rs.invalid("'web_ui_url' vuole un indirizzo http:// o https://, oppure vuoto.")
    return value.rstrip("/")


def _timeout(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not MIN_TIMEOUT <= value <= MAX_TIMEOUT:
        raise rs.invalid(f"'reply_timeout_seconds' vuole un numero intero di secondi tra {MIN_TIMEOUT} e {MAX_TIMEOUT}.")
    return value


def _enabled(value: Any) -> bool:
    if not isinstance(value, bool):
        raise rs.invalid("'enabled' vuole sì o no.")
    return value


def _allowed_users(value: Any) -> List[int]:
    if not isinstance(value, list) or not all(isinstance(v, int) and not isinstance(v, bool) and 0 < v <= MAX_USER_ID
                                              for v in value):
        raise rs.invalid("'allowed_users' vuole un elenco di id numerici positivi degli utenti Telegram.")
    if len(value) > MAX_ALLOWED_USERS:
        raise rs.invalid(f"'allowed_users' ammette al massimo {MAX_ALLOWED_USERS} utenti.")
    return sorted(set(value))


def _clearance(value: Any) -> str:
    if value == "private":
        raise rs.invalid("Telegram non riceve mai dati private senza conferma: i messaggi passano dai server di "
                         "Telegram. Livelli ammessi: public o internal.")
    if value not in CHANNEL_CLEARANCES:
        raise rs.invalid("'clearance' vuole public o internal.")
    return value


def _bot_token(value: str) -> str:
    if not _TOKEN.match(value):
        raise rs.invalid("Il token non ha la forma di un token di bot (numero, due punti, segreto): copialo da BotFather.")
    return value


# --- Valori del .env ---------------------------------------------------------------------------------

def _env_users(raw: Any) -> List[int]:
    """`TELEGRAM_ALLOWED_USERS`: un valore che non è un id positivo rende tutta la variabile non valida (ValueError)."""
    from app.channels.telegram import parse_allowed_users
    return sorted(parse_allowed_users(str(raw or "")))


def _env_clearance(raw: Any) -> str:
    """La regola del `.env` (config.py): public o internal; ogni altro valore, `private` compreso, vale public."""
    value = str(raw or "").strip().lower()
    return value if value in CHANNEL_CLEARANCES else "public"


# --- Conferme, applicazione, stato ---------------------------------------------------------------------

def _confirm_telegram(before: rs.Resolved, after: rs.Resolved) -> Optional[str]:
    """Alzare il livello o aggiungere un utente ammesso vuole `confirm`; togliere e abbassare no."""
    reasons = []
    old, new = Label.parse(before.value("clearance"), Label.PUBLIC), Label.parse(after.value("clearance"), Label.PUBLIC)
    if new > old:
        reasons.append(f"Il livello di Telegram sale da {old.key} a {new.key}: le risposte con dati {new.key} "
                       "arriveranno nella chat senza conferma.")
    added = sorted(set(after.value("allowed_users")) - set(before.value("allowed_users")))
    if added:
        who = ", ".join(map(str, added))
        reasons.append(f"L'utente {who} potrà dare comandi all'agente." if len(added) == 1
                       else f"Gli utenti {who} potranno dare comandi all'agente.")
    return " ".join(reasons) + " Serve la conferma." if reasons else None


def _apply_telegram() -> None:
    from app.channels import telegram
    telegram.apply_settings()


def _telegram_status(r: rs.Resolved) -> Dict[str, Any]:
    """`running` (il ciclo di polling è attivo), `last_error` (già ripulito dal token), `ignored` (per tipo). Se il
    canale non si è potuto costruire per un valore che la UI non può dedurre dai campi (token illeggibile, utenti del
    `.env` non validi), `last_error` dice perché."""
    from app.channels import telegram
    from app.channels.hub import get_hub
    channel = get_hub().get(telegram.CHANNEL_ID)
    if isinstance(channel, telegram.TelegramChannel):
        return {"running": channel.running, "last_error": channel.last_error, "ignored": dict(channel.ignored)}
    return {"running": False, "last_error": telegram.config_problem(r), "ignored": {}}


CHANNELS = rs.Section(
    id="channels",
    fields=(rs.Field("web_ui_url", _web_ui_url, attr="web_ui_url", default=""),
            rs.Field("reply_timeout_seconds", _timeout, attr="channel_reply_timeout_seconds", default=300)),
    parts=("telegram",),
)

TELEGRAM = rs.Section(
    id="telegram",
    fields=(rs.Field("enabled", _enabled, default=lambda is_set: is_set["bot_token"]),
            rs.Field("allowed_users", _allowed_users, attr="telegram_allowed_users", from_env=_env_users, default=[]),
            rs.Field("clearance", _clearance, attr="telegram_clearance", from_env=_env_clearance, default="internal")),
    secrets={"bot_token": "telegram_bot_token"},
    secret_validators={"bot_token": _bot_token},
    confirm=_confirm_telegram,
    apply=_apply_telegram,
    status=_telegram_status,
)

SECTIONS = (CHANNELS, TELEGRAM)
