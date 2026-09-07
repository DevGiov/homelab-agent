# Homelab Agent (`homelab-agent`)

Agente AI autonomo per la gestione dell'infrastruttura Proxmox VE con orchestrazione MetaMCP, supporto LangGraph, memoria conversazionale ibrida, percezione multimodale (Vision), ricerca web preventiva con grounding visivo, selezione dinamica dei tool e motore di rollback transazionale automatico.

---

## 🚀 Caratteristiche Principali

- **Percezione Multimodale & Vision Grounding**:
  - Upload e drag-and-drop di immagini (JPEG, PNG, WebP, HEIC via `pillow-heif`).
  - Ottimizzazione automatica dei payload client-side e archiviazione resiliente SQLite (`thread_messages.images_json`) con backfill dallo stato LangGraph.
  - **Visual Query Grounding**: micro-pass visivo rapido e silenzioso per estrarre brand, modello ed entità da foto e alimentare la ricerca web preventiva per prezzi, specifiche e disponibilità in tempo reale.
- **Ricerca Web Preventiva Deterministica & Sicurezza SSRF**:
  - Prefetch prima dei nodi di risposta per arricchire il contesto con fonti fresche.
  - Protezione SSRF multi-hop (blocco di localhost, IP RFC 1918, link-local e cloud metadata).
  - Multi-provider fallback (SearXNG + DDGS) e relevance re-ranking automatico.
- **Streaming Live Resiliente & Controllo Sessioni**:
  - SSE con snapshot sync immediato e gestione multi-client/cross-device (`/v1/threads/{id}/stream`).
  - Controlli real-time di pausa, ripresa e interruzione (`/v1/threads/{id}/control`).
  - Tracciamento separato di token di reasoning, token di contenuto e metriche prestazionali (tok/s, latenza).
- **Architettura Universale a Registry Estendibili**:
  - Separazione per domini: `metamcp` (infrastruttura Proxmox), `web` (ricerca), `code` (sandbox), `memory` (RAG vettoriale e Letta), `vision` (ispezione immagini).
  - Nessuna scissione rigida: integrazione trasparente con futuri server MCP.
- **Motore di Rollback Transazionale (Saga Pattern & WAL)**:
  - Registrazione anticipata su Write-Ahead Log prima dell'esecuzione.
  - LIFO undo stack transazionale che esegue compensazioni inverse solo per gli step completati con successo.
  - Supporto a piani multi-step JSON strutturati (`depends_on`, topological sort).

---

## ⚙️ Modalità Operative (Grafo LangGraph)

1. **CHAT**: Conversazione naturale con memoria storica sliding window + summary + prefetch web contestuale (anche guidato da immagini).
2. **ASK**: Consultazione rapida e di ricerca (tool web e shell/calcolo) con recupero di dati freschi e memoria RAG.
3. **ACT**: Esecuzione dinamica di tool MCP con self-correction guidata da schema e guardrails di sicurezza.
4. **PLAN**: Generazione di piani multi-step con ordinamento topologico, estrazione ricorsiva delle variabili ed esecuzione transazionale con **rollback automatico dichiarativo e LIFO undo stack**.

---

## 🔄 Rollback Automatico Transazionale & Declarative Undo Engine

Sostituito il vecchio sistema di rollback hardcoded con un motore generale e transazionale basato sul pattern **Saga** e **Write-Ahead Logging (WAL)**:

- **Declarative Rollback Schema (`tool_catalog.py`)**:
  - Ogni tool dichiara la sua azione di compensazione inversa (es. `allocate_ip` ➔ `release_ip`, `create_lxc_from_template` ➔ `stop_container`, `add_pihole_dns_record` ➔ `delete_pihole_dns_record`, `create_npm_proxy_host` ➔ `delete_npm_proxy_host`).
  - Mappa i template degli argomenti (`rollback_args_template`) con i risultati di esecuzione effettivi (`{{vmid}}`, `{{ip}}`, `{{domain}}`).
- **Transaction Log & LIFO Undo Stack (`ExecutionLog` in `graph.py`)**:
  - Ogni step viene registrato su un registro transazionale *prima* dell'esecuzione (WAL pattern).
  - In caso di fallimento durante l'esecuzione di un piano, il sistema scorre il registro in ordine inverso (LIFO Undo Stack), eseguendo il rollback **esclusivamente per gli step completati con successo**.
- **Skipping dei Tool Non Reversibili**:
  - I tool non reversibili (es. `exec_lxc_command`, `list_containers`) vengono identificati e ignorati in sicurezza durante il rollback con warning nei log.
- **LLM-Based Rollback Planning (Fallback)**:
  - Se il rollback dichiarativo per alcuni step fallisce o se vi sono operazioni non reversibili, l'LLM genera un piano di rollback manuale contestuale basato sullo stato dell'infrastruttura.

