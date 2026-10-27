# 04 — Roadmap

Sostituisce [ROADMAP.md](../../ROADMAP.md) (fasi 0–9, storico). Le fasi sono sequenziali: ognuna parte quando la precedente ha la CI verde ed è verificata su CT 125.

```
A. Consolidamento ──► B. Refactor architetturale ──► C. Frontend ──► D. Nuove funzionalità
   (fix + test + CI)     (pacchetti, no legacy)        (split, perf)    (MCP dinamici, memoria, …)
```

## Fase A — Consolidamento

Obiettivo: base affidabile su cui costruire. Dettagli in [03-FIX_PLAN.md](03-FIX_PLAN.md).

| # | Attività | Issue | Stato |
| :--- | :--- | :--- | :---: |
| A1 | Hotfix: retention automazioni, `logger`, lista thread su DB vuoto | ISS-01, 02, 03 | ✅ 2026-10-26 |
| A2 | Ambiente dev ricreato (venv 3.12, `requirements-dev.txt`), test eseguibili nel container | ISS-07, 15, 16, 17 | ✅ 2026-10-26 |
| A3 | Test in `tests/`, marker `live`, timeout, isolamento DB | ISS-04, 05, 19–22 | ✅ 2026-10-26 |
| A4 | Ruff e oxlint puliti, CI backend + frontend versionata e bloccante | ISS-06, 08, 12 | ✅ 2026-10-26 |
| A5 | Merge `dev` → `main`, tag `v0.9.0`, docs allineate | ISS-13, 14 | ✅ 2026-10-26 |

**Uscita**: `pytest` verde in meno di 60 s, CI verde, nessun errore nei log di CT 125 per 24 ore.

## Fase B — Refactor architetturale

Obiettivo: codice navigabile e senza legacy, in modo da poter aggiungere feature senza far crescere i monoliti. Breaking change ammessi (AGENTS.md).

