"""Profili di ragionamento dei modelli: dal livello richiesto da una fase del turno ai parametri della richiesta.

Le fasi chiedono un livello astratto (`off`, `low`, `medium`, `high`); il profilo del modello lo traduce:
- se il ragionamento si accende e si spegne (`hybrid`), è sempre attivo (`always`) o non esiste (`none`);
- quale livello del template usare, dove il modello ne ha (`reasoning_effort` di Qwen3.8);
- quanti token concedere: il budget viene sempre inviato in modo esplicito, mai lasciato al default del preset;
- il campionamento raccomandato dal produttore, con e senza ragionamento.

I valori vengono dalle schede dei modelli (docs/reasoning/REASONING_RESEARCH.md, sezione 5). Un modello senza profilo
riceve l'interruttore e il budget, che i template senza ragionamento ignorano, e nessun campionamento oltre alla
temperatura chiesta dal chiamante.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

Level = Literal["off", "low", "medium", "high"]
Kind = Literal["hybrid", "always", "none", "unknown"]

LEVEL_BUDGETS: Dict[str, int] = {"off": 0, "low": 512, "medium": 2048, "high": 8192}
# Frase forzata prima del tag di chiusura quando il budget finisce: il modello risponde sapendo di dover chiudere
BUDGET_MESSAGE = "\n\nI have to stop thinking here and answer with what I have.\n"


@dataclass(frozen=True)
class Sampling:
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    presence_penalty: Optional[float] = None
    repeat_penalty: Optional[float] = None

    def params(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass(frozen=True)
class Profile:
    family: str
    kind: Kind
    thinking: Sampling = field(default_factory=Sampling)  # con il ragionamento attivo
    plain: Sampling = field(default_factory=Sampling)  # senza ragionamento
    efforts: Dict[str, str] = field(default_factory=dict)  # livello → valore di `reasoning_effort` del template
    min_budget: int = 0  # per i modelli sempre ragionanti: il budget non scende mai a 0
    # Il template conserva il pensiero dei messaggi dell'assistente dopo l'ultima domanda dell'utente anche senza
    # `tool_calls`: l'agent loop può rimandarlo passo dopo passo (docs/reasoning/INTERLEAVED_THINKING.md)
    interleaved: bool = False


# Gemma 4 conserva il pensiero solo nei messaggi con `tool_calls`, che l'agent loop non produce: niente interleaved.
# LFM2.5 lo conserva, ma misurato rende peggio.
# Ordine significativo: vince il primo pattern che corrisponde al nome del modello (alias del preset)
PROFILES = [
    (r"qwen3\.6", Profile(
        "Qwen3.6", "hybrid",
        # Valori "coding preciso" della scheda: chiamate a tool e piani vogliono precisione più che varietà
        thinking=Sampling(temperature=0.6, top_p=0.95, top_k=20, min_p=0.0, presence_penalty=0.0, repeat_penalty=1.0),
        plain=Sampling(temperature=0.7, top_p=0.8, top_k=20, min_p=0.0, presence_penalty=1.5, repeat_penalty=1.0),
        interleaved=True,
    )),
    (r"qwen3\.8", Profile(
        "Qwen3.8", "hybrid",
        thinking=Sampling(temperature=1.0, top_p=0.95, top_k=20, min_p=0.0, presence_penalty=0.0, repeat_penalty=1.0),
        plain=Sampling(temperature=0.7, top_p=0.8, top_k=20, min_p=0.0, presence_penalty=1.5, repeat_penalty=1.0),
        efforts={"low": "low", "medium": "medium", "high": "xhigh"},
        interleaved=True,
    )),
    (r"qwen3", Profile(
        "Qwen3", "hybrid",
        thinking=Sampling(temperature=0.6, top_p=0.95, top_k=20, min_p=0.0),
        plain=Sampling(temperature=0.7, top_p=0.8, top_k=20, min_p=0.0),
        interleaved=True,
    )),
    (r"gemma-?4", Profile(
        "Gemma 4", "hybrid",
        thinking=Sampling(temperature=1.0, top_p=0.95, top_k=64),
        plain=Sampling(temperature=1.0, top_p=0.95, top_k=64),
    )),
    (r"lfm2\.5", Profile(
        "LFM2.5", "always",
        thinking=Sampling(temperature=0.1, top_k=50, repeat_penalty=1.05),
        min_budget=256,
        # Il template conserva il pensiero, ma su `multistep` (2026-10-31) con il pensiero conservato il modello fa più
        # chiamate, più comandi e supera meno casi (35% contro 42%): resta lo storico in testo
        interleaved=False,
    )),
    (r"phi-?4", Profile("Phi-4", "none")),
]
UNKNOWN = Profile("sconosciuto", "unknown")


def profile_for(model: Optional[str]) -> Profile:
    name = str(model or "").lower()
    return next((profile for pattern, profile in PROFILES if re.search(pattern, name)), UNKNOWN)


def interleaved_for(model: Optional[str]) -> bool:
    """Se l'agent loop rimanda al modello il pensiero dei passi precedenti: dal profilo, salvo AGENT_INTERLEAVED_THINKING."""
    from app.core.config import settings

    override = settings.agent_interleaved_thinking.strip().lower()
    if override in ("on", "off"):
        return override == "on"
    return profile_for(model).interleaved


