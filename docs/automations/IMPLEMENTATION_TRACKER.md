# Implementation Tracker — Automations & Loops
**Progetto:** `homelab-agent`  
**Ultimo Aggiornamento:** 21 Settembre 2026  
**Stato Complessivo:** 🟢 COMPLETATO — Milestone M9 (Automations v2: First-Class Artifacts, Lifecycle Retention & Modular Integrations)

---

## 1. Stato Avanzamento Generale

```
[████████████████████] 100% Completato (10 / 10 Milestone)
```

| Milestone | Descrizione | Stato | Inizio Previsto | Completamento |
| :--- | :--- | :---: | :---: | :---: |
| **M0** | Database Dedicato & Approvazioni Persistenti | 🟢 Completata | 2026-09-18 | 2026-09-18 |
| **M1** | Domain Models, Step Runner & API REST | 🟢 Completata | 2026-09-18 | 2026-09-18 |
| **M2** | Cron Scheduler & Template Daily Email Briefing | 🟢 Completata | 2026-09-18 | 2026-09-18 |
| **M3** | Frontend UI: Automations Hub & Run Inspector | 🟢 Completata | 2026-09-18 | 2026-09-18 |
| **M4** | Governance Avanzata, Circuit Breaker & Audit Log | 🟢 Completata | 2026-09-18 | 2026-09-18 |
| **M5** | Custom Python SDK & Sandboxed Code Runner | 🟢 Completata | 2026-09-18 | 2026-09-18 |
| **M6** | Creazione Assistita da Chat con l'Agente | 🟢 Completata | 2026-09-18 | 2026-09-18 |
| **M7** | Subagent Coding Loop (GitHub Issue Auto-Repair) | 🟢 Completata | 2026-09-18 | 2026-09-18 |
| **M8** | Valutazione Migrazione Durable Orchestrator | 🟢 Completata | 2026-09-18 | 2026-09-18 |
| **M9** | Automations v2: Artefatti First-Class, Retention, Card Dinamiche & Integrazioni Modulari | 🟢 Completata | 2026-09-21 | 2026-09-21 |

---

## 2. Checklist Operativa Dettagliata per Milestone

### Milestone M0: Database Dedicato & Approvazioni Persistenti
- [x] **Task 0.1**: Configurazione `AUTOMATIONS_DB_PATH` in `backend/config.py`.
- [x] **Task 0.2**: Creazione del package `backend/automations/` e modulo `backend/automations/db.py`.
- [x] **Task 0.3**: Inizializzazione schema SQLite con `PRAGMA journal_mode=WAL;` e creazione tabelle:
  - `automation_definitions`
  - `automation_runs`
  - `step_runs`
  - `automation_approvals`
  - `artifacts`
- [x] **Task 0.4**: Refactoring di `backend/guardrails.py` per sincronizzare le richieste di approvazione pendenti su tabella DB persistente.
- [x] **Task 0.5**: Creazione test unitario `backend/test_automations_db.py` per concorrenza in scrittura, modalità WAL e persistenza approvazioni al restart.
- **Comando di Verifica**: `.venv/bin/python -m unittest test_automations_db.py test_tool_safety.py`
- **Criterio di Accettazione**: Tutte le tabelle create, concorrenza testata senza lock error, approvazioni sopravvivono al riavvio del processo. ✅ *VERIFICATO (23/23 test passati)*

---

### Milestone M1: Domain Models, Step Runner & API REST
- [x] **Task 1.1**: Implementazione modelli Pydantic in `backend/automations/models.py` (`AutomationDefinition`, `Trigger`, `WorkflowSpec`, `ExecutionPolicy`, `Budget`, `StepRun`, `AutomationRun`, `Artifact`).
- [x] **Task 1.2**: Implementazione dello Step Runner in `backend/automations/runner.py`:
  - Esecuzione step deterministici tramite `ToolRegistryManager`.
  - Esecuzione step agentici tramite `agent_loop.run_agent_loop`.
  - Gating su approvazione con transizione a `WAITING_APPROVAL`.
  - Resumption automatica con ricaricamento checkpoint da DB.
  - Verifica hard limit e budget (timeout e token).
