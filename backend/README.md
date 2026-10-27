# Home Lab Agent - Backend

Backend LangGraph + FastAPI per l'agente AI del mio homelab.

## Architettura

```mermaid
flowchart LR
    U[Utente / Frontend React] -->|REST + SSE| API[FastAPI app/api]
    API --> SS[stream_session<br/>session queue + reconnect]
    API --> G[LangGraph app/agent/graph.py]

    subgraph Grafo
        I[intake] --> RM[retrieve_memory] --> MR[mode_router]
        MR --> WP[web_prefetch<br/>visual query grounding]
        WP --> CH[chat] & AK[ask] & AC[act] & PL[plan]
        CH & AK & AC & PL --> RS[respond] --> CM[commit_memory]
    end

    G --> AL[agent_loop ReAct]
    AL --> REG[ToolRegistryManager]

    subgraph Registries
        MM[metamcp] --> SDK[mcp/client<br/>SDK ufficiale MCP, Streamable HTTP]
        WS[web] --> SX[SearXNG / DDG + SSRF guard]
        CE[code] --> FC[Firecracker sandbox]
        ME[memory] --> LT[Letta hybrid retrieval]
        VN[vision] --> VI[inspect_image]
    end

    REG --> GR[guardrails<br/>rischio + approval workflow]
    GR --> AUD[(audit_log SQLite)]

    subgraph Persistenza
        VEC[(vector_store<br/>sqlite-vec + fastembed)]
        KB[(knowledge_base)]
        TS[(thread_store<br/>messages + images_json)]
        CP[(checkpoints LangGraph)]
    end

    AL --> LLM[llm/providers<br/>llama.cpp / Ollama]
    RM --> VEC
    RS --> VEC
```

### Flusso di una richiesta

```mermaid
sequenceDiagram
    participant U as Utente
    participant A as API
    participant L as agent_loop
    participant G as Guardrails
    participant M as MetaMCP

    U->>A: POST /v1/invoke_stream
    A->>L: run_agent_loop(mode policy)
    loop fino a max_tool_calls
        L->>L: LLM seleziona tool (schema-guided)
        L->>G: enforce_guardrails(tool, args)
        alt tool risky
            G-->>L: approval_required (request_id)
            L-->>U: trace con approval pending → loop break
        else tool safe/write
            G->>M: execute_tool + audit log
            M-->>L: risultato
        end
    end
    L-->>A: final_response + execution_trace
    A-->>U: SSE events (reasoning/content/final)
```

## Struttura

Tutto il codice applicativo sta nel pacchetto `app/` (import assoluti `app.*`). Avvio API: `python -m app`; CLI: `python -m app.cli "task" --thread alice`.

| Pacchetto | Contenuto |
| :--- | :--- |
| `app/startup.py` | Avvio unico: fail-fast di sicurezza, schemi di tutti i database (`init_databases`), registry dei tool, scheduler. Lo usano il lifespan FastAPI, la CLI e i test |
| `app/api/` | `main.py` (app FastAPI, lifespan, middleware), `deps.py` (API key, rate limit), `agent_runner.py` (esecuzione del grafo sincrona e in streaming), `schemas.py`, `routes/` con un router per dominio: `chat`, `threads`, `approvals` (approvazioni e permessi), `memory`, `kb`, `providers`, `uploads`, `system` (health, status, audit) |
| `app/agent/` | `graph.py` (costruzione del grafo LangGraph e checkpointer), `nodes/` (un modulo per nodo: `intake`, `retrieve_memory`, `routing`, `web_prefetch`, `chat`, `ask`, `act`, `plan`, `respond`, `commit_memory`), `state.py` (`AgentState`), `llm_calls.py` (chiamate LLM in streaming e output strutturato), `execution_log.py` (esecuzione dei piani come Saga: log write-ahead e rollback), `agent_loop.py` (loop ReAct con cache e chiamate parallele read-only), `mode_router.py` e `mode_policy.py` (scelta e budget della modalità), `tool_catalog.py`, `tool_schemas.py`, `stream_session.py` (sessioni SSE con pausa/ripresa/stop e riaggancio), `monitoring.py` (span e metriche) |
| `app/llm/` | `providers.py`: provider OpenAI-compatible (llama.cpp, LiteLLM) e Ollama |
| `app/security/` | `guardrails.py` (Tier 1 blocco deterministico, Tier 2 approvazione), `permissions.py` (permessi `thread`/`always`), `audit_log.py` |
| `app/memory/` | `vector_store.py` (sqlite-vec + fastembed), `knowledge_base.py`, `letta_client.py`, `thread_store.py` (cronologia, immagini, titoli), `transcript.py` (trascrizione JSONL dei thread, fallback se Letta non risponde) |
| `app/registry/` | Registry dei tool: `metamcp`, `web`, `code` (sandbox Firecracker), `memory`, `vision`, `email`, `automations`, `calendar` |
| `app/automations/` | Definizioni, run, scheduler, runner, code runner, template, loop; `db/` è il database SQLite con un modulo per aggregato (`definitions`, `runs`, `approvals`, `artifacts`, `breaker_states`, `integrations`) più `connection.py` e `schema.py` |
| `app/calendar/` | `db.py`, `router.py` (API), `sync.py` (import ICS/Google) |
| `app/mcp/` | `client.py`: client sincrono sull'SDK MCP ufficiale (Streamable HTTP), una sessione condivisa per processo con retry e reset (`get_mcp_client()`) |
| `app/integrations/` | Integrazioni di servizio per le automazioni |
| `app/core/` | `config.py` (istanza `settings` di Pydantic Settings, fail-fast sicurezza, `BACKEND_DIR`), `text_utils.py`, `image_utils.py` |
| `sdk/` | SDK pubblico per gli script delle automazioni (`@workflow`, `@step`, `AutomationContext`): resta fuori da `app/` perché lo importano gli script utente |

