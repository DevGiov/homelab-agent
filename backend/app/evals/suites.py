"""Suite di valutazione: per ogni suite un esecutore (chiama il modello senza effetti collaterali: nessun tool
eseguito, nessun fatto salvato nella memoria reale) e un giudizio puro sul risultato, testabile senza LLM.

La suite `recall` scrive conversazioni e fatti, ma in un database temporaneo per caso (`memory_sandbox`).

Un giudizio restituisce `Outcome`: superato o no, con una riga che spiega l'esito; `skipped` quando il caso
non è valutabile in questo deploy (per esempio il tool atteso non è nel catalogo).
"""
import json
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional
from unittest.mock import patch

from pydantic import BaseModel

CASES_DIR = Path(__file__).parent / "cases"


@dataclass
class Outcome:
    passed: bool
    detail: str
    skipped: bool = False


def load_cases(suite: str) -> List[Dict[str, Any]]:
    return json.loads((CASES_DIR / f"{suite}.json").read_text(encoding="utf-8"))


def _short(tool: Optional[str]) -> str:
    return (tool or "").split("__")[-1]


def _same_tool(a: Optional[str], b: Optional[str]) -> bool:
    """Stesso tool anche senza prefisso del server (i modelli a volte lo omettono)."""
    return bool(a) and bool(b) and (a == b or _short(a) == _short(b))


# --- Giudizi ---


def grade_routing(case: Dict[str, Any], mode: str, web_search_needed: bool) -> Outcome:
    if mode != case["expected_mode"]:
        return Outcome(False, f"modalità {mode}, attesa {case['expected_mode']}")
    if "expect_web" in case and web_search_needed != case["expect_web"]:
        return Outcome(False, f"ricerca web {'sì' if web_search_needed else 'no'}, attesa {'sì' if case['expect_web'] else 'no'}")
    return Outcome(True, f"modalità {mode}")


def grade_tool(case: Dict[str, Any], chosen: List[str], arguments: Dict[str, Any], catalog: Iterable[str]) -> Outcome:
    expected = case.get("expected_tool")
    if expected is None:
        return Outcome(not chosen, "nessun tool" if not chosen else f"tool non necessario: {', '.join(chosen)}")
    acceptable = [expected, *case.get("accept_tools", [])]
    catalog = list(catalog)
    if not any(any(_same_tool(a, c) for c in catalog) for a in acceptable):
        return Outcome(False, f"{expected} non è nel catalogo", skipped=True)
    picked = next((c for c in chosen if any(_same_tool(c, a) for a in acceptable)), None)
    if picked is None:
        return Outcome(False, f"scelto {', '.join(chosen) or 'nessun tool'}, atteso {expected}")
    wrong = {k: arguments.get(k) for k, v in case.get("expected_args", {}).items() if str(arguments.get(k)) != str(v)}
    if wrong:
        return Outcome(False, f"{picked} con argomenti errati: {wrong}")
    return Outcome(True, picked)


def grade_plan(case: Dict[str, Any], structure: Optional[Dict[str, Any]], catalog: Iterable[str]) -> Outcome:
    if not structure:
        return Outcome(False, "nessun piano strutturato valido")
    catalog = list(catalog)
    tools = [step.get("tool") for step in structure["steps"]]
    unknown = [t for t in tools if not any(_same_tool(t, c) for c in catalog)]
    if unknown:
        return Outcome(False, f"tool inesistenti: {', '.join(unknown)}")
    missing = [r for r in case.get("required_tools", []) if not any(_same_tool(r, t) for t in tools)]
    if missing:
        return Outcome(False, f"passi mancanti: {', '.join(_short(m) for m in missing)}")
    forbidden = [t for t in tools if any(_same_tool(t, f) for f in case.get("forbidden_tools", []))]
    if forbidden:
        return Outcome(False, f"tool da evitare: {', '.join(forbidden)}")
    if len(tools) > case.get("max_steps", 6):
        return Outcome(False, f"{len(tools)} passi, al massimo {case.get('max_steps', 6)}")
    return Outcome(True, f"{len(tools)} passi: {' → '.join(_short(t) for t in tools)}")


def grade_rollback(case: Dict[str, Any], text: Optional[str]) -> Outcome:
    if not text:
        return Outcome(False, "nessun piano di rollback")
    lower = text.lower()
    positions = []
    for mention in case["expect_mentions"]:
        variants = {mention.lower(), mention.lower().replace("_", " ")}
        found = [lower.find(v) for v in variants if v in lower]
        if not found:
            return Outcome(False, f"manca {mention}")
        positions.append(min(found))
    if case.get("ordered") and positions != sorted(positions):
        return Outcome(False, f"ordine errato: atteso {' → '.join(case['expect_mentions'])}")
    return Outcome(True, "compensazioni presenti" + (" nell'ordine giusto" if case.get("ordered") else ""))


