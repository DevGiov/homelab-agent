"""Interfaccia di un canale: cosa sa fare (`Capabilities`), cosa riceve e cosa manda."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.security import flows
from app.security.flows import Destination, Label

TEXT_FORMATS = ("markdown", "html", "plain")


@dataclass(frozen=True)
class Capabilities:
    """Cosa sa fare un canale. L'agente adatta la risposta (`style_hint`) e il hub decide cosa può consegnare.

    `clearance`: l'etichetta più alta consegnata senza chiedere. `confirm_up_to`: la più alta consegnata dopo che
    l'utente ha confermato (richiede `buttons`), None se oltre `clearance` non si consegna mai. `secret` non esce comunque.
    `max_messages`: quanti messaggi al massimo per una risposta; oltre, l'inizio e il link all'app (None = nessun limite)."""
    max_message_length: int
    text_format: str = "plain"
    buttons: bool = False
    accepted_inputs: Tuple[str, ...] = ("text",)
    style_hint: str = ""
    clearance: Label = Label.INTERNAL
    confirm_up_to: Optional[Label] = None
    max_messages: Optional[int] = None

    def __post_init__(self):
        if self.max_message_length < 1:
            raise ValueError("max_message_length deve essere almeno 1")
        if self.max_messages is not None and self.max_messages < 2:
            raise ValueError("max_messages deve essere almeno 2 (l'inizio della risposta e l'avviso)")
        if self.text_format not in TEXT_FORMATS:
            raise ValueError(f"text_format non valido: {self.text_format!r} ({', '.join(TEXT_FORMATS)})")
        if self.clearance >= Label.SECRET or (self.confirm_up_to is not None and self.confirm_up_to >= Label.SECRET):
            raise ValueError("Nessun canale riceve un segreto")
        if self.confirm_up_to is not None and self.confirm_up_to < self.clearance:
            raise ValueError("confirm_up_to non può stare sotto clearance")


@dataclass(frozen=True)
class InboundMessage:
    """Un messaggio dell'utente, come lo consegna il canale. `forwarded`: testo scritto da altri (messaggio inoltrato)."""
    channel: str
    chat_id: str
    user_id: str
    text: str
    images: Tuple[str, ...] = ()
    forwarded: bool = False


@dataclass(frozen=True)
class Action:
    """Un'azione che il canale offre sotto un messaggio: `reveal` (mostra qui, con `token`) o `open` (apri nell'app, con
    il `link` del messaggio). Il token è opaco: il canale lo restituisce a `ChannelHub.reveal` quando l'utente sceglie."""
    kind: str
    label: str
    token: Optional[str] = None


@dataclass
class OutgoingMessage:
    """Cosa il hub manda a una chat: pezzi di testo già nel formato del canale e della lunghezza ammessa, le azioni (solo
    se il canale ha i pulsanti) e il link alla conversazione nella Web UI, che il canale mostra (pulsante o in coda al testo)."""
    chunks: List[str]
    actions: List[Action] = field(default_factory=list)
    link: Optional[str] = None


class Channel(ABC):
    """Un canale di messaggistica. `start` e `stop` avviano e fermano il ciclo che riceve (un thread proprio):
    `start` ritorna subito. I messaggi in arrivo vanno a `ChannelHub.handle_inbound` (bloccante fino alla risposta: il
    canale lo chiama in un thread per messaggio, `ChannelHub.dispatch`)."""

    @property
    @abstractmethod
    def id(self) -> str:
        """Identificatore stabile, per esempio "telegram"."""

    @property
    @abstractmethod
    def capabilities(self) -> Capabilities:
        ...

    def destination(self) -> Destination:
        """La destinazione della regola di sensibilità, con il livello dichiarato nelle capacità."""
        return flows.channel_destination(self.id, self.capabilities.clearance)

    @abstractmethod
    def start(self) -> None:
        ...

    @abstractmethod
    def stop(self) -> None:
        ...

    @abstractmethod
    def deliver(self, chat_id: str, message: OutgoingMessage) -> None:
        """Manda il messaggio alla chat. Un errore di consegna si solleva: il hub lo registra."""
