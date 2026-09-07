# Home Lab Agent — Frontend

Interfaccia web moderna basata su **React 18**, **Vite**, **TypeScript** e **Tailwind CSS** per interagire con l'agente LangGraph e orchestrare l'infrastruttura Homelab.

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
- **Pannello Diagnostica & Approvazioni**:
  - Gestione del workflow di approvazione per operazioni critiche o non reversibili (es. rimozione risorse, rollback, comandi shell).
- **Knowledge Base Integrata**:
  - Upload e gestione documenti (.md, .txt, .pdf), conteggio chunk e ricerca semantica con punteggio di similarità.
- **Impostazioni & Sicurezza**:
  - `SettingsModal` per configurazione sicura di `API_SECRET_KEY` salvata in `localStorage` e iniettata automaticamente nelle richieste REST e SSE.

---

## 🛠️ Sviluppo Locale

```bash
# Installa le dipendenze
npm install

# Avvia il server di sviluppo Vite
npm run dev
```

Il server Vite espone la porta `5173` e inoltra automaticamente le chiamate `/v1` al backend locale su `http://localhost:8090`.

---

## 📦 Compilazione & Typecheck

```bash
# Esegui typecheck e build di produzione
npm run build
```

L'output ottimizzato viene generato nella directory `dist/`.

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
