# Homelab Agent — Report & Roadmap (2026-08-22)

## 1. Stato attuale

### Backend (`homelab-agent/backend`)
- **Stack**: FastAPI + LangGraph (StateGraph con `SqliteSaver`), loop ReAct custom, client MetaMCP custom (SSE + JSON-RPC, fallback REST), memoria ibrida (Letta remoto + JSONL locale + SQLite), LLM via llama.cpp OpenAI-compatible.
- **Endpoint**: `/v1/health`, `/v1/chat|ask|act|plan|invoke`, `/v1/invoke_stream` (SSE), CRUD `/v1/threads`.
- **Mode routing**: `router.py` classifica input in chat/ask/act/plan (regole + fallback LLM); `mode_policy.py` definisce budget tool/reasoning per mode.
- **Tool calling**: catalogo dinamico da MetaMCP (cache 5 min), selezione schema-guidata (`ToolSelection`), registries: metamcp / web / code.
- **Test**: 6 suite presenti (tool selection, modes, phase4, rollback, verification, conversation length).

### Frontend (`homelab-agent/frontend`)
- React/Vite/TS. Thread list, streaming SSE live (reasoning + content), ReasoningBlock, PlanViewer, ExecutionTraceViewer, ToolLog, MarkdownRenderer (react-markdown + remark-gfm).
- **Mancanze**: no syntax highlighting, no WebSocket, nessuna gestione multi-user/auth UI.

### ProxmoxMcp
- Config Pydantic solida, provisioning con step tracking + rollback parziale, IPAM su file JSON con lock, test coverage buona.
- **Criticità**: default di rete hardcoded (192.168.1.x, vmbr0, homelab.local), bootstrap all-or-nothing senza degrado graceful.

## 2. Gap principali vs reference (open-webui, odysseus)

| Area | Stato homelab-agent | Reference pattern |
|---|---|---|
| Provider LLM | Solo llama.cpp via `requests.post` | Adapter multi-provider (OpenAI/Ollama/local) normalizzati |
| Auth | API key opzionale, CORS `*`, single-user | JWT/OAuth, RBAC, multi-user, sessioni |
| Streaming | SSE custom via queue+thread | SSE/Socket.IO strutturato con eventi tipizzati |
| Memory/RAG | Letta + JSONL, `sqlite-vec` installato ma non usato, hybrid retrieval non collegato al grafo | Memory manager + KB/RAG first-class come tool |
| Tool system | Solo MetaMCP + web + code | Tool registry con access control, MCP stdio/SSE/HTTP, permission read/write |
| Persistenza | SQLite checkpoints + JSONL | DB ORM modulare, file storage, Redis per stato live |
| Osservabilità | execution trace in UI | audit log persistente, metriche, health dei provider |
| Robustezza | bootstrap fragile, nessun health-check provider esterni | fallback, retry, circuit breaker |

## 3. Piano — Fase 0: Hardening (priorità alta) ✅ IMPLEMENTATA
1. ✅ **Auth obbligatoria**: fail-fast al boot se `API_SECRET_KEY` manca (bypass con `ALLOW_INSECURE=1`). CORS ristretto a `CORS_ORIGINS` da `.env`.
2. ✅ **Rate limiting** con slowapi (`RATE_LIMIT`, default 30/min) su chat/ask/act/plan/invoke/invoke_stream.
3. ✅ **Guardrail host-level**: `guardrails.py` classifica i tool (safe/write/risky), blocca comandi shell pericolosi (rm -rf /, mkfs, dd, fork bomb...) e richiede `"confirm": true` per tool rischiosi.
4. ✅ **Audit log persistente**: tabella `audit_log` in SQLite + endpoint `GET /v1/audit`; ogni tool call registra thread, mode, args, risultato, durata.
5. ✅ **Config**: `config.py` migrato a Pydantic Settings; tutte le costanti mantenute per retrocompatibilità.

> Nota: il guardrail "confirm" è lato agent — l'LLM deve includere `confirm: true`. Il gate di conferma utente via UI è previsto in Fase 3.2/4.2.

## 4. Piano — Fase 1: Architettura backend (1.1–1.4 ✅, 1.5 differita)
1. ✅ **Provider abstraction**: `providers.py` con `OpenAICompatProvider` (llama.cpp/vLLM/LM Studio) e `OllamaProvider`; `_call_llm` delega al provider; estrazione `<think>` unificata; supporto `OLLAMA_URL` opzionale in config.
2. ✅ **SDK MCP ufficiale**: `mcp_sdk_client.py` (ClientSession + sse_client, sessione persistente, retry con reset); `MetaMCPRegistry` usa l'SDK con fallback automatico al client legacy.
3. ⏳ **Refactor streaming async**: differito — la coda+thread attuale funziona; eventi già tipizzati (`reasoning|content|final|error`). Da migrare ad async generator in Fase 4 insieme al frontend.
4. ✅ **Health checks**: `GET /v1/status` pinga in parallelo llama.cpp, MetaMCP e Letta + health dei provider; ritorna `ok`/`degraded`.
5. ⏳ **Struttura a pacchetti**: differita per non rompere i deployment esistenti (CT 112); da fare in una release dedicata con aggiornamento systemd.