- [x] **Task 1.3**: Implementazione router FastAPI in `backend/automations/router.py`:
  - `GET /v1/automations`, `POST /v1/automations`, `GET /v1/automations/{id}`, `DELETE /v1/automations/{id}`.
  - `POST /v1/automations/{id}/run` (con supporto `dry_run=true` e `sync=true`).
  - `GET /v1/automations/runs`, `GET /v1/automations/runs/{run_id}`.
  - `POST /v1/automations/runs/{run_id}/approvals/{approval_id}/resolve`.
- [x] **Task 1.4**: Registrazione di `automations_router` in `backend/api.py`.
- [x] **Task 1.5**: Creazione test `backend/test_automations_runner.py` e `backend/test_automations_api.py`.
- **Comando di Verifica**: `.venv/bin/python -m unittest test_automations_runner.py test_automations_api.py`
- **Criterio di Accettazione**: Ciclo completo di creazione definizione ed esecuzione di una run manuale via API REST. ✅ *VERIFICATO*

---

### Milestone M2: Cron Scheduler & Template Daily Email Briefing
- [x] **Task 2.1**: Aggiunta dipendenza `apscheduler>=3.10.4` in `backend/requirements.txt`.
- [x] **Task 2.2**: Implementazione scheduler in `backend/automations/scheduler.py` con sincronizzazione automatica dei trigger cron dal DB.
- [x] **Task 2.3**: Avvio/Arresto dello scheduler nel ciclo di vita FastAPI (`lifespan` in `backend/api.py`).
- [x] **Task 2.4**: Creazione tool email (`email_fetch_unread`, `email_create_draft`, `save_briefing_artifact`) in `backend/registry/email_tool.py`.
- [x] **Task 2.5**: Creazione file template canonico `backend/automations/templates/daily_email_briefing.json`.
- [x] **Task 2.6**: Creazione endpoint `GET /v1/automations/templates` e `GET /v1/automations/scheduler/jobs`.
- [x] **Task 2.7**: Creazione test `backend/test_automations_scheduler.py`.
- **Comando di Verifica**: `.venv/bin/python -m unittest test_automations_scheduler.py`
- **Criterio di Accettazione**: Esecuzione temporizzata automatica del Daily Email Briefing e generazione dell'artefatto di report. ✅ *VERIFICATO (3/3 test passati)*

---

