"""Ruoli delle chiamate al modello: ogni chiamata dichiara a quale scopo serve.

Il ruolo finisce nelle metriche (`llm_calls.role`) e, nelle fasi successive, guiderà la scelta del provider
(docs/providers/PROVIDERS_DESIGN.md, sezioni 5.2 e 5.5). Come `tag`, è obbligatorio e senza default.
"""
from typing import Dict

ROUTE = "route"
PLAN = "plan"
SELECT_TOOL = "select_tool"
REWRITE_EXIT = "rewrite_exit"
ANSWER = "answer"
PREFETCH = "prefetch"
FILTER_MEMORY = "filter_memory"
CONSOLIDATE = "consolidate"
TITLE = "title"
VISION = "vision"
ROLLBACK = "rollback"
EVAL = "eval"

# Ruolo -> cosa fa la chiamata
ROLE_DESCRIPTIONS: Dict[str, str] = {
    ROUTE: "Router della modalità: sceglie come trattare il messaggio",
    PLAN: "Piano e sua revisione",
    SELECT_TOOL: "Scelta del tool a ogni passo del loop",
    REWRITE_EXIT: "Riscrittura pulita degli argomenti di un'uscita, senza dati che la destinazione non può ricevere",
    ANSWER: "Risposta della chat, risposta diretta, sintesi finale, sintesi dopo un'approvazione",
    PREFETCH: "Riassunto della ricerca web iniziale",
    FILTER_MEMORY: "Scelta dei ricordi pertinenti alla richiesta",
    CONSOLIDATE: "Estrazione dei fatti, consolidamento della memoria, distillazione delle procedure",
    TITLE: "Titolo della conversazione",
    VISION: "Descrizione di un'immagine",
    ROLLBACK: "Piano di rollback dei passi eseguiti",
    EVAL: "Giudizio nelle valutazioni dei modelli",
}

VALID_ROLES = frozenset(ROLE_DESCRIPTIONS)


def check_role(role: str) -> str:
    """Il ruolo se è noto, altrimenti ValueError."""
    if role not in VALID_ROLES:
        raise ValueError(f"Ruolo LLM sconosciuto: {role!r} (validi: {', '.join(sorted(VALID_ROLES))})")
    return role
