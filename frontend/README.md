# Home Lab Agent — Frontend

Interfaccia web moderna basata su **React 19**, **Vite**, **TypeScript** e **Tailwind CSS** per interagire con l'agente LangGraph e orchestrare l'infrastruttura Homelab.

---

## 🚀 Caratteristiche Principali

- **Chat Streaming in Tempo Reale**:
  - Consumo flussi SSE tipizzati con aggiornamento istantaneo del testo e blocco di ragionamento collassabile (*Reasoning Phase*).
  - Visualizzazione metriche in tempo reale: velocità di generazione (tokens/sec), conteggio token e latenza totale.
  - Controlli di esecuzione integrati: pulsanti **Pausa**, **Riprendi** e **Interrompi**.
  - Riconnessione fluida multi-device tramite snapshot sync (`/v1/threads/{id}/stream`).
- **Supporto Multimodale (Vision)**:
  - Drag-and-drop e selettore file per immagini (JPEG, PNG, WebP, HEIC/HEIF).
  - Compressione e ottimizzazione client-side via Canvas prima dell'invio.
  - Miniature anteprima nell'input e rendering persistente dei messaggi utente anche dopo ricaricamento o cambio thread.
- **Visualizzazione Piani & Tracce di Esecuzione**:
  - `PlanViewer`: visualizzazione dei grafi d'azione multi-step con dipendenze topologiche (`depends_on`).
  - `ExecutionTraceViewer`: log dettagliato dei tool call eseguiti, compensazioni di rollback e stato delle azioni.
- **Pannello Diagnostica & Approvazioni Human-in-the-Loop (Tier 2)**:
  - `InlineApprovalCard`: Card interattiva direttamente nel flusso di chat con 4 scelte esplicite per i tool rischiosi:
    - *No (Rifiuta)*: respinge l'esecuzione senza crash.
    - *Sì (Una volta)*: autorizzazione singola per la chiamata.
    - *Sì (In questa chat)*: autorizzazione temporanea session-scoped per il thread.
    - *Sì (Sempre per il comando)*: autorizzazione permanente globale memorizzata su SQLite.
  - `ApprovalsPanel`: monitoraggio delle richieste pendenti e risoluzione rapida anche da pannello laterale.
- **Knowledge Base Integrata**:
  - Upload e gestione documenti (.md, .txt, .pdf), conteggio chunk e ricerca semantica con punteggio di similarità.
- **Impostazioni, Temi & Gestione Permessi di Sicurezza**:
  - `SettingsModal` con 4 schede: *Generale*, *Aspetto & Temi*, *Memoria* e *Sicurezza*.
  - Tab **Sicurezza**: panoramica dei guardrail automatici (Tier 1) e tabella di gestione/revoca dei permessi accordati (Tier 2).

---

## 🛠️ Sviluppo Locale

```bash
# Installa le dipendenze
npm install

# Avvia il server di sviluppo Vite verso il backend locale
VITE_API_BASE=http://localhost:8090/v1 npm run dev
```

Il server Vite espone la porta `5173`, già ammessa nei `CORS_ORIGINS` di default del backend. Senza `VITE_API_BASE` le chiamate vanno a `/v1` sulla stessa origine, come in produzione dietro nginx.

---

## 🗂️ Struttura

- `src/api/`: un modulo per gruppo di route del backend su un client `fetch` comune (`http.ts`: API key, timeout, `ApiError` con il `detail` di FastAPI già leggibile; `sse.ts`: parser degli stream).
- `src/components/`: viste e componenti; `chat/`, `automations/` e `calendar/` divisi per area. Le viste secondarie (automazioni, calendario, knowledge, impostazioni) sono caricate on demand con `React.lazy`.
- `src/hooks/`: stato e logica delle viste (`useChat`, `useChatOptions`, `useAutomationsData`, `useRunActions`, `useCalendarData`, `useCalendarNavigation`, …).
- `src/utils/`: funzioni pure (`chatMessages`, `calendarDates`, `messageAdapter`).

### Colori e temi

- I token (`bg`, `panel`, `border`, `fg`, `accent`, `input`, …) sono variabili CSS impostate dal tema e definite in [tailwind.config.js](tailwind.config.js) con `color-mix`, quindi i modificatori di opacità (`bg-accent/15`, `border-border/60`) funzionano. Per superfici e testi usare questi token, non colori fissi come `slate-*` o esadecimali.
- I colori di stato (`emerald`, `rose`, `amber`, …) si scrivono per i temi scuri (testi 100-400, fondi 900/950, bordi 700-900): il plugin `lightThemeStatusColors` li rende leggibili sui temi chiari (`body` senza `.dark`).

---

## 📦 Compilazione & Typecheck

```bash
# Esegui typecheck e build di produzione
npm run build
```

L'output ottimizzato viene generato nella directory `dist/`.

---

## 🧪 Test

```bash
npm test
```

Vitest con jsdom; i test stanno accanto al modulo che verificano (`*.test.ts`) e usano il backend finto di `src/test/backend.ts` (router di `fetch`, risposte JSON e stream SSE). Coprono parser SSE, client HTTP, stream della chat, `useChat` e i calcoli puri. Girano anche in `make test` e in CI.

---

## 🌐 Deploy in Produzione (Docker & Nginx)

In produzione (container **CT 125** a `192.168.1.185` / `agent-dev.deggio.local`), il frontend è compilato e servito tramite container Nginx dedicato (`agent-frontend`) orchestrato con `docker-compose.prod.yml`.

### Requisiti di Configurazione Nginx (`nginx.conf`):
1. **Supporto Streaming SSE**:
   ```nginx
   location /v1/ {
       proxy_pass http://backend:8090/v1/;
       proxy_http_version 1.1;
       proxy_set_header Connection '';
       proxy_buffering off;
       proxy_cache off;
       chunked_transfer_encoding on;
   }
   ```
2. **Payload Multimodali Grandi**:
   ```nginx
   client_max_body_size 50M;
   ```
   Necessario per consentire l'upload di immagini ad alta risoluzione convertite in base64 senza incorrere in errori HTTP 413 (*Payload Too Large*).
3. **Routing SPA**:
   ```nginx
   location / {
       try_files $uri $uri/ /index.html;
   }
   ```