## 5. Piano — Fase 2: Memory & RAG ✅ IMPLEMENTATA
1. ✅ **Vector store attivo**: `vector_store.py` con sqlite-vec (distance_metric=cosine) + embeddings locali fastembed (`paraphrase-multilingual-MiniLM-L12-v2`, 384 dim, ONNX, no torch). Recall semantico cross-thread nel `retrieve_memory_node` (soglia score > 0.35); indicizzazione automatica dei fatti salienti in `respond_node`.
2. ✅ **Letta hybrid recall**: nuovo registry `memory` con tool `recall_memory` (BM25 + dense + RRF via `search_archival_memory_hybrid`), disponibile in tutte le mode.
3. ✅ **Knowledge base**: `knowledge_base.py` (chunking con overlap, supporto .md/.txt/.pdf) + tool `knowledge_search` + endpoint REST: `GET/POST /v1/kb/documents`, `DELETE /v1/kb/documents/{filename}`, `GET /v1/kb/search`.
4. ✅ **Compattazione conversazione**: budget token stimati (~4 char/token) con finestra recente adattiva e summary incrementale.

> Nota: llama.cpp su .159 non ha `--embeddings` attivo (501 su /v1/embeddings): per questo si usa fastembed locale. Se in futuro abiliti `--embeddings` con un modello GGUF di embedding, basta sostituire `_get_embedder()` in vector_store.py.

## 6. Piano — Fase 3: Tool system evoluto ✅ IMPLEMENTATA
1. ✅ **Metadata tool registry**: `get_tool_metadata()` in guardrails.py — rischio (safe/write/risky), categoria (`proxmox.read`, `host.exec.dangerous`, `dns.write`...), read_only, requires_approval, reversible. Catalogo arricchito automaticamente in `tool_catalog.py`.
2. ✅ **Approval workflow**: i tool rischiosi non bloccano più ma creano una `ApprovalRequest` (TTL 5 min). L'agent loop si interrompe segnalando la pending; endpoint REST: `GET /v1/approvals`, `POST /v1/approvals/{id}/approve` (esegue il tool), `POST /v1/approvals/{id}/deny`. Il vecchio meccanismo `"confirm": true` resta come shortcut.
3. ✅ **Parallel tool calls**: nuovo campo `parallel_calls` nello schema `ToolSelection`; l'LLM può richiedere più tool read-only indipendenti, eseguiti via ThreadPoolExecutor (`execute_tools_parallel`). Solo tool classificati safe vengono parallelizzati.
4. ✅ **Cache/deduplicazione**: chiamate identiche a tool read-only nello stesso run riusano il risultato cached (trace marcata `cached: true`).

> Nota frontend: il pannello approvazioni UI è previsto in Fase 4.2; per ora gli approval sono gestibili via API REST.

## 7. Piano — Fase 4: Frontend ✅ IMPLEMENTATA
1. ✅ **Syntax highlighting**: `rehype-highlight` + `highlight.js` (tema github-dark) nel MarkdownRenderer; blocchi fenced con linguaggio rilevato.
2. ✅ **Pannello approvazioni**: `ApprovalsPanel` con polling 10s, badge count, expand per vedere gli argomenti JSON, bottoni Approve/Deny; integrato come card fissa in cima al tab Diagnostics del pannello destro.
3. ⏳ **Viewer memoria**: differito — il recall semantico è già visibile indirettamente nelle risposte; viewer dedicato rimandato a esigenza futura.
4. ✅ **Upload documenti KB**: `KnowledgePanel` con tab Documents/Search, upload .md/.txt (PDF via API), lista documenti con chunk count, delete, ricerca semantica inline con score percentuale.
5. ✅ **Impostazioni runtime**: `SettingsModal` accessibile dall'icona ingranaggio nella sidebar — configurazione API key salvata in localStorage e iniettata automaticamente via axios interceptor + header fetch streaming.

> Layout: il pannello destro ora ha due tab (Diagnostics | Knowledge). Le approvazioni appaiono anche quando l'agente si ferma in attesa (`approval_required` nel trace).