## Installazione

```bash
make venv   # dalla radice del repo: backend/.venv con Python 3.12 e requirements-dev.txt (richiede uv)
```

## Configurazione

`make setup` genera `backend/.env` in modo interattivo; in alternativa copia `.env.example` in `.env` e compila
i valori (riferimento completo in [.env.example](.env.example)). In Docker i dati stanno in `/data`
(`CHECKPOINT_DB_PATH=/data/checkpoints.db`, gli altri database e la memoria accanto).

## Avvio

### CLI
```bash
.venv/bin/python -m app.cli "task" --thread alice
```

### API REST
```bash
.venv/bin/python -m app
```

## Test

I test stanno in `tests/` (configurazione in `pytest.ini`). Due categorie:

- **Ermetici** (default): nessun servizio esterno. `tests/conftest.py` reindirizza tutti i dati in una
  directory temporanea e blocca le connessioni verso host non locali, quindi un servizio reale non mockato
  fa fallire il test subito. Timeout di 60 s per test.
- **`live`**: verificano il comportamento contro LLM, MetaMCP o Firecracker reali. Esclusi di default.

```bash
make venv                              # venv Python 3.12 con requirements-dev.txt
make test                              # suite ermetica
make test ARGS="-m live"               # solo test live (richiede la LAN homelab)
make test ARGS="tests/test_router_and_prefetch.py -q"

# Su CT 125: container di test isolato (nessun volume di produzione)
docker compose -f docker-compose.prod.yml run --rm --build backend-test
docker compose -f docker-compose.prod.yml run --rm backend-test -m live

# Lint
make lint
```

## Docker Compose (dev)

```bash
cd homelab-agent
docker compose -f docker-compose.dev.yml up --build
# Backend: http://localhost:8090/v1 — Frontend: http://localhost:5173
```

## Deploy con Docker (produzione)

Lo stack prod usa `docker-compose.prod.yml`: backend FastAPI + frontend compilato e servito da nginx (con proxy `/v1/` e SSE senza buffering).

```bash
# 1. Clona il repo e configura l'ambiente
cd homelab-agent
cp backend/.env.example backend/.env
# modifica backend/.env con i tuoi valori (API_SECRET_KEY, CORS_ORIGINS, URL servizi...)

# 2. Build e avvio
docker compose -f docker-compose.prod.yml up -d --build

# 3. Verifica
curl http://localhost:8090/v1/health          # {"status":"ok"}
curl http://localhost/                        # frontend UI
```

Il frontend nginx espone la porta 80 e inoltra `/v1/` al backend (nome servizio compose `backend`, porta interna 8090). Per HTTPS metti un reverse proxy davanti (es. Nginx Proxy Manager) puntando alla porta 80 del container frontend.

**Importante**: se accedi all'UI tramite un dominio proxato, aggiungi quell'origine (con schema) a `CORS_ORIGINS` nel `backend/.env`, altrimenti il browser bloccherà le chiamate API con "Disallowed CORS origin".

## Endpoint principali

| Metodo | Path | Descrizione |
|---|---|---|
| GET | `/v1/health` | Health check (pubblico) |
| GET | `/v1/status` | Health aggregato llama.cpp/MetaMCP/Letta |
| POST | `/v1/chat\|ask\|act\|plan\|invoke` | Chat sincrona per mode |
| POST | `/v1/invoke_stream` | Chat streaming SSE con supporto immagini |
| GET | `/v1/threads/{id}/stream` | Aggancio streaming live per riconnessione/multi-device |
| POST | `/v1/threads/{id}/control` | Controlli di flusso (pause, resume, stop) |
| POST | `/v1/images/upload` | Upload e validazione immagini multimodali |
| GET/DELETE | `/v1/threads[/{id}]` | Gestione thread e cronologia |
| GET | `/v1/audit` | Audit log tool call |
| GET | `/v1/approvals` | Approvazioni pending |
| POST | `/v1/approvals/{id}/approve\|deny` | Risolvi approvazione |
| GET/POST | `/v1/kb/documents` | Lista/upload documenti KB |
| DELETE | `/v1/kb/documents/{filename}` | Elimina documento |
| GET | `/v1/kb/search` | Ricerca semantica KB |

## Sicurezza

- `API_SECRET_KEY`: se impostata, tutti gli endpoint (tranne health) richiedono header `X-API-Key`. Se manca, il backend **non parte** a meno di `ALLOW_INSECURE=1`.
- Guardrail: tool rischiosi (delete/rollback/exec_*) richiedono approvazione utente; comandi shell pericolosi sono sempre bloccati.
- CORS ristretto a `CORS_ORIGINS`; rate limiting su endpoint chat (`RATE_LIMIT`, default 30/min).

curl http://localhost:8090/v1/health