---

## 🛡️ Sicurezza & Guardrail a Due Livelli (Tool Safety Engine)

1. **Tier 1 — Blocco Deterministico ed Immediato (Nessun bypass LLM)**:
   - Analisi sintattica preventiva di ogni comando shell su host (`exec_host_command`) e container (`exec_lxc_command`).
   - Blocco categorico di comandi malevoli o distruttivi senza emissione di conferme:
     - Rimozione ricorsiva su root, home o directory di sistema (`rm -rf /`, `rm -rf /etc`, `~`, `/var`, `/usr`, ecc.).
     - Formattazione di partizioni e cancellazione firme filesystem (`mkfs`, `wipefs`).
     - Scrittura grezza su dischi a blocchi (`dd of=/dev/sd*`, redirection `> /dev/nvme*`).
     - Fork bomb e denial of service (`:(){ :|:& };:`, loop fork perl/python).
     - Manomissione credenziali o firewall (`/etc/shadow`, `iptables -F`, `ufw disable`).
     - Esecuzione remota diretta pipe-to-shell (`curl ... | sh`, `base64 -d | sh`).
   - Il modello **non può scavalcare i guardrail** allucinando flag `confirm=true` nei payload JSON.

2. **Tier 2 — Human-in-the-Loop Interattivo & Policy Engine (`permissions.py`)**:
   - I tool rischiosi (`stop_container`, `rollback`, `delete_*`, `release_ip`, `exec_host_command` o comandi shell di modifica) richiedono conferma esplicita dell'utente tramite `InlineApprovalCard` integrata nella chat.
   - 4 scelte di risposta chiare e differenziate:
     1. **No (Rifiuta)**: annulla l'azione informando l'agente senza causare crash.
     2. **Sì (Una volta)**: autorizza la singola chiamata contestuale.
     3. **Sì (In questa chat per <cmd>)**: autorizza il comando per tutti i turni del thread corrente (session-scoped).
     4. **Sì (Sempre per <cmd>)**: memorizza l'autorizzazione permanente su tabella SQLite `tool_permissions` con granularità per prefisso comando (cross-session).
   - Tab **Sicurezza** nelle Impostazioni UI per il controllo delle regole e la revoca immediata di permessi permanenti o di sessione.

---

## 🛠️ Selezione Dinamica dei Tool via LLM

- **Catalogo Dinamico con Cache TTL 5m (`tool_catalog.py`)**: Recupera la lista dei tool dal protocollo SSE/MCP o OpenAPI.
- **Structured Output & Schema Validation (`tool_schemas.py`)**: Modello Pydantic `ToolSelection` con validazione `jsonschema`.
- **Loop di Self-Correction (`act_graph_node`)**: Iniezione degli errori di validazione per la ri-generazione guidata (fino a 2 retries).
- **Parallel Tool Calls**: Esecuzione parallela concorrente (`execute_tools_parallel`) per letture multiple indipendenti.

---

## 🧠 Architettura della Memoria Conversazionale Ibrida

- **Tier 1 — In-Context Memory**: Sliding window adattiva degli ultimi messaggi con summary incrementale via LLM per conversazioni lunghe.
- **Tier 2 — Semantic Vector Memory**: `vector_store.py` con `sqlite-vec` (distanza coseno) e modelli di embedding multilingua leggeri via ONNX (`fastembed`).
- **Tier 3 — Hybrid Knowledge Base & Letta**: Ricerca ibrida dense + BM25 con Reciprocal Rank Fusion (RRF) e knowledge base documentale (.md, .txt, .pdf).
- **Tier 4 — Cross-Session SQLite Persistence**: `thread_store.py` e `checkpoints.db` con persistenza completa di messaggi, immagini base64, titoli e metadati.

---

## 🌐 Deploy & Infrastruttura di Produzione

Lo stack di sviluppo e produzione attivo è deployato all'interno del container Proxmox **CT 125** (`192.168.1.185` / `agent-dev.deggio.local`):

- **Backend**: FastAPI su porta interna `8090` (`agent-backend`).
- **Frontend**: Single Page Application React servita da Nginx su porta `80` (`agent-frontend`), con proxying `/v1/` e disattivazione del buffering SSE (`proxy_buffering off;`).
- **Nginx Upload Limit**: `client_max_body_size 50M;` per gestire l'upload di immagini ad alta risoluzione senza errori HTTP 413.
- **Orchestrazione**: `docker-compose.prod.yml` con volumi persistenti per database SQLite, upload e modelli locali.

Comando di aggiornamento rapido via MCP da workstation:
```python
exec_lxc_command(
    vmid=125,
    command="cd /opt/homelab-agent && git pull origin dev && docker compose -f docker-compose.prod.yml restart backend"
)
```