## 8. Piano — Fase 5: Qualità & ops ✅ IMPLEMENTATA
1. ✅ **CI**: GitHub Actions `.github/workflows/backend-ci.yml` — pip cache, ruff lint, pytest suite (guardrails, memory/RAG, API integration) con env isolate.
2. ✅ **Test integrazione**: `test_api_integration.py` — endpoint REST end-to-end con TestClient, auth 401/200, KB CRUD completo, approval flow via API, agent loop con LLM mockato (direct answer, cache dedup, approval break). `conftest.py` isola le env vars prima di ogni import applicativo.
3. ✅ **Docker compose dev**: `docker-compose.dev.yml` (backend FastAPI + frontend Vite dev server, volumi, healthcheck) + `backend/Dockerfile`.
4. ✅ **Documentazione**: README backend aggiornato con diagrammi mermaid (architettura + sequenza richiesta), tabella endpoint, sezione sicurezza e test.

### Risultati
- **35 test passano** (24 unitari guardrails/memory-RAG + 11 integrazione API)
- **Ruff**: 213 → 51 problemi dopo auto-fix (161 corretti: whitespace, import sort, unused imports); i restanti 51 sono stile preesistente non bloccante (E702, B904...)
- **Bug trovati dai test**: chunking che scartava documenti < 30 caratteri; ordine alfabetico dei test unittest che invalidava la suite KB

## 9. Piano — Fase 6: Streaming Isolation & Real-Time Controls ✅ IMPLEMENTATA
1. ✅ **Session Queue & Multi-Subscriber**: `stream_session.py` con broadcast a sottoscrittori multipli e snapshot sync istantaneo.
2. ✅ **Cross-Device Reconnect**: Endpoint `/v1/threads/{thread_id}/stream` per riagganciare stream attivi da altri dispositivi o dopo refresh.
3. ✅ **Controlli di Flusso**: Endpoint `/v1/threads/{thread_id}/control` per pausa, ripresa e stop pulito con rilascio risorse.
4. ✅ **Metriche Real-time**: Tracciamento di prompt tokens, completion tokens, tok/s, e latenza end-to-end con propagazione SSE.

## 10. Piano — Fase 7: Pre-emptive Web Search Pipeline & SSRF Protection ✅ IMPLEMENTATA
1. ✅ **Deterministic Web Prefetch**: Nodo `web_prefetch_node` nel grafo LangGraph eseguito a monte delle modalità di risposta.
2. ✅ **Multi-Provider & Ranking**: `registry/web_search_service.py` con fallback SearXNG + DuckDuckGo e relevance filtering.
3. ✅ **Hardening SSRF**: `search_security.py` con validazione DNS multi-hop per bloccare private LAN (RFC 1918), loopback, link-local e cloud metadata anche su redirect HTTP.
4. ✅ **Untrusted Evidence Isolation**: Delimitatori e sanificazione prompt injection per i dati web esterni.

## 11. Piano — Fase 8: Multimodal Vision Mode & Media Persistence ✅ IMPLEMENTATA
1. ✅ **Decodifica & Ottimizzazione Immagini**: `image_utils.py` con supporto universale a JPEG, PNG, WebP e HEIC/HEIF via `pillow-heif`.
2. ✅ **Persistenza Immagini Resiliente**: Tabella `thread_messages` con colonna `images_json` e logica di backfill da cronologia LangGraph, garantendo persistenza al refresh o cambio thread.
3. ✅ **Upload & Streaming Body Size**: Incremento `client_max_body_size 50M;` in Nginx e gestione errori HTTP 413 con fallback leggibili nel frontend.

## 12. Piano — Fase 9: Visual Query Grounding & Real-Time Market Search ✅ IMPLEMENTATA
1. ✅ **Rilevamento Intento Visivo Puro**: `is_purely_visual_request` salta la ricerca web per prompt puramente descrittivi (*"cosa vedi"*, *"descrivi l'immagine"*).
2. ✅ **Silent Micro-Pass Visivo**: `formulate_visual_search_query` estrae marca, modello ed entità dall'immagine formulando query di ricerca Google/SearXNG concise (4-7 parole).
3. ✅ **Ottimizzazione Template Jinja**: Disattivazione esplicita del thinking (`enable_thinking: False`) per `reasoning_budget=0` in `providers.py`, riducendo la latenza del grounding a ~3.5s.
4. ✅ **Istruzioni ReAct per Dati Live**: Regole 1 e 3 aggiornate in `agent_loop.py` per richiedere l'uso di `web_search` su prezzi e disponibilità di mercato in tempo reale.

## 13. Prossime Evoluzioni (Backlog)
1. **Connessione Dinamica Nuovi Server MCP**: Configurazione UI o hot-reload per registrare nuovi server MCP oltre a `ProxmoxMcp` senza riavviare il backend.
2. **Visual Memory & Graph Explorer**: Viewer dedicato per navigare entità, relazioni e fatti salvati nella memoria a lungo termine Letta / sqlite-vec.
3. **Multi-User & Ruoli**: RBAC e supporto sessioni multi-utente qualora l'accesso venga esposto all'esterno della LAN.

