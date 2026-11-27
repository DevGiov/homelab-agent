"""Il canale Telegram (fase C1, docs/channels/CHANNELS_DESIGN.md): testo in arrivo e in uscita, con long polling.

- **Ricezione**: un thread chiama `getUpdates` in attesa lunga (nessun webhook, nessuna porta aperta). L'offset conferma
  gli update già letti; un errore aspetta sempre di più (fino a un minuto); `stop` conferma quelli gestiti e chiude.
- **Chi può scrivere**: solo gli utenti di `TELEGRAM_ALLOWED_USERS`, solo in chat privata con il bot. Gli altri messaggi
  (e i pulsanti premuti da altri) si contano e si scartano senza leggerne il testo.
- **Uscita**: il hub decide cosa può partire (regola di sensibilità); qui si manda l'HTML di Telegram, con "sta
  scrivendo" mentre il turno gira e i pulsanti "Mostra qui" (callback) e "Apri nell'app" (link alla Web UI).
- **Il token** sta nel percorso degli URL della Bot API. Lo aggiunge solo `_BotTransport`, dopo che httpx ha costruito
  la richiesta: la richiesta che httpx scrive nei log e allega alle eccezioni non lo contiene. In più ogni messaggio di
  errore passa da `redact`, e un filtro lo toglie dai log di questo modulo e di httpx.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import Counter
from typing import Any, Callable, Dict, FrozenSet, Optional

import httpx

from app.channels import render
from app.channels.base import Capabilities, Channel, InboundMessage, OutgoingMessage
from app.channels.hub import ChannelHub
from app.core import runtime_settings
from app.security.flows import Label

logger = logging.getLogger("channels.telegram")

CHANNEL_ID = "telegram"
API_BASE = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4096  # limite di Telegram per il testo di un messaggio
MAX_MESSAGES = 5  # oltre, l'inizio della risposta e il link all'app
CALLBACK_DATA_LIMIT = 64  # byte ammessi in `callback_data`
POLL_TIMEOUT_SECONDS = 25  # attesa lunga di getUpdates
MAX_BACKOFF_SECONDS = 60
STOP_JOIN_SECONDS = 5
TYPING_DELAY_SECONDS = 0.5  # un comando risponde prima: niente "sta scrivendo" per un attimo
TYPING_INTERVAL_SECONDS = 4  # Telegram mostra l'azione per circa 5 secondi
RETRY_AFTER_LIMIT_SECONDS = 30  # un 429 con un'attesa più lunga non si ritenta
ALLOWED_UPDATES = ["message", "callback_query"]
REVEAL_PREFIX = "reveal:"
FORWARD_FIELDS = ("forward_origin", "forward_from", "forward_from_chat", "forward_sender_name", "forward_date")
STYLE_HINT = ("Rispondi in una chat di Telegram, letta spesso dal telefono: vai al punto, con paragrafi brevi; "
              "evita le tabelle larghe.")

START_TEXT = ("Ciao! Scrivimi e ti risponde l'agente.\n"
              "/nuova apre una conversazione nuova\n"
              "/stop ferma il turno in corso\n"
              "/link dà il link alla conversazione nell'app")
TEXT_ONLY = "Per ora leggo solo messaggi di testo."
REVEAL_GONE = "Non più disponibile: apri l'app."
# Un messaggio rimasto in coda da Telegram mentre il backend era fermo (fino a 24 h) non avvia un turno da solo
STALE_MESSAGE_SECONDS = 600
STALE_TEXT = ("Questo messaggio è arrivato {minutes} minuti fa, mentre il servizio era fermo: non l'ho eseguito. "
              "Se serve ancora, rimandalo.")

_START = re.compile(r"^/(start|help)(?:@\w+)?(?:\s.*)?$", re.DOTALL)
_TOKEN_SHAPE = re.compile(r"\d{3,}:[A-Za-z0-9_-]{20,}")
REDACTED = "<token>"


def redact(text: Any, token: str = "") -> str:
    """Il testo senza il token: quello dato e qualunque cosa abbia la forma di un token di bot (`<id>:<segreto>`)."""
    text = str(text)
    if token:
        text = text.replace(token, REDACTED)
    return _TOKEN_SHAPE.sub(REDACTED, text)


class _RedactFilter(logging.Filter):
    """Toglie il token dalle righe di log (messaggio già formattato) dei logger a cui è attaccato."""

    def __init__(self, token: str):
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        clean = redact(message, self._token)
        if clean != message:
            record.msg, record.args = clean, None
        return True


_FILTERED_LOGGERS = ("channels.telegram", "httpx")


class TelegramError(Exception):
    """Una chiamata alla Bot API non riuscita. Il messaggio non contiene mai il token."""

    def __init__(self, message: str, code: Optional[int] = None, retry_after: Optional[float] = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class _BotTransport(httpx.BaseTransport):
    """Aggiunge `/bot<token>` al percorso della richiesta solo qui, all'ultimo momento.

    httpx registra (log `HTTP Request: ...`) e allega alle eccezioni la richiesta che ha costruito, senza il token;
    un errore del trasporto si rilancia con il messaggio ripulito e senza la catena dell'eccezione originale."""

    def __init__(self, token: str, inner: httpx.BaseTransport):
        self._token = token
        self._inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        outgoing = httpx.Request(
            request.method, request.url.copy_with(path=f"/bot{self._token}{request.url.path}"),
            headers=request.headers, stream=request.stream, extensions=request.extensions)
        try:
            return self._inner.handle_request(outgoing)
        except httpx.RequestError as e:
            raise type(e)(redact(e, self._token), request=request) from None
        except Exception as e:
            raise httpx.TransportError(redact(f"{type(e).__name__}: {e}", self._token), request=request) from None

    def close(self) -> None:
        self._inner.close()