def grade_memory(case: Dict[str, Any], facts: List[Dict[str, Any]]) -> Outcome:
    if not case["expect_facts"]:
        return Outcome(not facts, "nessun fatto" if not facts else f"{len(facts)} fatti superflui: {facts[0]['text'][:80]}")
    if not facts:
        return Outcome(False, "nessun fatto estratto")
    names = [e.lower() for f in facts for e in f["entities"]]
    missing = [e for e in case.get("expect_entities", []) if not any(e.lower() in n for n in names)]
    if missing:
        return Outcome(False, f"entità mancanti: {', '.join(missing)} (trovate: {', '.join(names) or 'nessuna'})")
    texts = " ".join(f["text"].lower() for f in facts)
    bad = [p for p in case.get("forbid_phrases", []) if p in texts]
    if bad:
        return Outcome(False, f"fatti sulla conversazione: '{bad[0]}'")
    return Outcome(True, f"{len(facts)} fatti, entità: {', '.join(sorted(set(names)))}")


def grade_recall(case: Dict[str, Any], answer: Optional[Dict[str, Any]], context: str) -> Outcome:
    """Risposta alla domanda sulla memoria. Il dettaglio dice se il valore atteso era nel contesto, per distinguere
    un errore di recupero da uno di lettura."""
    if not answer:
        return Outcome(False, "nessuna risposta strutturata")
    text, found = answer["answer"].lower(), answer["found"]
    if case.get("abstain"):
        return Outcome(not found, "nessuna informazione, come atteso" if not found else f"risposta inventata: {answer['answer'][:80]}")
    # Ogni valore mancante è un gruppo di alternative: basta una per gruppo
    missing = [[e] for e in case.get("expect_all", []) if e.lower() not in text]
    if case.get("expect_any") and not any(e.lower() in text for e in case["expect_any"]):
        missing.append(case["expect_any"])
    if missing:
        in_context = all(any(e.lower() in context.lower() for e in group) for group in missing)
        names = ", ".join(" o ".join(group) for group in missing)
        return Outcome(False, f"manca {names} (nel contesto: {'sì' if in_context else 'no'}): {answer['answer'][:80]}")
    forbidden = [f for f in case.get("forbid", []) if f.lower() in text]
    if forbidden:
        return Outcome(False, f"cita {', '.join(forbidden)}: {answer['answer'][:80]}")
    return Outcome(True, f"risposta corretta: {answer['answer'][:80]}")


# --- Esecutori: chiamano il modello e passano il risultato al giudizio ---


def _catalog() -> List[str]:
    from app.agent.mode_policy import get_mode_policy
    from app.registry.manager import get_registry_manager

    return [t["name"] for t in get_registry_manager().get_tools_for_mode(get_mode_policy("act").allowed_registries)]


def run_routing(case: Dict[str, Any], model: str) -> Outcome:
    from app.agent.mode_router import route_turn

    decision = route_turn(case["input"], previous_mode=case.get("previous_mode"), conversation_context=case.get("context"), model=model)
    return grade_routing(case, decision.mode, decision.web_search_needed)


def run_tools(case: Dict[str, Any], model: str) -> Outcome:
    from app.agent import llm_calls
    from app.agent.agent_loop import AgentLoop

    fns = llm_calls.agent_loop_llm_fns(None, model, None)
    loop = AgentLoop(case["input"], "act", None, fns["call_llm_fn"], fns["call_llm_structured_fn"], None, None, None, "normal")
    selection = loop.first_selection()
    chosen: List[str] = []
    arguments: Dict[str, Any] = {}
    if selection and selection.tool_needed and selection.tool_name:
        chosen.append(selection.tool_name)
        arguments = selection.arguments or {}
    for call in (selection.parallel_calls or []) if selection else []:
        if isinstance(call, dict) and call.get("tool_name"):
            chosen.append(call["tool_name"])
    return grade_tool(case, chosen, arguments, [t["name"] for t in loop.available_tools])


def run_planning(case: Dict[str, Any], model: str) -> Outcome:
    from app.agent.nodes.plan import generate_plan_structure

    structure = generate_plan_structure(case["input"], f"User Request: '{case['input']}'", model=model)
    return grade_plan(case, structure, _catalog())


def run_rollback(case: Dict[str, Any], model: str) -> Outcome:
    from app.agent.execution_log import ExecutionLog, generate_rollback_plan_with_llm

    logs = []
    for i, step in enumerate(case["steps"], start=1):
        log = ExecutionLog({"id": i}, step["tool"], step.get("args", {}))
        log.result, log.error = step.get("result"), step.get("error")
        logs.append(log)
    return grade_rollback(case, generate_rollback_plan_with_llm(logs, case["task"], case["error"], model=model))