@dataclass(frozen=True)
class Reasoning:
    """Come una singola richiesta usa il ragionamento."""

    enabled: bool
    budget: int  # token di ragionamento concessi (0 = chiusura immediata)
    effort: Optional[str] = None
    sampling: Sampling = field(default_factory=Sampling)
    send_controls: bool = True  # False per i modelli senza ragionamento: nessun parametro di ragionamento

    def payload(self) -> Dict[str, Any]:
        """Parametri di ragionamento per llama.cpp (`/v1/chat/completions`)."""
        if not self.send_controls:
            return {}
        kwargs: Dict[str, Any] = {"enable_thinking": self.enabled}
        if self.effort:
            kwargs["reasoning_effort"] = self.effort
        params: Dict[str, Any] = {"chat_template_kwargs": kwargs, "reasoning_budget_tokens": self.budget}
        if self.enabled and self.budget > 0:
            params["reasoning_budget_message"] = BUDGET_MESSAGE
        return params


def resolve(model: Optional[str], level: Level = "off", *, budget_override: Optional[int] = None,
            temperature: Optional[float] = None) -> Reasoning:
    """Ragionamento e campionamento di una richiesta.

    `budget_override` è il budget in token scelto dall'utente per il turno: vale per le fasi che ragionano (0 lo
    spegne); le fasi `off` restano spente. `temperature` è quella chiesta dal chiamante: vale senza ragionamento (o per i
    modelli senza profilo), perché i modelli in modalità ragionamento degradano a temperature basse (ripetizioni).
    """
    profile = profile_for(model)
    budget = LEVEL_BUDGETS[level]
    if level != "off" and budget_override is not None and budget_override >= 0:
        budget = budget_override
    if profile.kind == "none":
        return Reasoning(False, 0, sampling=_with_temperature(profile.plain, temperature), send_controls=False)
    if profile.kind == "always":
        return Reasoning(True, max(budget, profile.min_budget), sampling=profile.thinking)
    if budget <= 0:
        return Reasoning(False, 0, sampling=_with_temperature(profile.plain, temperature))
    effort = profile.efforts.get(level) if level != "off" else None
    sampling = profile.thinking if profile.thinking.params() else _with_temperature(profile.thinking, temperature)
    return Reasoning(True, budget, effort=effort, sampling=sampling)


def _with_temperature(sampling: Sampling, temperature: Optional[float]) -> Sampling:
    """Senza ragionamento la temperatura del chiamante (per esempio bassa per un output strutturato) prevale, da sola:
    le penalità pensate per la conversazione non vanno applicate a un JSON."""
    return sampling if temperature is None else Sampling(temperature=temperature)