def _bot_transport() -> httpx.BaseTransport:
    """Il trasporto verso la Bot API (i test lo sostituiscono con una Bot API finta)."""
    return httpx.HTTPTransport()


def _make_bot_client(token: str, transport: Optional[httpx.BaseTransport] = None,
                     timeout: float = 15.0) -> httpx.Client:
    return httpx.Client(base_url=API_BASE, timeout=httpx.Timeout(timeout),
                        transport=_BotTransport(token, transport or _bot_transport()))


def _api_call(client: httpx.Client, token: str, method: str, params: Dict[str, Any],
              read_timeout: Optional[float] = None) -> Any:
    """Una chiamata alla Bot API: il risultato, o TelegramError con il messaggio già ripulito dal token."""
    timeout = httpx.Timeout(15.0, read=read_timeout) if read_timeout else httpx.USE_CLIENT_DEFAULT
    try:
        response = client.post(f"/{method}", json=params, timeout=timeout)
    except httpx.HTTPError as e:
        raise TelegramError(redact(f"{method}: {type(e).__name__}: {e}", token)) from None
    try:
        body = response.json()
    except ValueError:
        raise TelegramError(f"{method}: risposta non JSON (HTTP {response.status_code})",
                            code=response.status_code) from None
    if not isinstance(body, dict) or not body.get("ok"):
        body = body if isinstance(body, dict) else {}
        code = body.get("error_code") or response.status_code
        retry_after = (body.get("parameters") or {}).get("retry_after")
        raise TelegramError(redact(f"{method}: {code} {body.get('description', '')}".strip(), token),
                            code=code, retry_after=retry_after)
    return body.get("result")


def parse_allowed_users(raw: str) -> FrozenSet[int]:
    """`TELEGRAM_ALLOWED_USERS`: id numerici separati da virgola. Un valore che non è un id positivo è un errore."""
    ids = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit() or int(part) <= 0:
            raise ValueError(f"TELEGRAM_ALLOWED_USERS contiene {part!r}: servono id numerici, separati da virgola")
        ids.add(int(part))
    return frozenset(ids)


