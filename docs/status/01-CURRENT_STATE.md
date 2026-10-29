# 01 — Situazione attuale

Rilevata il 2026-10-26 su `dev` @ `4e9f040`.

## 1. Repository

| Voce | Valore |
| :--- | :--- |
| Branch attivo | `dev` (100 commit avanti a `main`, mai mergiati) |
| Modifiche locali non committate | 3 file in `docs/` (correzione percorsi `projects/` e `references/`), `.github/` non tracciato |
| Dimensione | ~41k righe tra backend (Python) e frontend (TS/TSX), test inclusi |
| File di test | 34 `test_*.py` nella radice di `backend/` |

## 2. Backend (`backend/`)

**Stack**: Python 3.12 (Docker) · FastAPI · LangGraph 1.2 con `SqliteSaver` · Pydantic Settings · slowapi · sqlite-vec + fastembed · SDK MCP ufficiale.

### 2.1 Grafo LangGraph ([graph.py](../../backend/app/agent/graph.py))

```
intake → recent_turns → mode_router → retrieve_memory → web_prefetch → { chat | ask | act | plan → execute_plan } → respond
```

- **Modalità**: CHAT (conversazione), ASK (ricerca/consultazione), ACT (tool MCP con self-correction), PLAN (piani multi-step con rollback Saga/WAL).
- **Codice**: [graph.py](../../backend/app/agent/graph.py) costruisce solo il grafo; ogni nodo sta in [nodes/](../../backend/app/agent/nodes/), l'esecuzione dei piani (Saga/WAL con rollback) in [execution_log.py](../../backend/app/agent/execution_log.py), le chiamate LLM in [llm_calls.py](../../backend/app/agent/llm_calls.py).
- **Routing**: [router.py](../../backend/app/agent/mode_router.py) usa regole più un LLM di fallback; [mode_policy.py](../../backend/app/agent/mode_policy.py) definisce budget di tool, reasoning e memoria per ogni modalità.

### 2.2 Registry dei tool ([registry/](../../backend/app/registry/))

`mcp` (MetaMCP più i server registrati dalla UI, con impostazioni per tool), `web` (SearXNG + DDGS, protezione SSRF), `code` (sandbox / Firecracker), `memory` (recall ibrido), `vision`, `email`, `automations`, `calendar`.

### 2.3 Sottosistemi

| Area | Moduli principali | Note |
| :--- | :--- | :--- |
| API REST/SSE | [api.py](../../backend/app/api/) (~40 route) | Chat, thread, stream, approvazioni, KB, audit, modelli |
| Automazioni | [automations/](../../backend/app/automations/) ([routes/](../../backend/app/automations/routes/), 41 route) | DB dedicato, scheduler cron, runner, SDK Python, circuit breaker, artefatti |
| Calendario | [calendar_db.py](../../backend/app/calendar/db.py), [calendar_router.py](../../backend/app/calendar/router.py) (~15 route), [calendar_sync.py](../../backend/app/calendar/sync.py) | Import ICS/Google |
| Sicurezza | [policy.py](../../backend/app/security/policy.py), [approvals.py](../../backend/app/security/approvals.py), [permissions.py](../../backend/app/security/permissions.py) | Blocco deterministico più approvazione utente (una volta / sessione / sempre) |
| Memoria | [facts.py](../../backend/app/memory/facts.py), [vector_store.py](../../backend/app/memory/vector_store.py), [knowledge_base.py](../../backend/app/memory/knowledge_base.py), [thread_store.py](../../backend/app/memory/thread_store.py), [profile.py](../../backend/app/memory/profile.py), [hybrid_search.py](../../backend/app/memory/hybrid_search.py), [episodes.py](../../backend/app/memory/episodes.py), [procedures.py](../../backend/app/memory/procedures.py) | Profilo dell'utente, fatti con entità e relazioni in sqlite-vec, episodi di esecuzione, procedure approvate dall'utente (note sui tool e piani modello), knowledge base, thread con messaggi e riassunti, composti per modalità dopo il router; ricerca ibrida FTS5 + vettori e tool `search_conversations`; tutto in `checkpoints.db`, nessun servizio esterno |
| Streaming | [stream_session.py](../../backend/app/agent/stream_session.py) | Multi-subscriber, riaggancio, pausa/ripresa/stop |
| LLM | [providers.py](../../backend/app/llm/providers.py) | OpenAI-compatible (LiteLLM CT 149) e Ollama |
| Osservabilità | [observability/](../../backend/app/observability/) | Turni e chiamate LLM in `metrics.db`, salute dei servizi campionata ogni minuto, API `/v1/metrics/*` |
| Integrazioni | [integrations/manager.py](../../backend/app/integrations/manager.py) | Integrazioni modulari per le automazioni |