### Milestone M3: Frontend UI — Automations Hub & Run Inspector
- [x] **Task 3.1**: Aggiunta del navigation switch in `frontend/src/App.tsx` e `frontend/src/ThreadList.tsx` (`currentView: 'chat' | 'automations'`).
- [x] **Task 3.2**: Implementazione funzioni client API in `frontend/src/api.ts` (`fetchAutomations`, `triggerAutomationRun`, `fetchAutomationRuns`, `resolveAutomationApproval`, `fetchAutomationTemplates`, `fetchScheduledJobs`, ecc.).
- [x] **Task 3.3**: Creazione componente `frontend/src/components/automations/AutomationsView.tsx` con schede:
  - Automations (Tabella/card con toggle e pulsanti Run/Dry-Run).
  - Run History (Elenco esecuzioni con filtri e badge stato).
  - Approvals Inbox (Approvazioni pendenti con pulsanti rapidi Approva/Nega).
  - Templates (Galleria template pronti all'uso con installazione a 1 click).
- [x] **Task 3.4**: Creazione componente `frontend/src/components/automations/RunInspectorModal.tsx` con timeline degli step, log dei tool e visualizzazione artefatti renderizzati in Markdown.
- [x] **Task 3.5**: Verifica compilazione e bundling frontend con `npm run build`.
- **Comando di Verifica**: `cd frontend && npm run build`
- **Criterio di Accettazione**: Navigazione fluida nell'interfaccia, visualizzazione e interazione completa con automazioni, run e approvazioni. ✅ *VERIFICATO (Vite build OK)*

---

### Milestone M4: Persistent Approvals, Audit & Budgets
- [x] **Task 4.1**: Estensione schema tabella `audit_log` con colonne `automation_id`, `run_id`, `step_run_id` e migrazione dinamica.
- [x] **Task 4.2**: Aggiornamento `audit_log.log_tool_call` e `registry/manager.py` per catturare e propagare i correlation IDs del contesto automazione.
- [x] **Task 4.3**: Implementazione circuit breaker (`CircuitBreakerManager`) con hard limits per ora/giorno, soglia fallimenti consecutivi, reset e monitoraggio stato `CLOSED`/`OPEN`/`HALF_OPEN`.
- [x] **Task 4.4**: Creazione endpoint REST `GET /v1/automations/{id}/circuit-breaker` e `POST /v1/automations/{id}/circuit-breaker/reset`.
- [x] **Task 4.5**: Test suite di sicurezza `backend/test_automations_governance.py` per circuit breaker, rate limit e blocco step privi di autorizzazione.
- **Comando di Verifica**: `.venv/bin/python -m unittest test_automations_governance.py test_tool_safety.py`
- **Criterio di Accettazione**: Blocco automatico su superamento budget/rate-limit o 3 fallimenti consecutivi, tracciamento correlation IDs su audit_log. ✅ *VERIFICATO (36/36 test passati complessivi)*

---

### Milestone M5: Custom Python SDK & Sandboxed Code Runner
- [x] **Task 5.1**: Creazione package `backend/sdk/` (`__init__.py`, `context.py`, `decorators.py`) con decoratori `@workflow`, `@step` e classe `AutomationContext` con scoped secrets.
- [x] **Task 5.2**: Implementazione `backend/automations/code_runner.py` con validazione `manifest.yaml` ed analisi statica AST di sicurezza (`ast_security_check`).
- [x] **Task 5.3**: Isolamento sandboxed tramite worker subprocess protetto, ambiente pulito `clean_env`, timeout enforcing rigido e zero shell/root fallback.
- [x] **Task 5.4**: Integrazione nello Step Runner (`StepType.CUSTOM_CODE`) con salvataggio automatico di output e artefatti su SQLite (`list_artifacts`).
- [x] **Task 5.5**: Test suite `backend/test_automations_sdk.py` per SDK, decoratori, context secrets, sandboxed runner e timeout.
- **Comando di Verifica**: `.venv/bin/python -m unittest test_automations_sdk.py test_tool_safety.py`
- **Criterio di Accettazione**: Esecuzione isolata e sicura di codice custom senza permessi host, intercettazione tentativi non autorizzati e blocco timeout. ✅ *VERIFICATO (42/42 test passati complessivi)*

---

### Milestone M6: Agent-Assisted Creation Flow
- [x] **Task 6.1**: Aggiunta intent `create_automation` e trigger keywords in `backend/router.py`.
- [x] **Task 6.2**: Generazione structured proposal JSON in `backend/graph.py` all'interno di `plan_graph_node` con blocco ````automation_proposal````.
- [x] **Task 6.3**: Componente UI `AutomationProposalCard.tsx` integrato in `MarkdownRenderer.tsx` con preview interattiva di permessi, trigger, step, simulazione Dry-Run e pulsante di attivazione sicura a 1 click.
- **Comando di Verifica**: `cd frontend && npm run build && cd ../backend && .venv/bin/python -m unittest test_router_and_prefetch.py`
- **Criterio di Accettazione**: L'utente può richiedere in chat un'automazione e ricevere una card interattiva con cui effettuare un dry-run o attivarla con un click. ✅ *VERIFICATO*

---

### Milestone M7: Subagent & Coding Loop (GitHub Issue Repair)
- [x] **Task 7.1**: Implementazione loop di riparazione deterministico a N tentativi in `backend/automations/loops/coding_repair.py`.
- [x] **Task 7.2**: Workspace isolato effimero con test runner integrato e prevenzione caching bytecode (`PYTHONDONTWRITEBYTECODE=1`).
- [x] **Task 7.3**: Calcolo unified diff patch, template di workflow `backend/automations/templates/github_issue_repair.json` e suite di test dedicata `backend/test_automations_coding_repair.py`.
- **Comando di Verifica**: `.venv/bin/python -m unittest test_automations_coding_repair.py`
- **Criterio di Accettazione**: Esecuzione loop con test baseline, diagnosi, correzione e verifica finale superata. ✅ *VERIFICATO (3/3 test passati)*

---

### Milestone M8: Durable Orchestration Migration Evaluation
- [x] **Task 8.1**: Benchmarking delle performance, consumo di memoria e latenze su CT 125 (`docker stats`, overhead di memoria, latenza di checkpoint sub-millisecondo).
- [x] **Task 8.2**: Redazione del report comparativo `docs/automations/MIGRATION_EVALUATION.md` e decisione motivata di consolidare l'architettura in-process SQLite WAL + APScheduler.
- **Comando di Verifica**: Ispezione `docs/automations/MIGRATION_EVALUATION.md`
- **Criterio di Accettazione**: Report completo con metriche reali, trade-off, criteri di trigger per riesame futuro. ✅ *VERIFICATO*

---

### Milestone M9: Automations v2 — Artefatti First-Class, Retention, Card Dinamiche & Integrazioni Modulari
- [x] **Task 9.1 (Sezione Artefatti Dedicata)**:
  - Estensione DB `artifacts` (`is_preserved`, `is_favorite`, `title`, `metadata`) e API REST (`GET /v1/automations/artifacts`, `GET /v1/automations/{id}/latest-artifact`, `PATCH .../favorite`, `PATCH .../preserve`, `DELETE .../{artifact_id}`).
  - Frontend: Nuova scheda primaria "Artefatti & Report" con split-pane master-detail, raggruppamento temporale ("Oggi", "Ieri", "Ultimi 7gg", "Questo Mese", "Precedenti"), ricerca, filtri, download, copia Markdown, toggle Markdown Renderizzato/Raw e pillola 1-click dalla card automazione.
- [x] **Task 9.2 (Gestione Storico Run & Retention)**:
  - Estensione DB `automation_runs` (`is_preserved`, `is_favorite`, `artifacts_count`).
  - API REST: `DELETE /v1/automations/runs/{run_id}`, `DELETE /v1/automations/runs` (bulk con `failed_only=true`, `older_than_days`), toggle preferito e conservazione con protezione delle run preservate.
  - Retention Service: Job notturno APScheduler (`auto_retention_cleanup` alle 03:30 Europe/Rome) per pulizia automatica delle run scadute in base al TTL (`retention_days`, default 14gg), preservando quelle bloccate con lucchetto.
  - Frontend: Toolbar con "Elimina tutte le fallite", indicatori di stato, pulsanti rapidi stella e lucchetto su ogni riga dello storico.
- [x] **Task 9.3 (Card Automazioni Dinamiche & Controlli Real-Time)**:
  - Feedback visivo animato durante l'esecuzione (bordo pulsante e glow, pulse ring azzurro).
  - Macchina a stati controlli: *Esegui* / *Dry-Run* -> *Pausa* -> *Riprendi*, con pulsante *Stop* di arresto immediato.
  - Runner: Cooperative check tra i singoli step per intercettare gli stati `PAUSED` e `CANCELLED`.
  - Drawer espandibile della card (`ChevronDown`/`ChevronUp`): Pipeline visuale degli step (ordine, tool, tipo), statistiche rapide (ultima esecuzione, timestamp, totale run registrate, TTL retention).
- [x] **Task 9.4 (Parametri Tipizzati & Integrazioni su 3 Livelli)**:
  - Introspection Engine in `backend/automations/introspection.py` basato su analisi AST e template inspection (`{{inputs.*}}`, `{{secrets.*}}`, `os.environ["*"]`).
  - Modale parametri con distinzione tra parametri rilevati dal workflow (con badge tipizzati string/number/boolean/secret) e parametri personalizzati.
  - Architettura a 3 livelli: Livello 1 (Integrazioni Globali Base), Livello 2 (Multi-account / override per singola automazione), Livello 3 (Credenziali dinamiche in `settings["secrets"]`).
  - Iniezione delle integrazioni attive nel system prompt dell'agente chat per grounding contestuale.
- [x] **Task 9.5 (Robustezza Harness & Fix Creazione Agentica)**:
  - Risoluzione anomalie in `normalize_proposal` e validazione pre-flight in `_create_custom`: step non vuoti, `initial_step_id` coerente, argomenti obbligatori per tool deterministici (es. `query` per `web_search`).
  - Schema contract e istruzioni canoniche aggiunte nel prompt di sistema dell'agente per grounding impeccabile.

---

## 3. Registro delle Modifiche e Diario di Implementazione

| Data | Milestone / Task | Componenti Coinvolti | Descrizione Modifiche | Esito Test |
| :--- | :--- | :--- | :--- | :---: |
| 2026-09-18 | Baseline | Documentazione | Creati `docs/automations/ARCHITECTURE.md`, `SPECIFICATION.md`, `IMPLEMENTATION_TRACKER.md` | PASS |
| 2026-09-18 | Milestone M0 | `backend/automations/db.py`, `backend/guardrails.py`, `backend/config.py` | Schema WAL SQLite per tabelle automazioni e persistenza approvazioni su restart | PASS (23/23) |
| 2026-09-18 | Milestone M1 | `backend/automations/models.py`, `backend/automations/runner.py`, `backend/automations/router.py`, `backend/api.py` | Step Runner con pause/resume su approvazione, dry-run, modelli Pydantic e API REST | PASS (29/29) |
| 2026-09-18 | Milestone M2 | `backend/automations/scheduler.py`, `backend/registry/email_tool.py`, `backend/automations/templates/daily_email_briefing.json` | APScheduler asincrono con sincronizzazione DB, Email tool registry (fetch, draft, save artifact) e template canonico MVP | PASS (32/32) |
| 2026-09-18 | Milestone M3 | `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/ThreadList.tsx`, `frontend/src/components/automations/*` | AutomationsView (4 schede), RunInspectorModal (timeline, tool calls, Markdown viewer) e switcher Chat/Automations | PASS (Vite OK) |
| 2026-09-18 | Milestone M4 | `backend/audit_log.py`, `backend/registry/manager.py`, `backend/automations/circuit_breaker.py`, `backend/automations/router.py`, `backend/test_automations_governance.py` | Governance & Security: correlation IDs in audit_log, CircuitBreakerManager (tripping su 3 errori, rate-limiting orario, budget token, reset), blocco rigido policy | PASS (36/36) |
| 2026-09-18 | Milestone M5 | `backend/sdk/*`, `backend/automations/code_runner.py`, `backend/automations/runner.py`, `backend/test_automations_sdk.py` | Custom Python SDK (@workflow, @step, AutomationContext), validazione manifest, AST security check, SandboxedCodeRunner | PASS (42/42) |
| 2026-09-18 | Milestone M6 | `backend/router.py`, `backend/graph.py`, `frontend/src/components/automations/AutomationProposalCard.tsx`, `frontend/src/components/MarkdownRenderer.tsx` | Creazione assistita in chat: intent recognition, blocco proposal structured markdown, interactive proposal card con dry-run e 1-click activation | PASS (Vite OK) |
| 2026-09-18 | Milestone M7 | `backend/automations/loops/coding_repair.py`, `backend/automations/templates/github_issue_repair.json`, `backend/test_automations_coding_repair.py` | Coding Repair Loop: tentativi di auto-diagnosi e fix iterativo in workspace effimero, unified diff e template workflow | PASS (45/45) |
| 2026-09-18 | Milestone M8 | `docs/automations/MIGRATION_EVALUATION.md` | Benchmarking reale su CT 125, analisi overhead Temporal vs SQLite WAL (<35MB vs 690MB+), decisione architetturale consolidata | PASS |
| 2026-09-20 | Post-Deploy Fixes | `backend/automations/*`, `backend/registry/automations_tool.py`, `backend/graph.py`, `backend/router.py`, `frontend/src/*` | Fix risoluzione approvazioni chat senza 400 'Run not found', eliminazione manuale e pulizia scadute; piena consapevolezza e tool automazioni per l'agente chat | PASS (56/56 + Live CT 125) |
| 2026-09-20 | Bugfix Chat Tools | `backend/registry/manager.py`, `backend/registry/automations_tool.py`, `backend/automations/scheduler.py`, `backend/automations/models.py`, `backend/api.py` | Fix execute_approved_tool con supporto a tutti i registry (automations, email); fix scheduler sync_triggers(); prevenzione blocco asyncio event loop su endpoint sincroni | PASS (CT 125 Live OK) |
| 2026-09-21 | Milestone M9 | `backend/automations/*`, `backend/integrations/*`, `frontend/src/*`, `docs/*` | Automations v2 completa: Sezione Artefatti e Report con split-pane e temporal grouping, retention auto-cleanup job e bulk delete, card live con morphing e drawer pipeline, introspezione parametri AST e integrazioni 3-tier, harness self-healing | PASS (29/29 test passati + Vite build OK) |

