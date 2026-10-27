# 03 — Piano di correzione

Ogni step segue il workflow di [AGENTS.md](../../AGENTS.md): modifica su `dev`, validazione locale, push, deploy su CT 125, verifica live. Gli step sono ordinati per dipendenza: quelli successivi assumono che i test siano già affidabili.

## Step 1 — Hotfix di produzione (ISS-01, ISS-02, ISS-03)

### 1.1 Retention automazioni
- In `bulk_delete_runs` ([automations/db.py](../../backend/app/automations/db.py)) sostituire `before_date` (nessun chiamante lo usa) con `older_than_days: Optional[int]`, tradotto nel filtro esistente `started_at < now - N giorni`. Resta un solo modo di esprimere il cutoff.
- Verificare che `preserve_protected` resti attivo nella retention automatica (le run marcate come protette non si cancellano).
- **Test nuovi**: retention per singola automazione e globale; `DELETE /v1/automations/runs?older_than_days=` e `POST /runs/delete-batch`.

### 1.2 Logger in `api.py`
- Aggiungere `logger = logging.getLogger(__name__)` a livello modulo e rimuovere l'`import logging` locale alla riga ~871.

### 1.3 Lista thread su DB vuoto
- Rendere esplicito il setup dello schema LangGraph: subito dopo `memory = SqliteSaver(conn)` ([graph.py:134](../../backend/app/agent/graph.py)) chiamare `memory.setup()`, così la tabella `checkpoints` esiste sempre. Nella Fase B (B6) il setup passa al lifespan dell'app.
- **Verifica**: `test_stream_api` verde; su CT 125, dopo un wipe del DB, `GET /v1/threads` risponde `200 []`.

**Fatto quando**: deploy su CT 125, nessun traceback di retention nei log dopo il primo ciclo dello scheduler, numero di run in `automations.db` che scende.

## Step 2 — Test affidabili (ISS-04, ISS-05, ISS-07)

> **Stato al 2026-10-26** — Step 2 completato (A2 `b20e63b`, A3 `0021414` + `16eae3a`). Suite ermetica: **234 test in ~4 s in locale, ~9 s su CT 125, tutti verdi**. Test in `backend/tests/`; `conftest.py` blocca la rete verso host non locali per i test non `live`. Test `live` (esclusi di default, `-m live`): conversation_length, dynamic_tool_selection, sandbox Firecracker, classificazione LLM del router.

### 2.1 Ambiente
- Ricreare `backend/.venv` con Python 3.12 (`uv venv -p 3.12` o `python3.12 -m venv`), installare `requirements.txt` più un nuovo `requirements-dev.txt` (`pytest`, `pytest-timeout`, `ruff`).
- Pulire `__pycache__` e `backend/memory/test_*.jsonl`.

### 2.2 Separare i test unit dai test live
- Spostare i test in `backend/tests/` con `conftest.py` condiviso.
- Configurare pytest in `pyproject.toml`: `markers = ["live: richiede LLM/MetaMCP/Letta reali"]`, `addopts = "-m 'not live' --timeout=30"`.
- Classificare i 7 file bloccati:
  - **Diventano unit con mock** dove il test verifica logica nostra: `test_rollback` (il mock di `call_tool` c'è già, manca quello dell'LLM), `test_memory_api`, `test_router_and_prefetch`, `test_automations_api` (mock del registry o dell'esecuzione dell'approvazione).
  - **Marcati `live`** dove il test misura il comportamento del modello: `test_conversation_length`, `test_dynamic_tool_selection`, `test_phase4`.
- Convertire `test_agent_verification` in test reali oppure eliminarlo.
- I test live non devono scrivere in `backend/memory/`: usare `tmp_path`.

### 2.3 Isolamento dello stato
- Una fixture `autouse` che punta tutti i path DB (`CHECKPOINT_DB_PATH`, `AUTOMATIONS_DB_PATH`, calendario, approvazioni, vector store) a `tmp_path` e resetta le cache in memoria (`guardrails._APPROVALS`, ecc.) per ogni test.
- **Risolve**: `test_guardrails::test_pending_list_and_filter`.

### 2.4 Riallineare i test con asserzioni superate
- `test_tool_safety::test_router_infrastructure_and_confirmation_queries`: decidere il comportamento atteso del router per le query infrastrutturali o di conferma. Se il router LLM sbaglia, si corregge il router; se è cambiata la specifica, si aggiorna il test. Il routing non deve dipendere da un LLM nei test unit: mock del classificatore LLM e verifica solo delle regole deterministiche.
- `test_modes_and_registries::test_code_exec_sandbox`: con la sandbox disponibile il test è `live`; altrimenti va testato il fallback, con il risultato atteso esplicito.

**Fatto quando**: `pytest` (default, senza live) termina in meno di 60 s, tutto verde, sia in locale sia con `docker exec agent-backend pytest`. `pytest -m live` resta eseguibile a mano contro CT 125.

## Step 3 — CI e lint (ISS-06, ISS-08, ISS-12) · ✅ Fatto (A4)

- `ruff check --fix .`, poi correzione manuale dei rimanenti (`B904`: `raise ... from e`; `E702`; `E402`; `F841`). Aggiungere le regole a `ruff.toml` solo dove c'è una ragione (per esempio `B008` per `Depends()`/`Query()` di FastAPI).
- Riscrivere il vecchio `backend-ci.yml` come [ci.yml](../../.github/workflows/ci.yml) e versionarlo:
  - job **backend**: Python 3.12, `ruff check` bloccante, `pytest` (unit, con timeout).
  - job **frontend**: `npm ci`, `npm run lint` (oxlint con `--deny-warnings`), `npm run build`.
- Correggere gli 8 warning oxlint: dipendenze degli hook con `useCallback` stabili, `catch` senza binding oppure con feedback all'utente.

**Fatto quando**: CI verde su `dev` dopo il push.

## Step 4 — Allineamento repository (ISS-13, ISS-14) · ✅ Fatto (A5)

- Committare le correzioni ai percorsi in `docs/`.
- Aggiornare il tracker automazioni (M9: la retention era rotta fino allo Step 1).
- Dopo gli Step 1–3 con CI verde: merge `dev` → `main` e tag `v0.9.0` come primo baseline stabile. Da lì `main` = ultimo stato verificato su CT 125.

## Checklist di verifica per ogni step

1. `ruff check .` e `pytest` in locale
2. `npm run lint && npm run build` (se tocca il frontend)
3. `git push origin dev`
4. Su CT 125: `git pull origin dev`, poi restart o rebuild come da [AGENTS.md](../../AGENTS.md)
5. `docker compose -f docker-compose.prod.yml run --rm --build backend-test` (mai `pytest` dentro `agent-backend`)
6. `curl -s http://localhost:8090/v1/health` e controllo dei log (`docker logs --since 10m agent-backend`)
7. Verifica UI sui flussi toccati
