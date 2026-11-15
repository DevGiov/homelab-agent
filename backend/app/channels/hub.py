"""Il hub dei canali: registra i canali, li avvia con l'applicazione e porta un messaggio in arrivo fino alla risposta.

Ogni messaggio che esce verso un canale è un'uscita di dati (design 4.3): prima di consegnare la risposta si applica
`can_flow(sensibilità della risposta, destinazione del canale)`, e ogni consegna finisce nell'audit con destinazione
`channel:<id>`, etichetta ed esito, dove la vista delle uscite di dati della Web UI la legge.
"""
import logging
import queue
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.agent.stream_session import StreamSession
from app.api import agent_runner
from app.channels import render, threads
from app.channels.base import Action, Channel, InboundMessage, OutgoingMessage
from app.core.config import settings
from app.security import audit_log, flows
from app.security.flows import Label, Tag

logger = logging.getLogger("channels")

# Esiti registrati nell'audit: gli stessi della vista delle uscite (`ask` = chiesta conferma, `approved` = confermata)
ALLOW, ASK, APPROVED, DENY = "allow", "ask", "approved", "deny"
EXIT_TOOL_NAME = "channel_delivery"

# Una risposta oltre il livello del canale resta sul server per questo tempo, in attesa che l'utente scelga "Mostra qui"
REVEAL_TTL_SECONDS = 600
MAX_PENDING = 100

_COMMAND = re.compile(r"^/(nuova|stop|link)(?:@\w+)?$")

BUSY_TEXT = "c'è già un turno in corso: /stop per fermarlo"


@dataclass
class _Pending:
    """Una risposta trattenuta: sta solo in memoria (C0). Un riavvio del backend la perde e l'utente la apre nell'app."""
    channel: str
    chat_id: str
    thread_id: str
    text: str
    label: Label
    expires: float