| # | Attività | Issue |
| :--- | :--- | :--- |
| B1 | ~~Backend in pacchetto `app/`: `api/` (router per dominio), `agent/`, `registry/`, `automations/`, `calendar/`, `memory/`, `core/`~~ ✅ 2026-10-27 (in più: `security/`, `llm/`, `mcp/`; `sdk/` resta fuori perché pubblico) | ISS-09 |
| B2 | ~~Dividere `graph.py` in un modulo per nodo, più `execution_log` (Saga/WAL) separato~~ ✅ 2026-10-27 (in più: `state.py`, `llm_calls.py`, `memory/transcript.py`) | ISS-09 |
| B3 | ~~Dividere `automations/db.py` per aggregato (definitions, runs, approvals, artifacts)~~ ✅ 2026-10-27 (in più: `breaker_states`, `integrations`; rimossi la migrazione `_ensure_v2_columns` e gli alias `*_automation`) | ISS-09 |
| B4 | ~~Rimuovere il client MCP legacy: solo SDK ufficiale, con retry e reset di sessione~~ ✅ 2026-10-27 (Streamable HTTP; rimossi anche il fallback OpenAPI del catalogo e `METAMCP_URL_HTTP`) | ISS-10 |
| B8 | ~~Router via provider astratto invece di `requests` diretto~~ ✅ 2026-10-27 (`json_mode` nei provider; rimossi `classify_mode` e il doppione di `is_purely_visual_request`) | ISS-23 |
| B9 | ~~Decisione e fix sul fallback non isolato della sandbox codice~~ ✅ 2026-10-26 (fallback previa approvazione) | ISS-18 |
| B5 | ~~`config.py` solo Pydantic Settings, eliminate le costanti di retrocompatibilità~~ ✅ 2026-10-27 (anche SearXNG e lingue di ricerca nelle settings) | ISS-10 |
| B6 | ~~Startup unico (lifespan FastAPI): init di tutti gli schemi DB, scheduler, registry~~ ✅ 2026-10-27 (`app/startup.py`; nessuna inizializzazione all'import) | ISS-03 |
| B7 | ~~Database in una directory dati unica (`DATA_DIR`), niente `.db` nella radice del codice~~ ✅ 2026-10-27 | ISS-09 |
| B10 | ~~Pulizia: rimuovere `backfill_from_state_history` e `repair_missing_web_prefetch` da `thread_store`, `verify_api_key` unica con confronto a tempo costante, duplicato `_parse_natural_duration`, alias `SAFE_TOOLS`~~ ✅ 2026-10-27 (in più: lista thread dallo store dei messaggi, i thread incogniti non compaiono più) | ISS-25 |
| B11 | ~~`automations/runner.py`: un gestore per tipo di step (`automations/steps/`) e helper di template in `templating.py`~~ ✅ 2026-10-27 (in più: `run_secrets.py`; corretto l'avvio di un'automazione dalla chat) | ISS-09 |
| B12 | ~~`agent/agent_loop.py`: `run_agent_loop` (536 righe) diviso in fasi di una classe `AgentLoop`; verifica live~~ ✅ 2026-10-27 (prompt in `agent_prompts.py`) | ISS-09 |
| B13 | ~~`automations/router.py` in un router per dominio (`automations/routes/`); `guardrails.py` diviso in `security/policy.py` e `security/approvals.py`~~ ✅ 2026-10-27 (in più: `routes/common.py` con runner e sincronizzazione scheduler; rimossi `check_shell_command` e `HIGH_RISK_TOOLS`) | ISS-09 |
| — | ~~Agent loop sui modelli locali: prompt riusabili dalla cache, storico dei tool limitato, nessun retry dopo un timeout, output strutturato vincolato da grammatica~~ ✅ 2026-10-27 lato backend; resta il preset LLM di CT 100 | ISS-26 |

Valutazione dei file sopra 600 righe (2026-10-27): `calendar/db.py`, `registry/calendar_tool.py`, `registry/automations_tool.py` e `llm/providers.py` restano come sono (coesi; negli strumenti metà file sono schemi JSON statici).

**Uscita**: nessuna funzione sopra ~100 righe e un modulo per responsabilità, invece del solo limite di ~600 righe per file; Dockerfile e compose aggiornati; test verdi dopo ogni spostamento.

## Fase C — Frontend

| # | Attività | Issue |
| :--- | :--- | :--- |
| C1 | Code-splitting con `React.lazy` per le viste Automations, Calendar, Knowledge e Settings; highlight.js caricato on demand | ISS-11 |
| C2 | `api.ts` diviso per dominio (`api/chat.ts`, `api/automations.ts`, …) | ISS-11 |
| C3 | `Chat.tsx`, `AutomationsView.tsx`, `CalendarView.tsx` divisi in sotto-componenti con hook dedicati | ISS-11 |
| C4 | Test frontend minimi (Vitest) per `useChat` (parsing SSE) e per i client API | — |

**Uscita**: chunk iniziale sotto i 400 kB, nessun componente sopra le ~500 righe.

## Fase D — Nuove funzionalità (backlog prioritizzato)

| # | Funzionalità | Valore | Dipende da |
| :--- | :--- | :--- | :--- |
| D1 | **Server MCP dinamici**: registrazione e hot-reload di nuovi server MCP dalla UI, oltre a ProxmoxMcp (per esempio creative-suite), con permessi per tool | Estende l'agente senza deploy | B4 |
| D2 | **Osservabilità**: metriche per run (latenza, token, errori tool), dashboard in Diagnostics, health dei provider nel tempo | Debug e tuning dei modelli | B6 |
| D3 | **Memory explorer**: viewer di fatti, entità e relazioni (sqlite-vec / Letta), con modifica e cancellazione | Controllo della memoria a lungo termine | B1 |
| D4 | **Eval harness**: i test `live` diventano una suite di valutazione ripetibile (routing, tool selection, rollback) con report per modello | Confronto tra modelli su CT 149 | A3 |
| D5 | **Auth multi-utente / RBAC**: solo se l'accesso esce dalla LAN | Sicurezza | B1 |

## Storico

| Periodo | Contenuto |
| :--- | :--- |
| ago 2026 | Fasi 0–9: hardening, provider, memoria/RAG, tool system, frontend, CI, streaming, web prefetch, vision ([ROADMAP.md](../../ROADMAP.md)) |
| set 2026 | Automazioni M0–M9 ([tracker](../automations/IMPLEMENTATION_TRACKER.md)), calendario nativo ([docs](../calendar/)) |
| ott 2026 | Selezione e visualizzazione del modello, diagnostica per messaggio, fix su router e deploy |
| 2026-10-26 | Assessment: questo documento |