### 2.4 Persistenza

Database SQLite in `DATA_DIR`: `checkpoints.db` (LangGraph, thread, `audit_log`, sqlite-vec), `automations.db`, `calendar.db`, `mcp.db` (server MCP e impostazioni per tool), `metrics.db` (turni, chiamate LLM, salute dei servizi). In produzione stanno nel volume Docker `agent_data:/data`, in locale in `data/` nella radice del repo.

## 3. Frontend (`frontend/`)

**Stack**: React 19 · Vite 8 · TypeScript 6 · Tailwind 3 · react-markdown + highlight.js · oxlint. Client HTTP su `fetch` in `src/api/` (un modulo per gruppo di route del backend).

- **Viste**: Chat (streaming, reasoning, approvazioni inline, diagnostica per messaggio), lista thread, Automations hub (run inspector, trigger, artefatti, integrazioni), Calendario, Memoria (profilo; fatti, entità e relazioni, con modifica e unione; episodi; procedure da approvare; conferme nell'app), Metriche (turni, velocità dei modelli, tool, salute dei servizi nel tempo), Knowledge, Impostazioni (sicurezza, modelli, temi, server MCP).
- **Struttura (C3)**: chat in `components/chat/` (10 componenti, il più grande 193 righe), automazioni e calendario divisi per scheda e vista, stato negli hook (`useChat` 436 righe, `useChatOptions`, `useAutomationsData`, `useRunActions`, `useCalendarData`, `useCalendarNavigation`, …), calcoli puri in `utils/` (`chatMessages`, `calendarDates`).
- **Dimensioni**: nessun file sopra le 500 righe (il più grande è `ParametersModal.tsx`, 492). Impostazioni, gestione calendari, integrazioni, artefatti, modifica automazione e trigger sono cartelle per area (`settings/`, `calendar/manage/`, `automations/{integrations,artifacts,edit,triggers}/`), con la logica pura in `utils/` (`automationForm`, `cronSchedule`, `artifactGroups`).
- **Build**: passa. Code-splitting (C1): chunk iniziale `index.js` 297 kB più `react` 190 kB (490 kB, 144 kB gzip in tutto; prima 947 kB in un chunk unico da 262 kB gzip). Axios rimosso in C2. Automations, Calendar, Knowledge, Settings e la card delle proposte sono chunk lazy; highlight.js (168 kB) si carica solo se un messaggio contiene un blocco di codice.
- **Lint (oxlint)**: 0 warning con `--deny-warnings` (A4).

### Valutazione dei modelli (D4)

Base del 2026-10-28 su LFM2.5-24B-A2B-HugeCtx (`make eval`, CT 125). Accuratezza sulle esecuzioni e durata mediana:

| routing | tools | planning | rollback | memory |
| :--- | :--- | :--- | :--- | :--- |
| 71% (10/14) · 3 s | 81% (13/16) · 33 s | 12% (1/8) · 44 s | 33% (2/6) · 3 s | 67% (4/6) · 3 s |

Punti deboli emersi: piani strutturati incompleti (manca quasi sempre un passo), argomenti non normalizzati (`vmid: "CT 120"`),
fatti estratti da chiacchiere e nozioni generali, ragionamento che finisce nella risposta anche con il thinking spento.
La selezione dei tool è lenta perché il preset HugeCtx elabora i ~7,9k token del catalogo in parte sulla CPU (~100 tok/s
senza cache). La valutazione ha anche trovato due bug, corretti: piano di rollback sempre vuoto e piano strutturato
non valido (il thinking esauriva i token).

Suite `recall` (E2), base del 2026-10-29 su Qwen3.6-35B-HugeCtx: **75% (9/12)**, 13 s per caso. Superati preferenze,
dettagli e decisioni tra thread, valori aggiornati (IP, container, strumento), astensione e il dettaglio iniziale di un
thread lungo, recuperato dal riassunto. I tre fallimenti sono tutti di recupero, non di lettura: il valore atteso non
arriva nel contesto. Due domande temporali ("cosa ho installato ad agosto", "l'ultimo servizio installato") non
somigliano ai fatti, che non portano date; l'aggregazione su tre thread perde il terzo fatto (recall limitato a 3
fatti sopra 0,35). Sono gli obiettivi di E3 ed E4.

Dopo E3 (memoria per modalità, fino a 5 fatti datati in ask): ancora **75% (9/12)**, 11,4 s per caso, ma con un
fallimento diverso. L'aggregazione ora passa. La preferenza tra thread fallisce a volte, perché il fatto ha
somiglianza 0,351 con la domanda, sul filo della soglia: ripetuto a parte passa 2 volte su 2. Le due domande
temporali restano fuori dal contesto: servono la ricerca ibrida (E4) e la validità temporale dei fatti (E6).