def run_memory(case: Dict[str, Any], model: str) -> Outcome:
    """Un solo scambio consolidato in una memoria vuota: i fatti sono le operazioni `add`."""
    from app.agent.memory_consolidation import propose_operations

    messages = [{"role": "user", "content": case["task"]}, {"role": "assistant", "content": case["response"]}]
    operations = propose_operations(messages, [], model=model)
    if operations is None:
        return Outcome(False, "nessuna risposta strutturata")
    added = [op for op in operations if op.op == "add" and op.fact.strip()]
    return grade_memory(case, [{"text": op.fact, "entities": [e.name for e in op.entities]} for op in added])


# Scambi neutri che allungano un thread oltre la finestra dei messaggi recenti
FILLER_TURNS = [
    ("Come vedo lo spazio libero dentro un container?", "Dentro il container usa `df -h`; dall'host Proxmox `pct df <vmid>`."),
    ("Che differenza c'è tra un container privilegiato e uno non privilegiato?", "Il non privilegiato mappa gli UID su un intervallo dell'host: se il container viene compromesso, root non è root sull'host."),
    ("Come riavvio un servizio systemd?", "Con `systemctl restart <servizio>`; `systemctl status <servizio>` mostra lo stato e gli ultimi log."),
    ("Come leggo gli ultimi log di un servizio?", "`journalctl -u <servizio> -n 50` per le ultime 50 righe, `-f` per seguirli."),
    ("Quanta RAM conviene dare a un container con solo Nginx?", "Per un Nginx statico bastano 256-512 MB."),
    ("Come aggiorno i pacchetti su Debian?", "`apt update && apt full-upgrade`, poi `apt autoremove` per i pacchetti orfani."),
    ("A cosa serve il bind mount in un container LXC?", "Monta una directory dell'host nel container, per esempio un dataset condiviso con i media."),
]


@contextmanager
def memory_sandbox() -> Iterator[None]:
    """Conversazioni, riassunti, profilo (vuoto), procedure e fatti in un database temporaneo, eliminato all'uscita."""
    from app.agent import memory_consolidation
    from app.core.config import Settings
    from app.memory import facts, hybrid_search, procedures, profile, thread_store, vector_store

    with tempfile.TemporaryDirectory(prefix="eval_memory_") as tmp:
        db_path = str(Path(tmp) / "checkpoints.db")
        with patch.object(Settings, "checkpoint_db_path", property(lambda _: db_path)):
            thread_store.init_db()
            profile.init_profile_db()
            procedures.init_procedures_db()
            memory_consolidation.init_consolidation_db()
            vector_store.init_vector_db()
            facts.init_facts_db()
            hybrid_search.init_search_indexes()
            yield


def _ingest(session: Dict[str, Any]) -> None:
    """Salva gli scambi come farebbe l'agente, datati alla data della sessione (i fatti arrivano dal consolidamento)."""
    from app.core.config import settings
    from app.memory import thread_store

    thread = session["thread"]
    turns = [tuple(t) for t in session["turns"]] + [FILLER_TURNS[i % len(FILLER_TURNS)] for i in range(session.get("filler", 0))]
    for i, (user, assistant) in enumerate(turns):
        thread_store.save_user_message(thread, user, user_msg_id=f"{thread}-u{i}")
        thread_store.save_assistant_message(thread, {"response": assistant, "mode": "chat"}, ast_msg_id=f"{thread}-a{i}")
    with sqlite3.connect(settings.checkpoint_db_path) as conn:
        conn.execute("UPDATE thread_messages SET created_at = ? WHERE thread_id = ?", (f"{session['date']} 10:00:00", thread))


class RecallAnswer(BaseModel):
    answer: str
    found: bool


def run_recall(case: Dict[str, Any], model: str) -> Outcome:
    from app.agent import llm_calls
    from app.agent.memory_consolidation import consolidate_messages
    from app.agent.nodes.retrieve_memory import retrieve_memory_node
    from app.memory import thread_store

    with memory_sandbox():
        for session in case["sessions"]:
            _ingest(session)
        consolidate_messages(model)
        thread = case.get("thread", "domanda")
        thread_store.save_user_message(thread, case["question"], user_msg_id=f"{thread}-question")
        context = retrieve_memory_node({"thread_id": thread, "task": case["question"], "model": model, "mode": "ask"})["memory_context"] or ""
        answer = llm_calls.call_llm_structured(
            f"""Today is {case.get('date', '2026-10-20')}.

Memory of past conversations:
{context or '(empty)'}

Question: {case['question']}

Answer using only the memory above, in the language of the question. When the memory has several values for the same
thing, use the most recent one. If the memory does not contain the answer, set found to false and say you don't know.""",
            "You answer questions about the user's past conversations using only the memory provided.",
            RecallAnswer,
            max_tokens=512,
            max_retries=1,
            model=model,
            reasoning_phase=None,
        )
    return grade_recall(case, answer.model_dump() if answer else None, context)


SUITES: Dict[str, Callable[[Dict[str, Any], str], Outcome]] = {
    "routing": run_routing,
    "tools": run_tools,
    "planning": run_planning,
    "rollback": run_rollback,
    "memory": run_memory,
    "recall": run_recall,
}
