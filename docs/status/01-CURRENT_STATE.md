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
intake → retrieve_memory → mode_router → web_prefetch → { chat | ask | act | plan → execute_plan } → respond → commit_memory
```

- **Modalità**: CHAT (conversazione), ASK (ricerca/consultazione), ACT (tool MCP con self-correction), PLAN (piani multi-step con rollback Saga/WAL).
- **Codice**: [graph.py](../../backend/app/agent/graph.py) costruisce solo il grafo; ogni nodo sta in [nodes/](../../backend/app/agent/nodes/), l'esecuzione dei piani (Saga/WAL con rollback) in [execution_log.py](../../backend/app/agent/execution_log.py), le chiamate LLM in [llm_calls.py](../../backend/app/agent/llm_calls.py).
- **Routing**: [router.py](../../backend/app/agent/mode_router.py) usa regole più un LLM di fallback; [mode_policy.py](../../backend/app/agent/mode_policy.py) definisce budget di tool e reasoning per ogni modalità.

### 2.2 Registry dei tool ([registry/](../../backend/app/registry/))

`metamcp` (Proxmox via MetaMCP), `web` (SearXNG + DDGS, protezione SSRF), `code` (sandbox / Firecracker), `memory` (recall ibrido), `vision`, `email`, `automations`, `calendar`.

### 2.3 Sottosistemi

| Area | Moduli principali | Note |
| :--- | :--- | :--- |
| API REST/SSE | [api.py](../../backend/app/api/) (~40 route) | Chat, thread, stream, approvazioni, KB, audit, modelli |
| Automazioni | [automations/](../../backend/app/automations/) ([routes/](../../backend/app/automations/routes/), 41 route) | DB dedicato, scheduler cron, runner, SDK Python, circuit breaker, artefatti |
| Calendario | [calendar_db.py](../../backend/app/calendar/db.py), [calendar_router.py](../../backend/app/calendar/router.py) (~15 route), [calendar_sync.py](../../backend/app/calendar/sync.py) | Import ICS/Google |
| Sicurezza | [policy.py](../../backend/app/security/policy.py), [approvals.py](../../backend/app/security/approvals.py), [permissions.py](../../backend/app/security/permissions.py) | Blocco deterministico più approvazione utente (una volta / sessione / sempre) |
| Memoria | [vector_store.py](../../backend/app/memory/vector_store.py), [knowledge_base.py](../../backend/app/memory/knowledge_base.py), [letta_client.py](../../backend/app/memory/letta_client.py), [thread_store.py](../../backend/app/memory/thread_store.py) | sqlite-vec, BM25+RRF, persistenza thread |
| Streaming | [stream_session.py](../../backend/app/agent/stream_session.py) | Multi-subscriber, riaggancio, pausa/ripresa/stop |
| LLM | [providers.py](../../backend/app/llm/providers.py) | OpenAI-compatible (LiteLLM CT 149) e Ollama |
| Integrazioni | [integrations/manager.py](../../backend/app/integrations/manager.py) | Integrazioni modulari per le automazioni |

### 2.4 Persistenza

Cinque database SQLite: `checkpoints.db` (LangGraph più thread), `automations.db`, `calendar.db`, la tabella `audit_log` e sqlite-vec. In produzione stanno nel volume Docker `agent_data:/data`. In locale `automations.db`, `calendar.db` e `checkpoints.db` sono nella radice di `backend/`; la directory `backend/memory/` contiene ~50 file `test_*.jsonl` generati dai test (ignorati da git).

## 3. Frontend (`frontend/`)

**Stack**: React 19 · Vite 8 · TypeScript 6 · Tailwind 3 · react-markdown + highlight.js · oxlint. Client HTTP su `fetch` in `src/api/` (un modulo per gruppo di route del backend).

- **Viste**: Chat (streaming, reasoning, approvazioni inline, diagnostica per messaggio), lista thread, Automations hub (run inspector, trigger, artefatti, integrazioni), Calendario, Knowledge, Impostazioni (sicurezza, modelli, temi).
- **Struttura (C3)**: chat in `components/chat/` (10 componenti, il più grande 193 righe), automazioni e calendario divisi per scheda e vista, stato negli hook (`useChat` 436 righe, `useChatOptions`, `useAutomationsData`, `useRunActions`, `useCalendarData`, `useCalendarNavigation`, …), calcoli puri in `utils/` (`chatMessages`, `calendarDates`).
- **Componenti ancora sopra le 500 righe**: `SettingsModal.tsx` (938), `CalendarManageModal.tsx` (699), `EditAutomationModal.tsx` (693), `IntegrationsTab.tsx` (644), `ArtifactsView.tsx` (630), `TriggerEditorModal.tsx` (504).
- **Build**: passa. Code-splitting (C1): chunk iniziale `index.js` 297 kB più `react` 190 kB (490 kB, 144 kB gzip in tutto; prima 947 kB in un chunk unico da 262 kB gzip). Axios rimosso in C2. Automations, Calendar, Knowledge, Settings e la card delle proposte sono chunk lazy; highlight.js (168 kB) si carica solo se un messaggio contiene un blocco di codice.
- **Lint (oxlint)**: 0 warning con `--deny-warnings` (A4).

## 4. Deploy (CT 125)

| Voce | Stato |
| :--- | :--- |
| Codice | `/opt/homelab-agent` @ `4e9f040`, worktree pulito |
| Container | `agent-backend` Up (healthy), `agent-frontend` Up, `restart: always` |
| Health | `GET /v1/health` → `{"status":"ok"}` |
| Errori nei log (24h) | 1 traceback ricorrente: retention delle automazioni (vedi [ISS-01](02-ISSUES.md#iss-01)) |
| Compose | [docker-compose.prod.yml](../../docker-compose.prod.yml): backend con `./backend:/app:ro`, dati in volume `agent_data` |

## 5. Quality gate (eseguiti in locale)

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