class TelegramChannel(Channel):
    def __init__(self, token: str, allowed_users: FrozenSet[int], hub: ChannelHub, clearance: Label = Label.INTERNAL,
                 transport: Optional[httpx.BaseTransport] = None, poll_timeout: int = POLL_TIMEOUT_SECONDS):
        if not token:
            raise ValueError("Serve il token del bot")
        if not allowed_users:
            raise ValueError("Serve almeno un utente ammesso")
        self._token = token
        self._allowed = frozenset(allowed_users)
        self._hub = hub
        self._transport = transport
        self._poll_timeout = poll_timeout
        self._caps = Capabilities(
            max_message_length=MAX_MESSAGE_LENGTH, text_format="html", buttons=True, accepted_inputs=("text",),
            style_hint=STYLE_HINT, clearance=clearance, confirm_up_to=Label.PRIVATE, max_messages=MAX_MESSAGES)
        self._client: Optional[httpx.Client] = None
        self._thread: Optional[threading.Thread] = None
        self._stopping = threading.Event()
        self._lock = threading.Lock()  # offset e gestione di un lotto di update
        self._offset: Optional[int] = None  # il prossimo update da chiedere
        self._acked: Optional[int] = None  # l'offset che Telegram ha già ricevuto (update precedenti confermati)
        self._filter = _RedactFilter(token)
        self.ignored: Counter = Counter()  # messaggi e pulsanti scartati, per tipo
        self.last_error: Optional[str] = None  # l'ultimo errore della Bot API (già ripulito); None dopo una lettura riuscita
        self._ignored_users: set = set()
        self._sleep: Callable[[float], None] = time.sleep

    # --- Channel -------------------------------------------------------------------------------

    @property
    def id(self) -> str:
        return CHANNEL_ID

    @property
    def capabilities(self) -> Capabilities:
        return self._caps

    @property
    def running(self) -> bool:
        """Il ciclo di polling è attivo."""
        thread = self._thread
        return thread is not None and thread.is_alive() and not self._stopping.is_set()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        for name in _FILTERED_LOGGERS:
            logging.getLogger(name).addFilter(self._filter)
        self._stopping = threading.Event()
        self._client = self._make_client()
        self._thread = threading.Thread(target=self._poll_loop, name="telegram-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stopping.set()
        # Una getUpdates nuova conferma gli update già gestiti e chiude quella in attesa (Telegram ne tiene una sola)
        self._acknowledge()
        thread.join(STOP_JOIN_SECONDS)
        if thread.is_alive():
            logger.warning("Il ciclo di Telegram non si è fermato in tempo: si chiude il client")
        client, self._client, self._thread = self._client, None, None
        if client is not None:
            client.close()
        for name in _FILTERED_LOGGERS:
            logging.getLogger(name).removeFilter(self._filter)

    def _make_client(self) -> httpx.Client:
        return _make_bot_client(self._token, self._transport)

    def deliver(self, chat_id: str, message: OutgoingMessage) -> None:
        chunks = [c for c in message.chunks if render.html_to_text(c).strip()] or [render.literal("(vuoto)", self._caps)]
        markup = self._keyboard(message)
        for i, chunk in enumerate(chunks):
            last = i == len(chunks) - 1
            self._send_message(chat_id, chunk, markup if last else None, message.link if last else None)

    # --- chiamate alla Bot API -------------------------------------------------------------------

    def _call(self, method: str, params: Dict[str, Any], read_timeout: Optional[float] = None) -> Any:
        client = self._client
        if client is None:
            raise TelegramError(f"{method}: canale fermo")
        try:
            return _api_call(client, self._token, method, params, read_timeout)
        except TelegramError as e:
            self.last_error = str(e)
            raise

    def _call_sending(self, method: str, params: Dict[str, Any]) -> Any:
        """Un invio: con un 429 si aspetta quanto chiede Telegram (se è poco) e si ritenta una volta."""
        try:
            return self._call(method, params)
        except TelegramError as e:
            if e.code != 429 or e.retry_after is None or e.retry_after > RETRY_AFTER_LIMIT_SECONDS:
                raise
            self._sleep(float(e.retry_after))
            return self._call(method, params)

    def _send_message(self, chat_id: str, text: str, markup: Optional[Dict[str, Any]], link: Optional[str]) -> None:
        params: Dict[str, Any] = {"chat_id": _chat(chat_id), "text": text, "parse_mode": "HTML",
                                  "link_preview_options": {"is_disabled": True}}
        if markup:
            params["reply_markup"] = markup
        try:
            self._call_sending("sendMessage", params)
            return
        except TelegramError as e:
            if e.code != 400:
                raise
            # HTML rifiutato o pulsante con un URL che Telegram non accetta: si manda testo semplice, il link in chiaro
            logger.warning(f"sendMessage rifiutato ({e}): lo mando come testo semplice")
        plain = render.html_to_text(text)
        callbacks = [[b for b in row if "url" not in b] for row in (markup or {}).get("inline_keyboard", [])]
        callbacks = [row for row in callbacks if row]
        had_url = any("url" in b for row in (markup or {}).get("inline_keyboard", []) for b in row)
        if had_url and link:
            plain = f"{plain}\n{link}"
        fallback: Dict[str, Any] = {"chat_id": _chat(chat_id), "text": plain[:MAX_MESSAGE_LENGTH],
                                    "link_preview_options": {"is_disabled": True}}
        if callbacks:
            fallback["reply_markup"] = {"inline_keyboard": callbacks}
        self._call_sending("sendMessage", fallback)

    def _keyboard(self, message: OutgoingMessage) -> Optional[Dict[str, Any]]:
        row = []
        for action in message.actions:
            if action.kind == "reveal" and action.token:
                data = REVEAL_PREFIX + action.token
                if len(data.encode()) <= CALLBACK_DATA_LIMIT:
                    row.append({"text": action.label, "callback_data": data})
            elif action.kind == "open" and message.link:
                row.append({"text": action.label, "url": message.link})
        return {"inline_keyboard": [row]} if row else None

    # --- ricezione -------------------------------------------------------------------------------

    def _poll_loop(self) -> None:
        stopping = self._stopping
        failures = 0
        while not stopping.is_set():
            with self._lock:
                offset = self._offset
            params: Dict[str, Any] = {"timeout": self._poll_timeout, "allowed_updates": ALLOWED_UPDATES}
            if offset is not None:
                params["offset"] = offset
            try:
                updates = self._call("getUpdates", params, read_timeout=self._poll_timeout + 15)
            except TelegramError as e:
                if stopping.is_set():
                    break
                failures += 1
                delay = _backoff(failures, e.retry_after)
                logger.warning(f"getUpdates non riuscita ({e}){_hint(e)}; nuovo tentativo tra {delay:.0f} s")
                stopping.wait(delay)
                continue
            failures = 0
            self.last_error = None
            with self._lock:
                if offset is not None:
                    self._acked = offset
                if stopping.is_set():
                    break  # il lotto non è confermato: Telegram lo ridà al prossimo avvio
                for update in updates or []:
                    self._take(update)

    def _take(self, update: Any) -> Optional[threading.Thread]:
        """Un update: l'offset avanza comunque (un update che fallisce non torna all'infinito)."""
        if not isinstance(update, dict) or not isinstance(update.get("update_id"), int):
            return None
        self._offset = max(self._offset or 0, update["update_id"] + 1)
        try:
            return self._handle_update(update)
        except Exception as e:
            logger.error(f"Update {update['update_id']} non gestito: {redact(e, self._token)}")
            return None

    def _acknowledge(self) -> None:
        with self._lock:
            offset = self._offset
        params: Dict[str, Any] = {"timeout": 0, "limit": 1}
        if offset is not None:
            params["offset"] = offset
        try:
            self._call("getUpdates", params)
            with self._lock:
                self._acked = offset
        except TelegramError as e:
            logger.warning(f"Conferma degli update alla chiusura non riuscita: {e}")

    def _handle_update(self, update: Dict[str, Any]) -> Optional[threading.Thread]:
        if "message" in update:
            return self._on_message(update["message"])
        if "callback_query" in update:
            return self._on_callback(update["callback_query"])
        return None

    def _allowed_private(self, user_id: Any, chat: Dict[str, Any]) -> bool:
        """Un utente ammesso, nella sua chat privata con il bot (in una chat privata l'id della chat è quello dell'utente)."""
        return (isinstance(user_id, int) and user_id in self._allowed
                and chat.get("type") == "private" and chat.get("id") == user_id)

    def _ignore(self, kind: str, user_id: Any) -> None:
        self.ignored[kind] += 1
        if user_id not in self._ignored_users and len(self._ignored_users) < 1000:
            self._ignored_users.add(user_id)
            logger.info(f"Telegram: {kind} da un utente non ammesso o fuori da una chat privata (id {user_id}): "
                        f"ignorato. Per ammetterlo, aggiungi l'id a TELEGRAM_ALLOWED_USERS")

    def _on_message(self, message: Dict[str, Any]) -> Optional[threading.Thread]:
        user_id = (message.get("from") or {}).get("id")
        chat = message.get("chat") or {}
        if not self._allowed_private(user_id, chat):
            self._ignore("message", user_id)
            return None
        chat_id = str(chat["id"])
        sent = message.get("date")
        age = time.time() - sent if isinstance(sent, (int, float)) else 0
        if age > STALE_MESSAGE_SECONDS:
            self.ignored["stale"] += 1
            return self._spawn(self._reply, chat_id, STALE_TEXT.format(minutes=int(age // 60)))
        text = message.get("text")
        if not isinstance(text, str):
            return self._spawn(self._reply, chat_id, TEXT_ONLY)
        forwarded = any(field in message for field in FORWARD_FIELDS)
        if not forwarded and _START.match(text.strip()):
            return self._spawn(self._reply, chat_id, START_TEXT)
        return self._spawn(self._run_inbound, InboundMessage(CHANNEL_ID, chat_id, str(user_id), text, forwarded=forwarded))

    def _on_callback(self, query: Dict[str, Any]) -> Optional[threading.Thread]:
        """Un pulsante premuto: vale solo dall'utente ammesso e nella chat del messaggio che lo porta (il hub controlla
        anche che il token sia di quella chat)."""
        user_id = (query.get("from") or {}).get("id")
        chat = (query.get("message") or {}).get("chat") or {}
        if not self._allowed_private(user_id, chat) or not query.get("id"):
            self._ignore("callback", user_id)
            return None
        return self._spawn(self._resolve_callback, str(query["id"]), str(chat["id"]), str(query.get("data") or ""))

    def _resolve_callback(self, query_id: str, chat_id: str, data: str) -> None:
        shown = data.startswith(REVEAL_PREFIX) and self._hub.reveal(data[len(REVEAL_PREFIX):], chat_id)
        params: Dict[str, Any] = {"callback_query_id": query_id}
        if not shown:
            params["text"] = REVEAL_GONE
        try:
            self._call("answerCallbackQuery", params)
        except TelegramError as e:
            logger.warning(f"answerCallbackQuery non riuscita: {e}")

    def _run_inbound(self, message: InboundMessage) -> None:
        done = threading.Event()
        typing = threading.Thread(target=self._typing, args=(message.chat_id, done), name="telegram-typing", daemon=True)
        typing.start()
        try:
            self._hub.handle_inbound(message)
        finally:
            done.set()

    def _typing(self, chat_id: str, done: threading.Event) -> None:
        delay = TYPING_DELAY_SECONDS
        while not done.wait(delay):
            try:
                self._call("sendChatAction", {"chat_id": _chat(chat_id), "action": "typing"})
            except TelegramError as e:
                logger.debug(f"sendChatAction non riuscita: {e}")
            delay = TYPING_INTERVAL_SECONDS

    def _reply(self, chat_id: str, text: str) -> None:
        try:
            self.deliver(chat_id, OutgoingMessage([render.literal(text, self._caps)]))
        except TelegramError as e:
            logger.warning(f"Risposta a {chat_id} non consegnata: {e}")

    def _spawn(self, target: Callable[..., None], *args: Any) -> threading.Thread:
        worker = threading.Thread(target=target, args=args, name="telegram-update", daemon=True)
        worker.start()
        return worker


def _chat(chat_id: str) -> Any:
    return int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id


def _backoff(failures: int, retry_after: Optional[float]) -> float:
    delay = min(MAX_BACKOFF_SECONDS, 2 ** (failures - 1))
    return float(max(delay, min(retry_after or 0, MAX_BACKOFF_SECONDS * 5)))


def _hint(error: TelegramError) -> str:
    if error.code == 401:
        return ": il token è stato rifiutato, controlla il token del bot (Impostazioni > Canali o TELEGRAM_BOT_TOKEN)"
    if error.code == 409:
        return ": un'altra istanza legge lo stesso bot, oppure il bot ha un webhook (questo canale usa il long polling)"
    return ""


# --- configurazione ---------------------------------------------------------------------------------

def config_problem(r: runtime_settings.Resolved) -> Optional[str]:
    """Perché il canale non si costruisce, quando la UI non lo vede dai campi (token illeggibile, utenti del `.env` non
    validi); None se manca solo il token, è spento o non ha utenti: quello si legge dai campi."""
    if r.secrets_unreadable:
        return "Il token salvato non si legge (API_SECRET_KEY è cambiata?): inseriscilo di nuovo."
    if not r.secret("bot_token").strip():
        return None
    if "allowed_users" in r.env_errors and r.values["allowed_users"][1] != "ui":
        return r.env_errors["allowed_users"]
    return None


def from_settings(hub: ChannelHub, transport: Optional[httpx.BaseTransport] = None) -> Optional[TelegramChannel]:
    """Il canale dai valori effettivi (UI, altrimenti `.env`), o None (con il motivo nel log) se è spento o
    configurato a metà."""
    r = runtime_settings.snapshot("telegram")
    token = r.secret("bot_token").strip()
    problem = config_problem(r)
    if problem:
        logger.error(f"Canale Telegram non avviato: {problem}")
        return None
    if not token:
        logger.debug("Canale Telegram spento: nessun token del bot")
        return None
    if not r.value("enabled"):
        logger.info("Canale Telegram spento dalle impostazioni")
        return None
    allowed = frozenset(r.value("allowed_users"))
    if not allowed:
        logger.error("Canale Telegram non avviato: con il token servono gli utenti ammessi (TELEGRAM_ALLOWED_USERS, id "
                     "numerici separati da virgola, oppure Impostazioni > Canali)")
        return None
    clearance = Label.parse(r.value("clearance"), Label.PUBLIC)
    return TelegramChannel(token, allowed, hub, clearance=clearance, transport=transport)


def apply_settings(hub: Optional[ChannelHub] = None) -> Optional[TelegramChannel]:
    """Dopo un salvataggio delle impostazioni: il canale nuovo prende il posto del vecchio (che si ferma), oppure il
    vecchio si ferma e basta se ora è spento o incompleto. Nessun riavvio del backend."""
    from app.channels.hub import get_hub
    hub = hub or get_hub()
    channel = from_settings(hub)
    if channel is None:
        if hub.unregister(CHANNEL_ID) is not None:
            logger.info("Canale Telegram fermato dalle impostazioni")
        return None
    hub.replace(channel)
    logger.info(f"Canale Telegram riconfigurato: {len(channel._allowed)} utenti ammessi, livello "
                f"{channel.capabilities.clearance.key} senza conferma")
    return channel


def probe(token: str) -> Dict[str, Any]:
    """"Prova il bot": `getMe` con il token dato. Solo `{ok, bot_username, error}`: mai il token, nemmeno nell'errore."""
    log_filter = _RedactFilter(token)
    for name in _FILTERED_LOGGERS:
        logging.getLogger(name).addFilter(log_filter)
    try:
        with _make_bot_client(token, timeout=10.0) as client:
            me = _api_call(client, token, "getMe", {})
    except TelegramError as e:
        return {"ok": False, "bot_username": None, "error": redact(f"{e}{_hint(e)}", token)}
    finally:
        for name in _FILTERED_LOGGERS:
            logging.getLogger(name).removeFilter(log_filter)
    username = me.get("username") if isinstance(me, dict) else None
    return {"ok": True, "bot_username": username if isinstance(username, str) else None, "error": None}


def register_configured(hub: ChannelHub) -> Optional[TelegramChannel]:
    """Registra il canale nel hub se è configurato (una volta sola): parte con il hub, nel lifespan dell'applicazione."""
    existing = hub.get(CHANNEL_ID)
    if existing is not None:
        return existing  # type: ignore[return-value]
    channel = from_settings(hub)
    if channel is not None:
        hub.register(channel)
        logger.info(f"Canale Telegram configurato: {len(channel._allowed)} utenti ammessi, livello "
                    f"{channel.capabilities.clearance.key} senza conferma")
    return channel
