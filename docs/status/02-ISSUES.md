# 02 — Problemi rilevati

Assessment del 2026-10-26. Severità: **S1** bug attivo in produzione · **S2** blocca qualità o sviluppo · **S3** debito tecnico · **S4** cosmetico.

| ID | Titolo | Sev. | Area | Stato |
| :--- | :--- | :---: | :--- | :--- |
| [ISS-01](#iss-01) | Retention automazioni rotta (`older_than_days`) | S1 | backend/automations | ✅ Risolto (`7205e75`) |
| [ISS-02](#iss-02) | `logger` non definito in `api.py` | S1 | backend/api | ✅ Risolto (`7205e75`) |
| [ISS-03](#iss-03) | `GET /v1/threads` → 500 su DB checkpoint vuoto | S1 | backend/api | ✅ Risolto (`7205e75`) |
| [ISS-04](#iss-04) | Suite di test che non termina (dipendenze live) | S2 | test | ✅ Risolto (`0021414`) |
| [ISS-05](#iss-05) | Test falliti (guardrails, tool_safety, modes, automations_api) | S2 | test | ✅ Risolto (`0021414`) |
| [ISS-06](#iss-06) | CI non versionata e troppo permissiva | S2 | CI | ✅ Risolto (A4) |
| [ISS-07](#iss-07) | Ambiente locale rotto dopo lo spostamento in `projects/` | S2 | dev env | ✅ Risolto (`b20e63b`) |
| [ISS-08](#iss-08) | 208 errori ruff | S3 | backend | ✅ Risolto (A4) |
| [ISS-09](#iss-09) | Moduli monolitici, backend non strutturato a pacchetti | S3 | architettura | Aperto |
| [ISS-10](#iss-10) | Fallback MCP legacy e shim di retrocompatibilità | S3 | backend | ✅ Risolto (B4, B5) |
| [ISS-11](#iss-11) | Bundle frontend unico da 947 kB | S3 | frontend | ✅ Risolto (Fase C) |
| [ISS-12](#iss-12) | Warning oxlint (hook deps, catch inutilizzati) | S4 | frontend | ✅ Risolto (A4) |
| [ISS-13](#iss-13) | `dev` non mergiato in `main` (100 commit) | S3 | processo | ✅ Risolto (A5, `v0.9.0`) |
| [ISS-14](#iss-14) | Documentazione disallineata | S4 | docs | ✅ Risolto (A5) |
| [ISS-15](#iss-15) | `pytest` assente nel container di produzione | S2 | deploy/test | ✅ Risolto (`b20e63b`) |
| [ISS-16](#iss-16) | Attesa di 180 s sul caricamento del modello anche se il load fallisce | S1 | backend/providers | ✅ Risolto (`b20e63b`) |
| [ISS-17](#iss-17) | I test non isolavano i dati persistenti | S1 | test | ✅ Risolto (`b20e63b`) |
| [ISS-18](#iss-18) | Fallback della sandbox: codice LLM eseguito dentro `agent-backend` | S2 | backend/registry | ✅ Risolto (fallback con approvazione) |
| [ISS-19](#iss-19) | PLAN ignorava la modalità di sicurezza scelta dall'utente | S1 | backend/graph | ✅ Risolto (`0021414`) |
| [ISS-20](#iss-20) | Fallback del router: "ct"/"vm" cercati come sottostringhe | S3 | backend/router | ✅ Risolto (`0021414`) |
| [ISS-21](#iss-21) | Risoluzione template non deterministica (template sbagliato creato) | S1 | backend/automations | ✅ Risolto (`0021414`) |
| [ISS-22](#iss-22) | Modello di embedding scaricato a runtime da HuggingFace | S2 | deploy | ✅ Risolto (`16eae3a`) |
| [ISS-23](#iss-23) | Il router chiama l'LLM con `requests` diretto, scavalcando i provider | S3 | backend/router | ✅ Risolto in B8 |
| [ISS-24](#iss-24) | Letta non in esecuzione su CT 102: niente memoria archivistica né summary persistenti | S2 | infra/memoria | ✅ Risolto (Letta rimosso, E1) |
| [ISS-25](#iss-25) | Recupero dei thread dai checkpoint a ogni apertura; `verify_api_key` triplicata | S3 | backend | ✅ Risolto (B10) |
| [ISS-26](#iss-26) | Agent loop lento sui modelli locali: prompt non riusabile dalla cache di llama.cpp e osservazioni senza limite | S2 | backend/agent, infra LLM | 🟡 Backend risolto, infra aperta |
| [ISS-27](#iss-27) | Eval `planning/new-service` e `rollback/ip-only` da rivedere insieme a ProxmoxMcp | S3 | evals, ProxmoxMcp | Rimandato |
| [ISS-28](#iss-28) | La selezione dei tool a volte mette chiamate inventate in `final_answer`, che il loop mostra come risposta | S2 | agent loop | Aperto |

---

## ISS-01
**Retention automazioni rotta (`older_than_days`)** — S1

- **Evidenza**: log di `agent-backend` su CT 125:
  `ERROR:automations.scheduler:Errore durante l'esecuzione di auto-retention cleanup: bulk_delete_runs() got an unexpected keyword argument 'older_than_days'`
- **Causa**: `automations/db.py:622` (oggi [db/runs.py](../../backend/app/automations/db/runs.py)) definisce `bulk_delete_runs(status, before_date, automation_id, failed_only, preserve_protected, run_ids, db_path)`, ma tre chiamanti passano `older_than_days`:
  - [automations/scheduler.py:189](../../backend/app/automations/scheduler.py) e `:195` (job di retention)
  - [automations/router.py:262](../../backend/app/automations/router.py) (`DELETE /v1/automations/runs`)
  - [automations/router.py:275](../../backend/app/automations/router.py) (`POST /v1/automations/runs/delete-batch`)
- **Impatto**: le run storiche non vengono mai eliminate e `automations.db` cresce senza limite. Gli endpoint di cancellazione massiva rispondono con 500 (dedotto dal codice). Il tracker M9 segna la retention come completata, ma non funziona.
- **Perché i test non l'hanno visto**: nessun test esegue `_run_retention_cleanup` né le due route di cancellazione con i parametri reali.

## ISS-02
**`logger` non definito in `api.py`** — S1

- **Evidenza**: `ruff F821` su [api.py:1012](../../backend/app/api/) e [api.py:1048](../../backend/app/api/). Il modulo importa `logging` ma non definisce mai `logger`.
- **Impatto**: quando si entra nei rami di errore, l'endpoint fallisce con `NameError` (500) invece di scrivere un warning nel log e proseguire.

## ISS-03
**`GET /v1/threads` → 500 su DB checkpoint vuoto** — S1

- **Evidenza**: `test_stream_api.py` (2 test) riceve `500 != 200`. Riprodotto: in un DB di test pulito `sqlite_master` è vuoto e la query in [api.py:743](../../backend/app/api/) fa `SELECT ... FROM checkpoints`.
- **Causa**: la tabella `checkpoints` viene creata da `SqliteSaver` in modo lazy, solo alla prima esecuzione del grafo. `thread_store.init_db()` crea le sue tabelle, non quelle di LangGraph.
- **Impatto**: dopo un reset del database (operazione prevista in dev da AGENTS.md), la lista dei thread va in errore finché non parte la prima chat. La UI resta senza sidebar.
- **Consolidamento (B6, 2026-10-27)**: tutti gli schemi (checkpoint LangGraph, thread, audit, permessi, memoria vettoriale, automazioni, calendario) li crea [startup.py](../../backend/app/startup.py) `init_databases()`, chiamata dal lifespan, dalla CLI e dal `conftest` dei test. Nessun modulo crea tabelle o connessioni all'import; un errore di inizializzazione blocca l'avvio invece di essere solo loggato. Checkpointer, grafo compilato e registry dei tool sono creati alla prima richiesta (`get_checkpointer`, `get_app_graph`, `get_registry_manager`). Rimosse le migrazioni di colonne di `thread_messages` e `audit_log`, già applicate al DB di produzione, e le chiamate a `thread_store.init_db()` ripetute a ogni salvataggio.

## ISS-04
**Suite di test che non termina** — S2

- **Evidenza**: `pytest` completo bloccato oltre 10 minuti. Eseguiti file per file con timeout di 90 s, 7 file non terminano:
  `test_conversation_length`, `test_dynamic_tool_selection`, `test_phase4`, `test_rollback`, `test_memory_api`, `test_router_and_prefetch`, `test_automations_api::test_resolve_approval_create_automation_from_template`.
- **Causa**: test di integrazione che chiamano servizi reali (LLM via `build_graph()`, MetaMCP, Letta) senza mock né timeout; alcuni sono script "dimostrativi" che scrivono `memory/test_*.jsonl`. Manca una separazione unit/live e `pytest-timeout` non è installato.
- **Impatto**: impossibile usare i test come gate, sia in locale sia nel container (`docker exec agent-backend pytest` previsto dal workflow).

## ISS-05
**Test falliti** — S2

| Test | Errore | Ipotesi |
| :--- | :--- | :--- |
| `test_guardrails::TestApprovalWorkflow::test_pending_list_and_filter` | `6 != 2` | Approvazioni persistenti (M0) condivise tra test: stato non isolato |
| `test_tool_safety::TestMetaMCPPrefixAndRouter::test_router_infrastructure_and_confirmation_queries` | `'chat' != 'act'` | Il router "unificato LLM" (`d72ab1b`) ha cambiato la classificazione; test o regole da riallineare |
| `test_modes_and_registries::test_code_exec_sandbox` | `False is not true` | Sandbox di esecuzione codice non disponibile in locale (Firecracker o timeout di 60 s) |
| `test_stream_api` (2 test) | `500 != 200` | Vedi [ISS-03](#iss-03) |
| `test_agent_verification` | nessun test raccolto | Script, non test pytest |

## ISS-06
**CI non versionata e troppo permissiva** — S2 · ✅ Risolto in A4

- `.github/workflows/backend-ci.yml` esiste in locale ma non è tracciato da git: la CI non è mai girata.
- Anche committato, il workflow esegue solo 3 file di test, ignora ruff (`|| true`) e non copre il frontend (build e oxlint).
- **Fix**: sostituito da [ci.yml](../../.github/workflows/ci.yml), versionato e bloccante. Job **backend**: costruisce lo stage `test` del Dockerfile (lo stesso di `make test-container`, con cache GHA) ed esegue `ruff check` e l'intera suite `pytest`. Job **frontend**: Node 22 come il Dockerfile, `npm ci`, `npm run lint` (ora `oxlint --deny-warnings`), `npm run build`.

## ISS-07
**Ambiente locale rotto dopo lo spostamento in `projects/`** — S2

- `backend/.venv` è stato creato nel vecchio percorso `homelab/homelab-agent/`: gli entry-point (`.venv/bin/pytest`, ecc.) hanno uno shebang che punta a un interprete inesistente. Funziona solo `.venv/bin/python -m ...`.
- Python locale 3.14 contro 3.12 in Docker e CI: possibili divergenze (già visibile un `DeprecationWarning` di slowapi).
- `__pycache__` obsoleti riportano il percorso vecchio nei traceback.

## ISS-08
**208 errori ruff** — S3 · ✅ Risolto in A4

79 `F401` (import inutilizzati), 24 `I001`, 21 `B904`, 19 `E402`, 19 `E702`, 13 `W293`, 10 `F841`, 9 `B008`, 3 `F811`, 2 `F821` (→ [ISS-02](#iss-02)), più altri minori. 120 si correggono con `--fix`.

- **Fix**: `ruff check` → 0 errori (`target-version` portato a `py312`). Fix automatici più correzioni manuali: `raise ... from e` nei 21 `except`, import spostati in testa (`api.py`, `graph.py`, `letta_client.py`, `search_content.py`), `BackgroundTasks()` tolto dai default degli endpoint (FastAPI lo inietta), `B008` ammesso solo per i marcatori FastAPI (`Body`, `Depends`, `File`, `Query`, `Security`) via `extend-immutable-calls`. Rimossi anche i `datetime.utcnow()` deprecati in `graph.py`: la suite non emette più warning.

## ISS-09
**Moduli monolitici, backend non strutturato a pacchetti** — S3

- File oltre le 1000 righe: [graph.py](../../backend/app/agent/graph.py) (1730), `automations/db.py` (1315), [api.py](../../backend/app/api/) (1202).
- Tutti i moduli e i 34 test stanno nella radice di `backend/`, insieme ai database SQLite.
- La ristrutturazione a pacchetti (Fase 1.5 della vecchia roadmap) era stata rinviata per non rompere CT 112, ora dismesso: il vincolo non esiste più.
- **Avanzamento (B7, 2026-10-27)**: i dati persistenti stanno tutti in `DATA_DIR` (default `<repo>/data`, `/data` nei compose); database, memoria, artefatti, upload e knowledge base sono proprietà di `settings` derivate da lì e non più configurabili singolarmente, così un `CHECKPOINT_DB_PATH` rimasto in un `.env` non può più far scrivere i test sui dati reali. Rimossi il controllo "`/data` esiste ed è scrivibile" e i fallback nella radice di `backend/`. `create_artifact` scriveva sul percorso suggerito dal modello: ora tiene solo il nome del file dentro `artifacts/`. I test che sovrascrivevano i percorsi ripristinano `data_dir` a fine test; `test_guardrails` usa un DB delle automazioni isolato (passava solo grazie a un percorso rimasto puntato su una directory cancellata).
- **Avanzamento (B11, 2026-10-27)**: [runner.py](../../backend/app/automations/runner.py) da 991 a 330 righe. Ogni tipo di step ha il suo gestore in [automations/steps/](../../backend/app/automations/steps/) (approval, codice, calendario, tool, agentico), scelto da `select_handler` con un `StepContext` comune; template e contenuto degli step in `templating.py`, raccolta dei secrets in `run_secrets.py`. `execute_run` delega l'esecuzione e la registrazione di ogni step a `_run_step`. Rimossi l'alias `create_run`, il parametro doppione `is_dry_run` di `start_run` e un ramo irraggiungibile (`calendar_*` nel gestore dei tool). Bug corretto: il tool `automations_trigger_run` importava un `get_runner` inesistente e chiamava `execute_run` con parametri sbagliati, quindi l'avvio di un'automazione dalla chat falliva sempre.
- **Avanzamento (B12, 2026-10-27)**: `run_agent_loop` (una funzione da 536 righe) è ora un ingresso sottile su [AgentLoop](../../backend/app/agent/agent_loop.py), che tiene lo stato del turno (osservazioni, cache, anti-loop, ragionamenti) con un metodo per fase: selezione del tool, risposta finale, chiamate parallele, validazione, ripetizioni, esecuzione, approvazione, sintesi; il metodo più lungo è `run` (42 righe). I prompt sono in `agent_prompts.py`, testo invariato. Rimossi i due `except TypeError` che ritentavano la chiamata LLM senza `reasoning_phase` o `images` (nascondevano anche i `TypeError` veri): il contratto delle funzioni LLM è documentato nel modulo. Rimosso un ramo anti-loop irraggiungibile ("avviso al primo doppione": il contatore includeva già la prima chiamata, quindi una ripetizione chiudeva sempre il loop). Nuovi test in `test_agent_loop.py`.
- **Avanzamento (B13, 2026-10-27)**: `automations/router.py` (799 righe) diviso in [automations/routes/](../../backend/app/automations/routes/), un modulo per dominio (il più grande, `definitions.py`, 270 righe); `security/guardrails.py` (770) diviso in [policy.py](../../backend/app/security/policy.py) (classificazione, analisi shell, decisione) e [approvals.py](../../backend/app/security/approvals.py) (richieste, scope, approvazioni a runtime). Con B13 la Fase B è completa, ma il criterio di uscita "nessuna funzione sopra ~100 righe" non è ancora rispettato: restano 19 funzioni, le più lunghe `automations/models.py::normalize_proposal` (327), `agent/nodes/plan.py::plan_graph_node` (220), `agent/mode_router.py::route_turn` (196), `automations/code_runner.py::run_script` (182), `registry/web_search_service.py::execute_search` (171), `api/routes/approvals.py::resolve_approval_endpoint` (150), `api/agent_runner.py::run_agent_flow_stream` (149); i `get_tools` di calendario e automazioni (266 e 243) sono quasi solo schemi JSON statici.
- **Avanzamento (B1, 2026-10-27)**: codice nel pacchetto `app/` con sottopacchetti per dominio e import assoluti; `api.py` diviso in `app/api/routes/` (8 router, il più grande ~240 righe) più `agent_runner.py` e `deps.py`. Restano `graph.py` (B2), `automations/db.py` (B3) e i database nella radice del codice (B7).
- **Avanzamento (B2, 2026-10-27)**: `graph.py` (1730 righe) diviso in `app/agent/nodes/` (un modulo per nodo, il più grande ~235 righe), `execution_log.py` (Saga/WAL, ~340), `llm_calls.py`, `state.py` e `memory/transcript.py`; `graph.py` resta con la sola costruzione del grafo (~75 righe). Restano `automations/db.py` (B3) e i database nella radice del codice (B7).
- **Avanzamento (B3, 2026-10-27)**: `automations/db.py` (1316 righe) diviso nel pacchetto `app/automations/db/` (il modulo più grande, `runs.py`, ~420 righe); i chiamanti importano i moduli per aggregato. Sopra le ~600 righe restano `automations/runner.py` (995), `automations/router.py` (808), `agent_loop.py` (605) e `automations/models.py` (602).

## ISS-10
**Fallback MCP legacy e shim di retrocompatibilità** — S3 · ✅ Risolto in B4 e B5

- [registry/metamcp.py:25](../../backend/app/registry/metamcp.py): l'SDK MCP ufficiale è primario, ma resta il fallback al client custom [mcp_client.py](../../backend/app/mcp/client.py) (316 righe).
- [config.py](../../backend/app/core/config.py) mantiene costanti "per retrocompatibilità" oltre a Pydantic Settings.
- Contrario al principio "No Legacy Code" di [AGENTS.md](../../AGENTS.md).
- **Avanzamento (B4, 2026-10-27)**: client legacy e wrapper SSE sostituiti da un unico [client.py](../../backend/app/mcp/client.py) sull'SDK `mcp` 2.x in Streamable HTTP, condiviso da registry, catalogo ed esecuzione dei piani. La sessione vive in un solo task asyncio (prima veniva aperta e chiusa in task diversi). `call_tool` ritenta solo su sessione già aperta e mai dopo un timeout: prima un timeout dell'SDK faceva rieseguire il tool al client legacy. Un risultato `isError` diventa `{"error": ...}`, quindi audit e piani vedono i tool falliti. Rimossi il fallback OpenAPI del catalogo e `METAMCP_URL_HTTP`. Restano le costanti di retrocompatibilità di `config.py` (B5).
- **Fix (B5, 2026-10-27)**: [config.py](../../backend/app/core/config.py) espone solo l'istanza `settings` (più `BACKEND_DIR`); i moduli leggono `settings.<campo>` al momento dell'uso e i test sovrascrivono gli attributi di `settings`. `memory_dir` vuota viene risolta da un validator accanto al DB dei checkpoint. `SEARXNG_URL`, `SEARXNG_ENGINES`, `SEARCH_PRIMARY_LANG` e `SEARCH_FALLBACK_LANG` non sono più letti con `os.environ` ma passano dalle settings. Rimossi i riferimenti a chiavi mai definite (`OLLAMA_MODEL`, `LLAMA_CPP_API_KEY`).

## ISS-11
**Bundle frontend unico da 947 kB** — S3

Nessun code-splitting: automazioni, calendario e highlight.js finiscono tutti nel chunk iniziale. Componenti da oltre 1000 righe: `AutomationsView`, `api.ts`, `CalendarView`, `Chat`.

- **C1 (2026-10-27)**: viste secondarie con `React.lazy` dietro `LazyBoundary` (Suspense + ErrorBoundary, così un chunk che non arriva non fa cadere l'app); highlight.js caricato da `MarkdownRenderer` solo quando il contenuto ha un blocco di codice; React in un chunk vendor separato. Chunk iniziale da 947 a 291 kB, JS iniziale da 262 a 160 kB gzip. In nginx: `index.html` sempre rivalidato, asset con hash `immutable`, chunk mancante = 404 invece della pagina SPA, gzip attivo.
- **C2 (2026-10-27)**: `api.ts` diviso in `src/api/` (un modulo per gruppo di route) su un client `fetch` con `ApiError`; axios rimosso, JS iniziale da 541 a 490 kB (144 kB gzip).
- **C3 (2026-10-27)**: `Chat.tsx` (1205), `AutomationsView.tsx` (1385) e `CalendarView.tsx` (1285) divisi in sotto-componenti con hook dedicati; `useChat` da 830 a 436 righe (stream con oggetto `StreamHandlers`, diagnostica in un unico stato, un solo updater dei messaggi). Bug trovati e corretti: la rigenerazione dopo la modifica di un prompt inviava il prompt vecchio; vista settimana e "oggi" del mese usavano date UTC (giorno sbagliato tra mezzanotte e le 2); il selettore del mese si riapriva cliccando sul titolo.
- **Chiusura (2026-10-28)**: divisi anche i 6 componenti rimasti sopra le 500 righe, valutati uno per uno. Bug trovati e corretti:
  - **Modifica automazione**: il salvataggio sostituiva tutti i trigger con un solo cron (webhook e manuali cancellati, il primo trigger trasformato in un cron alle 12:00). Scheda trigger rimossa: i trigger si modificano solo dal loro modale.
  - **Modifica automazione**: il JSON dei parametri di uno step non si poteva digitare (ogni tasto che lo rendeva non valido veniva scartato); tipi di step e tool sconosciuti comparivano come la prima opzione; id dei nuovi step potevano collidere.
  - **Trigger**: un cron `1-5` veniva salvato come solo lunedì; il fuso era sempre forzato a `Europe/Rome`; i trigger manuali e di altri tipi venivano eliminati.
  - **Impostazioni**: la modalità di sicurezza non arrivava alla toolbar della chat fino al reload (ora `useSecurityMode`, condiviso).
  - **Artefatti e trigger**: la copia negli appunti usava `navigator.clipboard`, assente su HTTP in LAN; gli artefatti mostravano due toast per ogni azione.

## ISS-12
**Warning oxlint** — S4 · ✅ Risolto in A4

- `react-hooks/exhaustive-deps`: `CalendarView.tsx:95` e `:218`, `ArtifactsView.tsx:93` e `:128`. Rischio di stale closure.
- `no-unused-vars` sul parametro dei `catch`: `AutomationProposalCard.tsx:141`, `ArtifactsView.tsx:153`, `:172`, `:191`. Errori inghiottiti senza feedback.
- Con oxlint 1.76 i warning erano 16 (in più: `only-export-components`, escape inutili, `Boolean()` ridondante).
- **Fix**: 0 warning con `--deny-warnings`. `showFeedback` di `AutomationsView` e `ArtifactsView` stabilizzato con `useCallback`, così i loader dei figli possono dipenderne senza loop; `ArtifactsView` sceglie il primo artefatto con un setter funzionale invece di leggere `selectedId`; `useTheme` spostato in `theme/useTheme.ts` con il context in `theme/context.ts`.

## ISS-13
**`dev` non mergiato in `main`** — S3 · ✅ Risolto in A5

100 commit avanti. `main` non rappresenta nessuno stato funzionante noto.

- **Fix**: `main` portato in fast-forward su `dev` e taggato `v0.9.0`, primo baseline stabile (CI verde, verificato su CT 125). Da qui `main` = ultimo stato verificato; lo sviluppo resta su `dev`.

## ISS-14
**Documentazione disallineata** — S4 · ✅ Risolto in A5

- [ROADMAP.md](../../ROADMAP.md) è ferma ad agosto.
- Il tracker automazioni dichiara M9 completata nonostante [ISS-01](#iss-01).
- 3 file in `docs/` hanno modifiche non committate (percorsi aggiornati).
- **Fix**: [ROADMAP.md](../../ROADMAP.md) marcata come storica (la roadmap attiva è [04-ROADMAP.md](04-ROADMAP.md)); nota sul bug di retention nel tracker automazioni; percorsi in `docs/` già committati. Workflow di test in README e piano corretti: `pytest` solo nel servizio `backend-test`. [backend/README.md](../../backend/README.md) senza la sezione systemd legacy e con installazione via `make venv`.

## ISS-15
**`pytest` assente nel container di produzione** — S2

- **Evidenza** (2026-10-26, CT 125): `docker exec agent-backend python -m pytest` → `No module named pytest`.
- **Causa**: [requirements.txt](../../backend/requirements.txt) non include le dipendenze di test e il Dockerfile non ha uno stage di test.
- **Impatto**: il passo 5 del workflow in [AGENTS.md](../../AGENTS.md) ("In-Container Test Execution") non è eseguibile.
- **Fix previsto**: in A2/A3, `requirements-dev.txt` installato in uno stage o target Docker `test` (per esempio `docker compose run --rm backend-test`), senza appesantire l'immagine di produzione.

## ISS-16
**Attesa di 180 s sul caricamento del modello anche se il load fallisce** — S1 · ✅ Risolto in `b20e63b`

- **Causa**: `OpenAICompatProvider.ensure_model_loaded` ([providers.py](../../backend/app/llm/providers.py)), introdotto in `675d12a`, dopo una richiesta `/models/load` fallita (server irraggiungibile, endpoint non supportato, modello sconosciuto) continuava a interrogare `/models` ogni secondo fino a 180 s.
- **Impatto**: con l'LLM non raggiungibile, ogni chiamata (router, chat, titoli) restava appesa fino a 3 minuti invece di fallire. È anche la causa principale dei test bloccati di [ISS-04](#iss-04).
- **Fix**: se il load non parte (`status != "ok"`), il metodo ritorna subito `False`. Coperto da due test in `test_model_features.py`.

## ISS-17
**I test non isolavano i dati persistenti** — S1 · ✅ Risolto in `b20e63b`

- **Causa**: `conftest.py` isolava solo `CHECKPOINT_DB_PATH`. Automazioni, calendario, artefatti e memoria usavano `/data/...` quando la directory era scrivibile, o i file nella radice di `backend/` in locale.
- **Impatto**: eseguire `pytest` dentro `agent-backend`, come prescriveva il workflow, avrebbe scritto nei database di produzione. In locale i test sporcavano `backend/*.db` e `backend/memory/`.
- **Fix**: `conftest.py` reindirizza tutti i path in una directory temporanea e disattiva lo scheduler. `MEMORY_DIR` è diventato configurabile (`config.MEMORY_DIR`). I test girano nel servizio `backend-test`, senza il volume di produzione e con `/data` su tmpfs.

## ISS-18
**Fallback della sandbox: codice LLM eseguito dentro `agent-backend`** — S2 · ✅ Risolto (opzione b: fallback solo previa approvazione)

- **Evidenza**: [registry/firecracker_sandbox.py](../../backend/app/registry/firecracker_sandbox.py) `_execute_fallback`. Se l'API Firecracker non risponde, fallisce o va in timeout, il codice Python del tool `python_interpreter` viene eseguito con `subprocess` nel container del backend (`sandboxed: False`).
- **Impatto**: codice generato dall'LLM con accesso a `/data` (database, memoria), a `.env` (chiavi API) e alla rete del backend. Oggi su CT 125 Firecracker risponde, quindi il fallback scatta solo se la sandbox va giù.
- **Opzioni valutate**: (a) nessun fallback; (b) fallback solo previa approvazione utente; (c) container usa-e-getta. **Scelta (b)**, il 2026-10-26.
- **Implementazione**:
  - `FirecrackerSandbox.execute_code` non ripiega più da sola: ritorna `sandbox_unavailable`. L'esecuzione locale è un metodo separato, `execute_local`.
  - `CodeExecRegistry` solleva `guardrails.ApprovalRequired(LOCAL_CODE_FALLBACK)`; il registry manager la converte in una richiesta di approvazione standard (card inline) con il codice come anteprima e `command_prefix = "local-fallback"`.
  - L'esecuzione locale è autorizzata solo da: approvazione di quella richiesta (contextvar non impostabile dall'LLM), permesso "per questa chat" o "sempre" su `python_interpreter` + `local-fallback`, oppure modalità `dangerous`, che per definizione esegue senza conferme.
  - Un'approvazione data per l'esecuzione nella sandbox non sblocca mai quella locale: se nel frattempo la sandbox è giù, compare una seconda card specifica.
  - Anche il timeout della microVM (codice lento o in loop) passa ora dall'approvazione, invece di rieseguire il codice in locale.
  - Coperto da `tests/test_code_sandbox_approval.py` (9 test, incluso il flusso API in due passi).

## ISS-19
**PLAN ignorava la modalità di sicurezza scelta dall'utente** — S1 · ✅ Risolto in `0021414`

- `execute_plan_node` ([graph.py](../../backend/app/agent/graph.py)) chiamava `enforce_guardrails` senza `security_mode`, quindi i piani giravano sempre in `normal`: `safest` applicava meno controlli di quelli richiesti e `dangerous` veniva ignorato.
- Coperto da `tests/test_rollback.py` (piano in `dangerous` fino al rollback; piano in `normal` fermo all'approvazione).

## ISS-20
**Fallback del router: "ct"/"vm" cercati come sottostringhe** — S3 · ✅ Risolto in `0021414`

- Con l'LLM non disponibile, il fallback di [router.py](../../backend/app/agent/mode_router.py) classificava come ACT qualsiasi testo contenente "ct" o "vm" ("project", "select", "direct"...). Ora usa parole intere. Aggiunta anche "plan the" alle parole chiave di pianificazione esplicita.

## ISS-21
**Risoluzione template non deterministica** — S1 · ✅ Risolto in `0021414`

- [registry/automations_tool.py](../../backend/app/registry/automations_tool.py) risolveva id e alias con un confronto approssimativo ("contiene `email`") in ordine di filesystem. Con due template "email", `get_automation_details` e `create_automation_from_template` potevano restituire o **creare il template sbagliato**, anche se l'id richiesto era esatto. Su CT 125 (ordine ext4) succedeva.
- Ora c'è un unico resolver a priorità (id esatto, poi id normalizzato o nome file, poi alias solo se univoco), coperto da `tests/test_automation_templates.py`.

## ISS-22
**Modello di embedding scaricato a runtime da HuggingFace** — S2 · ✅ Risolto in `16eae3a`

- fastembed scaricava ~240 MB al primo uso dopo ogni ricreazione del container: la memoria semantica dipendeva dalla raggiungibilità di HuggingFace. Ora il modello è incluso nell'immagine (`FASTEMBED_CACHE_PATH=/opt/fastembed`); un test verifica che Dockerfile e `vector_store.EMBEDDING_MODEL` coincidano.

## ISS-23
**Il router chiama l'LLM con `requests` diretto, scavalcando i provider** — S3 · ✅ Risolto in B8

- `route_turn` ([router.py](../../backend/app/agent/mode_router.py)) costruisce il payload e chiama `config.LLAMA_CPP_URL` con `requests.post`, ignorando il provider attivo (Ollama, provider di default scelto in UI) e le sue opzioni. Usa il provider solo per `ensure_model_loaded`.
- Da allineare in Fase B: il router deve passare da `providers.get_provider().chat(...)`.
- **Fix (B8, 2026-10-27)**: `route_turn` chiama `get_provider().chat(..., reasoning_budget=0, json_mode=True)`. `json_mode` è nuovo nell'interfaccia dei provider (`response_format` per llama.cpp, `format: json` per Ollama). Il router segue il provider e il modello attivi; il caricamento del modello lo gestisce il provider. Una risposta vuota (LLM offline o timeout) porta al fallback deterministico. Prima una risposta vuota sarebbe diventata "chat" senza passare dal fallback. Rimossi anche `classify_mode` (wrapper di retrocompatibilità) e il doppione di `is_purely_visual_request` in `web_prefetch`.
- **Emerso nella verifica su CT 125**: con `LFM2.5-24B-A2B-HugeCtx`, `enable_thinking: false` non basta: il modello ragiona comunque e consuma tutto `max_tokens`, quindi il contenuto resta vuoto. Il vecchio router trasformava questa risposta vuota in "chat" senza segnalarlo. Ora il provider manda anche `reasoning_budget_tokens: 0` quando `reasoning_budget=0`. La correzione vale per tutte le chiamate senza ragionamento: router, summary, fatti salienti, sintesi post-approvazione, query visiva.

## ISS-24
**Letta non in esecuzione su CT 102** — S2 · ✅ Risolto il 2026-10-29 (Letta rimosso dal backend)

- `/v1/status` risponde `degraded`: `http://192.168.1.177:8083` non risponde. CT 102 (`memory-services`) è acceso, ma nessun processo ascolta su 8083 e non gira nessun container Docker.
- Impatto: [letta_client.py](../../backend/app/memory/letta_client.py) fallisce in modo silenzioso. La cronologia ripiega sulla trascrizione JSONL ([transcript.py](../../backend/app/memory/transcript.py)), ma la memoria archivistica Letta (fatti salienti, summary incrementali) non viene salvata e `commit_memory` non scrive nulla. Il recall semantico cross-thread usa sqlite-vec e non ne risente.
- **Causa**: i container di Letta erano fermi dal 2026-08-04 (uscita 255, nessuna politica di riavvio); nessuno se n'era accorto perché l'agente ripiegava sui file locali.
- **Decisione (2026-10-29)**: Letta era usato solo come archivio passivo, con i messaggi salvati quattro volte e una cronologia ferma ad agosto. Rimosso dal backend; la memoria è tutta in `checkpoints.db` ([ricerca](../memory/MEMORY_RESEARCH.md)). CT 102 e i suoi dati restano intatti, spenti.
- **Fix (E1)**: cronologia solo da `thread_store`; riassunto incrementale in `thread_summaries` (prima un file mai aggiornato dopo la prima generazione); eliminati `letta_client.py`, `transcript.py` (JSONL), il nodo `commit_memory`, la configurazione `LETTA_*` e il controllo di salute.

## ISS-25
**Recupero dei thread dai checkpoint a ogni apertura; `verify_api_key` triplicata** — S3 · ✅ Risolto in B10

- **Evidenza**: `GET /v1/threads/{id}` chiama `thread_store.repair_missing_web_prefetch` se una qualunque risposta non ha `web_prefetch`, cosa normale per i turni chat e act. In produzione succede per 4 thread su 10: ogni apertura rilegge l'intera storia dei checkpoint LangGraph e scrive sul DB durante una GET (40–50 ms con 51 checkpoint, cresce con la lunghezza del thread). `backfill_from_state_history` (211 righe) ricostruisce i messaggi dei thread nati prima di `thread_store`: in produzione nessun thread ne ha bisogno.
- **Causa**: funzioni di recupero introdotte per migrare i dati (agosto e settembre 2026), rimaste nel percorso di lettura.
- `verify_api_key` è definita in `api/deps.py`, `automations/router.py` e `calendar/router.py`, con un confronto `!=` invece di uno a tempo costante.
- **Effetto collaterale trovato**: anche i turni in incognito scrivono checkpoint LangGraph. La lista dei thread univa checkpoint e messaggi, quindi un thread incognito compariva nella sidebar e `backfill_from_state_history` ne salvava i turni nello store, annullando l'incognito. L'ordinamento confrontava inoltre i `rowid` di due tabelle diverse.
- **Fix (B10, 2026-10-27)**: rimosse le due funzioni di recupero (`thread_store` da 707 a 430 righe). La lista dei thread parte da `thread_messages`, la fonte di verità, con il conteggio dei checkpoint in `LEFT JOIN`; l'apertura di un thread legge solo lo store. `verify_api_key` esiste solo in [deps.py](../../backend/app/api/deps.py) con `secrets.compare_digest`, usata anche dai router di calendario e automazioni. Unificato `parse_natural_duration` in `calendar/db.py`; rimosso l'alias `SAFE_TOOLS`. Test: `test_threads_api.py`, `test_auth.py`.
- **Resta aperto**: i checkpoint LangGraph dei turni incogniti restano nel DB (il grafo ha sempre il checkpointer). Da valutare se usare un thread effimero o cancellarli a fine turno.

## ISS-26
**Agent loop lento sui modelli locali: prompt non riusabile dalla cache di llama.cpp e osservazioni senza limite** — S2

- **Evidenza (prova live B12, 2026-10-27, LFM2.5-24B-A2B-HugeCtx)**: "elenca i container LXC" in act. Passo 1: prompt di 7.928 token, 77 s di prompt eval (~100 token/s). `list_containers` restituisce il JSON completo di ~50 container; il passo 2 ha un prompt di ~17.000 token, elaborato a velocità decrescente (da ~400 a 57 token/s) finché il provider va in timeout, ritenta da capo e llama.cpp continua a elaborare la richiesta abbandonata. Il turno non si chiude in 10 minuti.
- **Cause lato backend**:
  - [agent_prompts.py](../../backend/app/agent/agent_prompts.py) apre ogni system prompt con data e ora al secondo: il prefisso cambia a ogni chiamata e la prompt cache di llama.cpp non viene mai riusata, quindi ogni passo rielabora da zero catalogo, regole e storico.
  - Le osservazioni (storico dei tool) stanno a metà del system prompt di selezione, prima delle regole: anche con un prefisso stabile, tutto ciò che segue va rielaborato.
  - I risultati dei tool entrano interi nel prompt di selezione; `TRUNCATION_LIMIT` (40.000 caratteri) vale solo per la sintesi finale.
  - Il retry del provider dopo un timeout di lettura riparte dall'inizio mentre il server sta ancora elaborando la richiesta precedente.
- **Causa lato infra (CT 100)**: preset `LFM2.5-24B-A2B-HugeCtx` con KV cache `turbo2` e quantizzazione IQ3_XXS su V100: l'elaborazione dei prompt rallenta molto al crescere del contesto. Da confrontare con il profilo `Balanced` (Q3_K_XL) o con una KV cache `q8_0`.
- **Proposta**: parte statica del prompt (identità, catalogo, regole) in testa e senza orario al secondo; parte variabile (memoria, prefetch, osservazioni, data) in coda; limite per osservazione nel prompt di selezione (risultato completo nella traccia); nessun retry automatico dopo un timeout di lettura.
- **Risolto lato backend (2026-10-27, `03e89ef`…`9c2c260`)**:
  - System prompt statici per modalità; data (al minuto, fissata per il turno), memoria, prefetch e storico dei tool nel messaggio utente, storico in coda: ogni passo di selezione estende il prompt del precedente.
  - Ogni risultato di tool entra nello storico di selezione accorciato a `AGENT_OBSERVATION_LIMIT` (4.000 caratteri); la sintesi riceve i risultati interi e una `final_answer` scritta su dati accorciati viene scartata. I risultati MCP che sono testo JSON vengono decodificati prima di entrare nel prompt (`list_containers`: da 22.453 caratteri con escape a 15.752).
  - `OpenAICompatProvider` è sempre in streaming con `return_progress`: llama.cpp manda un chunk per batch, un prompt lungo non fa più scattare il timeout di lettura e una disconnessione libera lo slot. Si ritenta solo un errore di connessione; un timeout o un errore HTTP solleva `LLMUnavailableError` e il turno si chiude con un messaggio, senza nuove richieste.
  - Selezione strutturata vincolata dalla grammatica JSON-schema di llama.cpp (`response_format`, tutti i campi obbligatori, `arguments` anche `null`): il modello ragiona, emette un solo oggetto valido e si ferma. Prima LFM2.5 chiudeva il JSON e continuava fino a `max_tokens` (4.096 token, 224 s) oppure passava alla sua sintassi nativa di tool call.
  - La sintesi usa un prompt ridotto senza catalogo né specifica delle automazioni e con l'indicazione che non ci sono tool: con il prompt completo LFM2.5 rispondeva con una tool call.
- **Verifica live (stessa richiesta, LFM2.5)**: il turno si chiude in 290 s (prima non si chiudeva in 10 minuti). Passo 1 a freddo: 7.884 token di prompt in 77 s, selezione valida al primo tentativo. Passo 2: 7.372 token dalla cache e 2.418 nuovi in 51 s. Sintesi: 7.596 token in 72 s, 1.815 generati, tabella dei container in italiano (qualità del riepilogo limitata dal modello).
- **Ancora aperto (infra CT 100)**: l'elaborazione dei prompt resta lenta e degrada con il contesto (circa 400 token/s all'inizio, 100 a 8.000 token, 51 token/s per 557 token aggiunti a 8.000 di contesto). È il costo dominante del turno. LFM2.5 è ibrido (convoluzioni più attention): llama.cpp riprende un prompt solo dai checkpoint, quindi il riuso funziona quando un prompt estende il precedente ma non su un prefisso comune parziale. Da valutare con l'utente: KV cache `q8_0` al posto di `turbo2` o un profilo con quantizzazione meno spinta.

## ISS-27

- **`planning/new-service`**: il caso chiede un servizio web con IP, container, DNS e proxy, e si aspetta i quattro tool separati. Da E5 Qwen3.6-35B sceglie in modo stabile il tool composito `create_service`, preceduto dal dry run, che fa lo stesso provisioning in una chiamata. Non dipende dalla memoria. Per l'utente il tool dedicato è la scelta giusta: meno token e meno errori tra un passo e l'altro, se il tool è corretto. Il caso andrà riscritto per accettarlo; nella stessa revisione va controllato che il modello passi gli argomenti giusti (`create_service` di default esegue anche il bootstrap Agy, `skip_agy=false`).
- **`rollback/ip-only`**: il piano di compensazione chiama `release_ip` senza l'indirizzo da rilasciare.
- **Quando**: con la revisione di ProxmoxMcp (bug, refactoring, nuove feature), dopo la fase E.

## ISS-28

- **Evidenza**: nella suite `multistep` con Qwen3.6-35B (2026-10-30), circa un'esecuzione su quindici, con il pensiero tra i passi acceso o spento, termina senza alcuna chiamata. La risposta all'utente è testo come ` ```docker_ps``` ` o un JSON di chiamate a tool inesistenti (`zfs_list_snapshots`).
- **Causa**: il modello restituisce `tool_needed=false` e scrive in `final_answer` le chiamate che intendeva fare. `_final_answer` in [agent_loop.py](../../backend/app/agent/agent_loop.py) accetta come risposta finale qualunque `final_answer` più lungo di 10 caratteri.
- **Direzione**: riconoscere un `final_answer` che è codice o una lista di chiamate (blocco di codice senza prosa, nomi di tool) e trattarlo come selezione non valida, con un nuovo tentativo che lo spiega al modello.