Dopo E4 (ricerca ibrida parole + significato, fatti datati): **100% (12/12)**, 12,5 s per caso. Le domande temporali
passano perché la parola in comune ("installato") porta nel contesto tutti i fatti candidati, e la data permette al
modello di scegliere; le astensioni restano corrette. Suite `tools`: **100% (17/17)**, compreso il nuovo caso in cui il
modello deve scegliere `search_conversations`.
Prima base di Qwen3.6-35B su `planning` (**100%, 4/4**, 27 s per caso) e `rollback` (**67%, 2/3**): nel caso `ip-only`
il piano di compensazione LLM chiama `release_ip` senza l'indirizzo da rilasciare. Il rollback non usa la memoria; da
indagare a parte.

Dopo E5: `tools` **100% (17/17)**, `planning` **75% (3/4)**. Nel caso `new-service` il modello ora sceglie, in modo
stabile (3 volte su 3), il tool composito `create_service` (con il dry run) invece dei quattro passi espliciti attesi
dal caso. Non dipende da E5: lo fa anche togliendo `propose_procedure` dal catalogo. Va deciso se il caso deve accettare
anche `create_service`.

## 4. Deploy (CT 125)

| Voce | Stato |
| :--- | :--- |
| Codice | `/opt/homelab-agent` @ `4e9f040`, worktree pulito |
| Container | `agent-backend` Up (healthy), `agent-frontend` Up, `restart: always` |
| Health | `GET /v1/health` → `{"status":"ok"}` |
| Errori nei log (24h) | 1 traceback ricorrente: retention delle automazioni (vedi [ISS-01](02-ISSUES.md#iss-01)) |
| Compose | [docker-compose.prod.yml](../../docker-compose.prod.yml): backend con `./backend:/app:ro`, dati in volume `agent_data` |

## 5. Quality gate (eseguiti in locale)

> **Aggiornamento 2026-10-27 (C4)**: frontend con Vitest (`npm test`, anche in `make test` e in CI): 81 test su parser SSE, client HTTP, stream della chat, `useChat` (invio, errori, versioni, modifica del prompt, riaggancio, stop), modalità di sicurezza condivisa e funzioni pure (calendario, messaggi, form delle automazioni, cron, gruppi di artefatti). Backend: 300 test pytest.

> **Aggiornamento 2026-10-26 (dopo A1–A4)**: `pytest` → 244 passati, 0 falliti, 0 warning, ~4 s (test in `backend/tests/`, 4 test `live` esclusi di default). `ruff check` → 0 errori, `oxlint --deny-warnings` → 0 warning, tutti bloccanti in [CI](../../.github/workflows/ci.yml). La tabella sotto è lo stato dell'assessment iniziale.

| Gate | Risultato |
| :--- | :--- |
| `npm run build` | ✅ passa |
| `oxlint` | ⚠️ 8 warning |
| `ruff check` | ❌ 208 errori (120 auto-fixabili), di cui 2 `F821` reali |
| `pytest` (suite completa) | ❌ non termina (blocco > 10 min) |
| `pytest` per singolo file | 22 file OK · 4 con fallimenti · 7 bloccati · 1 vuoto |

Dettaglio per file:

| Esito | File |
| :--- | :--- |
| ✅ Passano | anti_loop, api_integration, automations_coding_repair, automations_db, automations_governance, automations_runner, automations_scheduler (60 s), automations_sdk, automations_triggers_v2, automations_v2, calendar, calendar_db, calendar_tool, integrations, memory_rag, model_features, stream_controls, streaming_isolation, stream_session, thread_persistence, visual_web_prefetch, web_prefetch |
| ❌ Falliscono | guardrails (1), modes_and_registries (1), stream_api (2), tool_safety (1) |
| ⏳ Bloccati (> 90 s) | conversation_length, dynamic_tool_selection, phase4, rollback, memory_api, router_and_prefetch, automations_api (1 test) |
| ∅ Nessun test | agent_verification |

## 6. Documentazione esistente

- [README.md](../../README.md) e [backend/README.md](../../backend/README.md): descrizione delle funzionalità, aggiornati a settembre.
- [ROADMAP.md](../../ROADMAP.md): fasi 0–9, ferma ad agosto (non copre automazioni, calendario e selezione del modello).
- [docs/automations/](../automations/): architettura, specifica e tracker M0–M9 (segnato 100% completato).
- [docs/calendar/](../calendar/): architettura e walkthrough.