class ChannelHub:
    def __init__(self) -> None:
        self._channels: Dict[str, Channel] = {}
        self._pending: Dict[str, _Pending] = {}
        self._lock = threading.Lock()

    # --- registrazione e ciclo di vita ----------------------------------------------------------

    def register(self, channel: Channel) -> None:
        if channel.id in self._channels:
            raise ValueError(f"Canale già registrato: {channel.id}")
        self._channels[channel.id] = channel

    def get(self, channel_id: str) -> Optional[Channel]:
        return self._channels.get(channel_id)

    def start(self) -> None:
        """Avvia i canali registrati; senza canali non parte nulla. Un canale che non parte non ferma gli altri."""
        for channel in self._channels.values():
            try:
                channel.start()
                logger.info(f"Canale '{channel.id}' avviato")
            except Exception as e:
                logger.error(f"Canale '{channel.id}' non avviato: {e}", exc_info=True)

    def stop(self) -> None:
        for channel in reversed(list(self._channels.values())):
            try:
                channel.stop()
            except Exception as e:
                logger.error(f"Canale '{channel.id}' non fermato: {e}", exc_info=True)

    # --- messaggi in arrivo --------------------------------------------------------------------

    def dispatch(self, message: InboundMessage) -> threading.Thread:
        """`handle_inbound` in un thread: un canale che riceve con un solo ciclo non deve restare fermo mentre il turno
        gira, altrimenti `/stop` non arriva mai."""
        worker = threading.Thread(target=self.handle_inbound, args=(message,), daemon=True)
        worker.start()
        return worker

    def handle_inbound(self, message: InboundMessage) -> None:
        """Porta un messaggio dall'utente alla risposta. Bloccante fino alla fine del turno (o al timeout)."""
        channel = self._channels.get(message.channel)
        if channel is None:
            logger.warning(f"Messaggio per un canale sconosciuto: {message.channel}")
            return
        try:
            self._handle(channel, message)
        except Exception as e:
            logger.error(f"Messaggio del canale '{channel.id}' non gestito: {e}", exc_info=True)

    def _handle(self, channel: Channel, message: InboundMessage) -> None:
        chat_id = message.chat_id
        text = (message.text or "").strip()
        # Un messaggio inoltrato è testo scritto da altri: non è mai un comando
        command = None if message.forwarded else _COMMAND.match(text)
        if command:
            self._command(channel, chat_id, command.group(1))
            return
        if not text and not message.images:
            return

        thread_id = threads.current_thread(channel.id, chat_id)
        if agent_runner.thread_has_active_turn(thread_id):
            # La Web UI qui salverebbe il messaggio e si aggancerebbe al turno; per un canale è confuso: non si salva
            self._reply(channel, chat_id, BUSY_TEXT)
            return

        extra_tag = flows.tag_of(Label.PUBLIC, "messaggio inoltrato", untrusted=True) if message.forwarded else None
        sess = agent_runner.start_turn(
            message.text, thread_id, images=list(message.images) or None, channel=channel.id, extra_tag=extra_tag,
            style_hint=channel.capabilities.style_hint)
        outcome, payload = _wait(sess, settings.channel_reply_timeout_seconds)
        if outcome == "final":
            self._deliver_answer(channel, chat_id, thread_id, payload)
        elif outcome == "timeout":
            self._notice(channel, chat_id, "La risposta richiede più tempo: la troverai nell'app.", thread_id)
        elif outcome == "error":
            self._notice(channel, chat_id, "Il turno non è riuscito: i dettagli sono nell'app.", thread_id)
        # "stopped": l'utente ha già avuto la risposta di /stop

    def _command(self, channel: Channel, chat_id: str, name: str) -> None:
        if name == "nuova":
            threads.new_thread(channel.id, chat_id)
            self._reply(channel, chat_id, "Conversazione nuova aperta.")
        elif name == "stop":
            thread_id = threads.current_thread(channel.id, chat_id)
            stopped = agent_runner.thread_has_active_turn(thread_id) and agent_runner.stop_turn(thread_id)
            self._reply(channel, chat_id, "Turno fermato." if stopped else "Nessun turno in corso.")
        else:  # link
            link = self.thread_link(threads.current_thread(channel.id, chat_id))
            self._reply(channel, chat_id, link or "Nessun link configurato: imposta WEB_UI_URL nel .env del backend.")

    # --- consegna: il controllo di sensibilità --------------------------------------------------

    def _deliver_answer(self, channel: Channel, chat_id: str, thread_id: str, final: Dict[str, Any]) -> None:
        if final.get("approval_required"):
            # Le approvazioni da canale arrivano con la fase C2: per ora si aprono nell'app
            self._notice(channel, chat_id, "Serve un'approvazione: apri l'app.", thread_id)
            return
        text = final.get("response") or ""
        raw_tag = final.get("sensitivity")
        # Senza etichetta nella risposta non si presume `public`: si tratta come `private`
        tag = Tag.from_dict(raw_tag) if raw_tag else flows.tag_of(Label.PRIVATE, "sensibilità non indicata")
        if flows.can_flow(tag, channel.destination()).allowed:
            self._record(channel, thread_id, tag.label, ALLOW, text)
            self._send_text(channel, chat_id, text)
        elif self._confirmable(channel, tag.label):
            token = self._hold(channel.id, chat_id, thread_id, text, tag.label)
            link = self.thread_link(thread_id)
            actions = [Action("reveal", "Mostra qui", token)]
            if link:
                actions.append(Action("open", "Apri nell'app", token))
            self._record(channel, thread_id, tag.label, ASK, text)
            self._deliver(channel, chat_id, OutgoingMessage([f"La risposta contiene dati {tag.label.key}."], actions, link))
        else:
            self._record(channel, thread_id, tag.label, DENY, text)
            what = "un segreto" if tag.label == Label.SECRET else f"dati {tag.label.key}"
            self._notice(channel, chat_id, f"La risposta contiene {what} e non la mostro qui.", thread_id)

    def _confirmable(self, channel: Channel, label: Label) -> bool:
        """Oltre il livello del canale, ma entro quello che l'utente può confermare (serve un modo di confermare)."""
        caps = channel.capabilities
        return (label < Label.SECRET and caps.buttons and caps.confirm_up_to is not None
                and label <= caps.confirm_up_to)

    def reveal(self, token: str, chat_id: Optional[str] = None) -> bool:
        """L'utente ha scelto "Mostra qui": consegna la risposta trattenuta. Vale una volta sola e fino alla scadenza;
        `chat_id` (se dato) deve essere la chat a cui era destinata. False se il token non c'è, è scaduto o è di un'altra chat."""
        with self._lock:
            pending = self._pending.get(token)
            if pending is None or (chat_id is not None and str(chat_id) != pending.chat_id):
                return False
            del self._pending[token]
            expired = pending.expires < time.monotonic()
        channel = self._channels.get(pending.channel)
        if channel is None:
            return False
        if expired:
            self._notice(channel, pending.chat_id, "La richiesta è scaduta: apri l'app.", pending.thread_id)
            return False
        if not self._confirmable(channel, pending.label):
            self._notice(channel, pending.chat_id, "Questa risposta non si può mostrare qui: apri l'app.", pending.thread_id)
            return False
        self._record(channel, pending.thread_id, pending.label, APPROVED, pending.text)
        self._send_text(channel, pending.chat_id, pending.text)
        return True

    def _hold(self, channel_id: str, chat_id: str, thread_id: str, text: str, label: Label) -> str:
        token = secrets.token_urlsafe(16)
        now = time.monotonic()
        with self._lock:
            for key in [k for k, p in self._pending.items() if p.expires < now]:
                del self._pending[key]
            while len(self._pending) >= MAX_PENDING:
                del self._pending[next(iter(self._pending))]
            self._pending[token] = _Pending(channel_id, str(chat_id), thread_id, text, label, now + REVEAL_TTL_SECONDS)
        return token

    # --- invio ----------------------------------------------------------------------------------

    def thread_link(self, thread_id: str) -> Optional[str]:
        base = (settings.web_ui_url or "").strip().rstrip("/")
        return f"{base}/c/{thread_id}" if base else None

    def _record(self, channel: Channel, thread_id: str, label: Label, outcome: str, text: str) -> None:
        """Ogni consegna è un'uscita di dati: destinazione, etichetta ed esito nell'audit (mai il testo della risposta)."""
        audit_log.log_tool_call(
            EXIT_TOOL_NAME, {"summary": f"risposta sul canale {channel.id} ({len(text)} caratteri)"},
            thread_id=thread_id, registry="channel", result={"outcome": outcome},
            flow={"label": label.key, "destination": channel.destination().id, "flow": outcome})

    def _send_text(self, channel: Channel, chat_id: str, text: str) -> None:
        chunks: List[str] = render.render_chunks(text, channel.capabilities) or ["(risposta vuota)"]
        self._deliver(channel, chat_id, OutgoingMessage(chunks))

    def _notice(self, channel: Channel, chat_id: str, text: str, thread_id: str) -> None:
        """Un avviso con il link alla conversazione (o senza, se WEB_UI_URL è vuoto: lo dice)."""
        link = self.thread_link(thread_id)
        self._deliver(channel, chat_id, OutgoingMessage([text if link else f"{text} (nessun link configurato)"],
                                                       [Action("open", "Apri nell'app")] if link and channel.capabilities.buttons else [], link))

    def _reply(self, channel: Channel, chat_id: str, text: str) -> None:
        self._deliver(channel, chat_id, OutgoingMessage([text]))

    def _deliver(self, channel: Channel, chat_id: str, message: OutgoingMessage) -> None:
        if not channel.capabilities.buttons:
            message.actions = []
        channel.deliver(chat_id, message)


def _wait(sess: StreamSession, timeout: float):
    """Aspetta la fine del turno: ("final", risposta), ("error", testo), ("stopped", None) o ("timeout", None).

    Ci si iscrive alla sessione solo per essere svegliati; l'esito si legge dallo stato della sessione, che il turno ha
    già scritto se è finito prima dell'iscrizione."""
    inbox = sess.subscribe()
    deadline = time.monotonic() + timeout
    try:
        while True:
            if sess.is_stopped():
                return "stopped", None
            if sess.final_response is not None:
                return "final", sess.final_response
            if sess.error is not None:
                return "error", sess.error
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "timeout", None
            try:
                item = inbox.get(timeout=min(0.25, remaining))
            except queue.Empty:
                continue
            if item is None and sess.final_response is None and sess.error is None and not sess.is_stopped():
                return "error", "Turno terminato senza risposta"
    finally:
        sess.unsubscribe(inbox)


_hub: Optional[ChannelHub] = None
_hub_lock = threading.Lock()


def get_hub() -> ChannelHub:
    """Il hub dell'applicazione. I canali configurati si registrano qui prima di `startup.start` (nessuno in C0)."""
    global _hub
    with _hub_lock:
        if _hub is None:
            _hub = ChannelHub()
        return _hub
