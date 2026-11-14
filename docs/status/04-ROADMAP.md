# 04 — Roadmap

Sostituisce [ROADMAP.md](../../ROADMAP.md) (fasi 0–9, storico). Le fasi sono sequenziali: ognuna parte quando la precedente ha la CI verde ed è verificata su CT 125.

```
A. Consolidamento ──► B. Refactor ──► C. Frontend ──► D. Funzionalità ──► E. Memoria ──► F. Agente affidabile ──► G. Rilascio e misure
       ✅                 🟡             ✅             ✅ (D5 solo se serve)   ✅            ✅                    🟡 (G1 ✅)
```

Stato al 2026-11-02: fuori dalla roadmap sono stati fatti anche la correzione di [ISS-28](02-ISSUES.md#iss-28), la selezione del modello caricato nelle chat, la scelta del modello nelle automazioni (default, caricato al momento, preciso) e la programmazione del consolidamento dalla UI (orario e modello). Le attività su host e CT 100 stanno nel backlog infrastrutturale delle docs dell'homelab (`docs/infrastructure-backlog.md`).

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
| C1 | ~~Code-splitting con `React.lazy` per le viste Automations, Calendar, Knowledge e Settings; highlight.js caricato on demand~~ ✅ 2026-10-27 (chunk iniziale 947 → 291 kB; in più: card delle proposte lazy, chunk vendor `react`, header di cache in nginx) | ISS-11 |
| C2 | ~~`api.ts` diviso per dominio (`api/chat.ts`, `api/automations.ts`, …)~~ ✅ 2026-10-27 (in più: client `fetch` con `ApiError` al posto di axios, parser SSE unico in `api/sse.ts`, rimosse 8 funzioni inutilizzate) | ISS-11 |
| C3 | ~~`Chat.tsx`, `AutomationsView.tsx`, `CalendarView.tsx` divisi in sotto-componenti con hook dedicati~~ ✅ 2026-10-27 (in più: `useChat` 830 → 436 righe; restano 6 componenti tra 504 e 938 righe fuori dall'elenco) | ISS-11 |
| C4 | ~~Test frontend minimi (Vitest) per `useChat` (parsing SSE) e per i client API~~ ✅ 2026-10-27 (58 test, ~1 s; in CI e in `make test`) | — |
| C5 | ~~Divisione dei 6 componenti rimasti sopra le 500 righe~~ ✅ 2026-10-28 (8 bug corretti, vedi [ISS-11](02-ISSUES.md#iss-11); test a 81) | ISS-11 |

**Uscita**: chunk iniziale sotto i 400 kB, nessun componente sopra le ~500 righe. ✅ Raggiunta il 2026-10-28 (chunk iniziale 293 kB, file più grande 492 righe).

## Fase D — Nuove funzionalità (backlog prioritizzato)

| # | Funzionalità | Valore | Dipende da |
| :--- | :--- | :--- | :--- |
| D1 | ~~**Server MCP dinamici**: registrazione e hot-reload di nuovi server MCP dalla UI, oltre a ProxmoxMcp (per esempio creative-suite), con permessi per tool~~ ✅ 2026-10-28 (registro nell'agente con MetaMCP come server predefinito; tool attivabili e rischio `auto`/`view`/`confirm`/`blocked`; registry rinominato `mcp`) | Estende l'agente senza deploy | B4 |
| D2 | ~~**Osservabilità**: metriche per run (latenza, token, errori tool), dashboard in Diagnostics, health dei provider nel tempo~~ ✅ 2026-10-28 (turni di chat e run in `metrics.db` con token, cache e velocità di llama.cpp; salute di llama.cpp, Letta, SearXNG e server MCP ogni minuto; vista Metriche dedicata invece di Diagnostics) | Debug e tuning dei modelli | B6 |
| D3 | ~~**Memory explorer**: viewer di fatti, entità e relazioni (sqlite-vec / Letta), con modifica e cancellazione~~ ✅ 2026-10-28 (entità estratte con i fatti nella stessa chiamata; relazioni per co-occorrenza; sqlite-vec unica fonte dei fatti, Letta solo per le conversazioni; vista Memoria con ricerca, modifica, rinomina e unione di entità) | Controllo della memoria a lungo termine | B1 |
| D4 | ~~**Eval harness**: i test `live` diventano una suite di valutazione ripetibile (routing, tool selection, rollback) con report per modello~~ ✅ 2026-10-28 (`app/evals`: suite routing, tools, planning, rollback, memory senza effetti collaterali; report JSON per modello e confronto Markdown; `make eval`; test live dei modelli rimossi) | Confronto tra modelli su CT 149 | A3 |
| D5 | **Auth multi-utente / RBAC**: solo se l'accesso esce dalla LAN | Sicurezza | B1 |

## Fase E — Memoria

Dalla [ricerca sulla memoria degli agenti](../memory/MEMORY_RESEARCH.md): una politica di memoria per modalità, poi episodi, procedure e consolidamento. Ogni passo si misura con le suite di valutazione.

| # | Passo | Misura | Dipende da |
| :--- | :--- | :--- | :--- |
| E1 | ~~**Memoria tutta interna**: rimozione di Letta, cronologia solo da `thread_store`, riassunto incrementale nel database~~ ✅ 2026-10-29 | test | D3 |
| E2 | ~~**Suite `recall`**: aggiornamenti, domande temporali, astensione, richiamo tra thread e su thread lunghi, su un database temporaneo~~ ✅ 2026-10-29 (12 casi; Qwen3.6-35B 75%, i fallimenti sono di recupero: domande temporali e aggregazione) | baseline | D4 |
| E3 | ~~**Memoria per modalità**: composizione dopo il routing, budget per modalità in `ModePolicy`, profilo utente precaricato e modificabile, memoria stabile all'inizio del prompt~~ ✅ 2026-10-29 (`recall` 75%: l'aggregazione ora passa, la preferenza tra thread è al limite della soglia di somiglianza; memoria di chat 1–2 ms contro 16 ms di ask) | `recall`, latenza di chat | E1, E2 |
| E4 | ~~**Episodi di esecuzione** per act e plan, ricavati dalle tracce; ricerca ibrida FTS5 + vettori; tool `search_conversations` per ask, act e plan~~ ✅ 2026-10-29 (`recall` 100%, `tools` 100% con il caso `search_conversations`) | `tools`, `planning`, `rollback`, `recall` | E3 |
| E5 | ~~**Memoria procedurale**: note sui tool e piani modello, proposti dall'agente e approvati nella UI~~ ✅ 2026-10-29 (proposte dal tool `propose_procedure` e dalle esecuzioni istruttive; scheda Procedure; episodi visibili e cancellabili nella scheda Episodi) | `planning`, `tools` | E4 |
| E6 | ~~**Consolidamento notturno**: estrazione dei fatti in blocco al posto di quella a ogni turno, deduplicazione, validità temporale dei fatti~~ ✅ 2026-10-29 (`recall` 100% su 13 casi, `memory` 100%; turno senza chiamata di estrazione) | `memory`, `recall` | E2 |
| E7 | ~~**Budget di ragionamento per modello**: i valori per modalità dipendono dal modello (alcuni non ragionano, altri ne hanno bisogno per i tool). Ricerca: [REASONING_RESEARCH.md](../reasoning/REASONING_RESEARCH.md)~~ ✅ 2026-10-29 (profili per modello e livelli per fase; Qwen3.6: `tools` 100%, `planning` 100%; matrice sugli altri modelli da fare) | tutte le suite | D4 |
| E8 | ~~**Pensiero tra i passi dell'agent loop**: piano testuale passato al piano strutturato, suite `multistep`, loop a messaggi con il pensiero dei passi precedenti dietro un interruttore per profilo. Ricerca: [INTERLEAVED_THINKING.md](../reasoning/INTERLEAVED_THINKING.md)~~ ✅ 2026-10-30 (Qwen3.6 `multistep` 70% contro 63% senza, −38% di token generati, più chiamate che eseguono comandi; `tools` e `planning` 100%) | `multistep`, `tools`, `planning` | E7 |

## Fase F — Agente affidabile

Obiettivo: un compito con tool e approvazioni arriva in fondo, in chat, nei piani e nelle automazioni.

Verificata il 2026-11-02 con prove reali su CT 125 (Qwen3.8-27B-Atomic-Vision-64K): chat con approvazione e con rifiuto, piano di tre passi, automazione con step agentico.

| # | Passo | Issue | Stato |
| :--- | :--- | :--- | :--- |
| F1 | **Stato del loop salvato**: alla richiesta di approvazione il loop salva il suo stato e riprende da lì, approvata o rifiutata; in chat la ripresa è in streaming | [ISS-30](02-ISSUES.md#iss-30) | ✅ 2026-11-02 |
| F2 | **Piani sospesi**: un'approvazione sospende il piano senza rollback, che riparte dal passo in attesa | [ISS-31](02-ISSUES.md#iss-31) | ✅ 2026-11-02 |
| F3 | **Step agentici con i tool**: agent loop vero con allowlist, registry e budget dell'automazione; approvazioni dentro lo step | [ISS-29](02-ISSUES.md#iss-29) | ✅ 2026-11-02 |
| F4 | **Run che riprendono**: l'approvazione esegue il tool in attesa e la run continua; richieste legate alla run, con la sua scadenza | [ISS-32](02-ISSUES.md#iss-32) | ✅ 2026-11-02 |

## Fase G — Rilascio e misure

| # | Passo | Note |
| :--- | :--- | :--- |
| G1 | ~~**Rilascio `dev` → `main`** con un nuovo tag, verificando la CI~~ ✅ 2026-11-11 (`v0.10.0`, 98 commit dopo `v0.9.0`, fast-forward; CI verde; in più: `make test` non dipende più dalla cache in `/tmp`) | Dopo F |
| G2 | **Matrice dei modelli**: tutte le suite su Qwen3.8 e Gemma 4, `multistep` a 20 casi su Qwen3.6, le suite vecchie di LFM2.5-Fast | Con Purpur spento (circa 4 ore a modello). Verifica anche ISS-28 sui report |
| G3 | **Criterio di uscita della fase B**: funzioni sopra le 100 righe ([ISS-09](02-ISSUES.md#iss-09)), a partire da `normalize_proposal` | Le altre quando si toccano quei file |
| G4 | **`confirm()` nativi** rimasti: migrazione a `ConfirmDialog` | Da contare: la vista Memoria è già migrata |

**Rimandati**: revisione di ProxmoxMcp ([ISS-27](02-ISSUES.md#iss-27), tool composti) e tool calling nativo (opzione D di [INTERLEAVED_THINKING.md](../reasoning/INTERLEAVED_THINKING.md)), da decidere insieme dopo G2.

**In costruzione**: sensibilità dei dati, cioè etichette sulle sorgenti e un controllo unico su ciò che esce dal backend ([SENSITIVITY_DESIGN.md](../sensitivity/SENSITIVITY_DESIGN.md)). Decisioni prese il 2026-11-13; fatte le fasi S0 (host ammessi), S1 (etichette e controllo delle uscite) il 2026-11-13 e S2 (interfaccia: livello della conversazione, indicatore, scheda di uscita, etichette in memoria, knowledge base e server MCP) il 2026-11-14. Prossima: S3, valutazioni.

## Storico

| Periodo | Contenuto |
| :--- | :--- |
| ago 2026 | Fasi 0–9: hardening, provider, memoria/RAG, tool system, frontend, CI, streaming, web prefetch, vision ([ROADMAP.md](../../ROADMAP.md)) |
| set 2026 | Automazioni M0–M9 ([tracker](../automations/IMPLEMENTATION_TRACKER.md)), calendario nativo ([docs](../calendar/)) |
| ott 2026 | Selezione e visualizzazione del modello, diagnostica per messaggio, fix su router e deploy |
| 2026-10-26 | Assessment: questo documento |
