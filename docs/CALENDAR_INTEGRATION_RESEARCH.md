# Ricerca Architetturale & Best Practice: Integrazione Calendario in Homelab-Agent

**Data:** 23 Settembre 2026  
**Autore:** Antigravity AI  
**Destinatari:** Homelab Engineering & Product  
**Stato:** Documento di Ricerca & Studio di Fattibilità (Fase 0 — Nessuna modifica al codice)

---

## 1. Executive Summary

L'introduzione della funzionalità **Calendario** in `homelab-agent` trasforma l'assistente da un agente reattivo basato su chat ad un orchestratore personale proattivo, capace di operare lungo l'asse temporale.
Il sistema deve soddisfare quattro requisiti fondamentali:
1. **Interfaccia Utente (UI) Nativa e Gestione Manuale:** Una vista dedicata nel frontend per la visualizzazione (Mese, Settimana, Giorno/Agenda) e la gestione manuale completa degli eventi (creazione, modifica, cancellazione, filtri).
2. **Accessibilità Completa per Agent e Automazioni:** Strumenti dedicati sia in lettura (`read`) che in scrittura (`write`) accessibili sia dall'Agent in ReAct loop sia dai workflow automatici deterministici e agentici di *Automations & Loops v2*.
3. **Sicurezza e Guardrail Umani (HITL):** Separazione netta dei permessi, deduplicazione intelligente per evitare spam di eventi, e barriere di approvazione interattive per modifiche distruttive o cancellazioni di massa.
4. **Sincronizzazione Multi-Provider (Google Calendar, Nextcloud, CalDAV, ICS):** Architettura *local-first* basata su database locale SQLite con sincronizzazione trasparente a due vie (bidirezionale) con i principali servizi di calendario (Google Calendar, Nextcloud, Apple iCloud, Radicale) e feed iCal/ICS.

Questo documento sintetizza le **best practice SOTA** (State Of The Art), analizza in profondità la referenza implementativa di **Odysseus** (presente nel nostro workspace), esamina l'attuale architettura di `homelab-agent` e propone un piano architetturale completo, arricchendo e potenziando le proposte fornite dall'utente.

---

## 2. Analisi Dettagliata della Reference: L'Implementazione in Odysseus

Nel workspace di progetto è presente la codebase di **Odysseus** (`/home/deggio/Desktop/coding/progetti/homelab/odysseus`), un sistema di assistente personale altamente avanzato. Dall'analisi del codice sorgente di Odysseus emergono pattern di eccellenza e lezioni operative fondamentali per l'integrazione del calendario:

### 2.1 Architettura Dati e Modello a Oggetti
In Odysseus (`core/database.py`, `routes/calendar_routes.py`):
- **Tabelle dedicate SQLite:**
  - `calendars`: ID univoco, nome, colore, `source` (`"local"`, `"caldav"`), `caldav_base_url`, `owner`.
  - `calendar_events`: `uid` (stringa RFC VEVENT), `calendar_id`, `summary`, `description`, `location`, `dtstart`, `dtend`, `all_day` (booleano), `is_utc` (booleano), `rrule` (ricorrenze standard iCal), `event_type` (categoria/tag), `importance` (`"low"`, `"normal"`, `"high"`, `"critical"`), `caldav_sync_pending` (`"create"`, `"update"`, `None`), `remote_href`, `remote_etag`.
  - `calendar_deleted_events`: Tombstone table per tracciare le cancellazioni avvenute in locale che devono essere propagate al server remoto CalDAV (`_record_caldav_delete_tombstone`).
- **Filosofia Local-First:** Tutte le query della UI e dell'Agent interrogano SQLite in modo istantaneo (<2ms). La sincronizzazione di rete avviene in background via threadpool asincrono (`asyncio.to_thread`), garantendo che la UI e l'API non blocchino mai l'event loop di FastAPI.

### 2.2 Il Tool Agent: `do_manage_calendar` (`src/tools/calendar.py`)
Il tool per l'agente espone azioni granulari (`list_events`, `create_event`, `update_event`, `delete_event`, `list_calendars`). Odysseus ha risolto problemi tipici dei modelli LLM con pattern di grande robustezza:
1. **Normalizzazione e Tolleranza Parametri (Aliasing):**
   - I modelli LLM spesso scambiano trattini con underscore (`list-events` vs `list_events`), oppure usano verbi brevi (`create` al posto di `create_event`).
   - I campi orari vengono normalizzati: `dtstart`, `start`, `start_time`, `when` vengono tutti mappati correttamente.
   - Supporto a durate espresse in linguaggio naturale: `"duration": "1h30m"`, `"30m"`, `"90min"`.
2. **Supporto al Batching Automatico:**
   - Alcuni modelli (es. DeepSeek, Claude o GPT) a fronte di prompt complessi restituiscono `{"events": [{...}, {...}]}` invece di invocare il tool una sola volta per evento. Odysseus intercetta questo formato ed esegue un loop interno di creazione, aggregando i risultati e restituendo un consuntivo dettagliato (`created_count`, `failed_count`).
3. **Deduplicazione Intelligente (Dedup):**
   - Se un evento con lo stesso titolo (case-insensitive) e lo stesso orario di inizio esiste già e non è cancellato, il tool non crea un duplicato, ma restituisce l'UID esistente con flag `duplicate: true`. Questo evita che l'agente o un'automazione che analizza più email relative alla stessa riunione crei eventi replicati.
4. **Clickable Markdown Anchors:**
   - Alla creazione di un evento, la risposta dell'agente include un'ancora Markdown come `[Riunione](#event-<uid>)` che nella UI apre direttamente il calendario sul giorno e sull'evento specifico.

### 2.3 Sincronizzazione Bidirezionale CalDAV (`caldav_sync.py` & `caldav_writeback.py`)
- **Libreria standard:** Uso di `python-caldav` e `icalendar`.
- **Pull Window:** Finestra temporale di sincronizzazione ottimizzata: 90 giorni nel passato e 365 giorni nel futuro (`_LOOKBACK_DAYS = 90`, `_LOOKAHEAD_DAYS = 365`). Questo evita di scaricare gigabyte di storico inutile mantenendo il REPORT XML leggero.
- **Sicurezza di Rete & Protezione SSRF:** Odysseus blocca esplicitamente indirizzi loopback, privati o di metadati cloud (`metadata.google.internal`) e disabilita i redirect HTTP automatici (`max_redirects = 0`) per prevenire SSRF via 3xx redirect verso host interni.
- **Scrittura a Due Vie (Write-Back):**
  - Quando un evento locale su calendario CalDAV viene creato/modificato/cancellato, viene marcato con `caldav_sync_pending`.
  - Subito dopo il commit locale, viene invocato `_push_caldav_event_after_commit` che genera il blocco iCal RFC VCALENDAR 2.0 tramite `build_event_ical` ed esegue un `PUT` o `DELETE` remoto con gestione degli ETag.
- **Supporto Google CalDAV nativo:**
  - Odysseus gestisce le specificità degli endpoint Google CalDAV (`https://apidata.googleusercontent.com/caldav/v2/<id>/user` vs `/events`) con mapping automatico del collection URL per evitare risposte vuote tipiche dell'endpoint Google.

### 2.4 Pipeline di Estrazione Automatica da Email (`action_extract_email_events`)
In `routes/email_pollers.py` e `src/builtin_actions.py`:
- Un'automazione periodica analizza i messaggi di posta recenti.
- **Pipeline Ibrida (LLM + Regex Heuristic Fallback):**
  - L'LLM riceve gli eventi già presenti nei successivi 60 giorni e il corpo dell'email, e produce un JSON con azioni `create`, `update` o `cancel`.
  - Fallback euristici tramite regex estraggono ed evidenziano metadati critici che l'LLM non deve assolutamente alterare:
    - *Meeting virtuali:* link Zoom, Google Meet, Microsoft Teams, Webex (assegnati automaticamente al campo `location`).
    - *Identificatori unici:* numeri di volo, codici PNR/prenotazione, codice tracciamento spedizione (Amazon, UPS, DHL, FedEx), password e pin riunione, orari check-in.
  - Salvataggio dello storico in `email_calendar_extractions` per evitare di riesaminare email già processate.

---

## 3. Best Practice & Tecniche SOTA per AI Agents e Calendari

La letteratura recente e i benchmark di settore (LangChain, AutoGen, CrewAI, protocollo MCP) evidenziano principi essenziali per rendere affidabile un agente che interagisce con un calendario:

### 3.1 Disaccoppiamento Granulare dei Tool (No "God-Tools")
- **Antipattern:** Creare un unico mega-tool `manage_calendar(json_str)` che accetta 15 parametri opzionali. I modelli si confondono facilmente tra update, filtri e cancellazioni.
- **SOTA Pattern:** Separare i tool in funzioni atomiche con firme chiare e rigide:
  1. `calendar_list_events(start_date, end_date, calendar_id?, query?)`
  2. `calendar_get_event(event_id)`
  3. `calendar_create_event(summary, start_time, end_time?, duration?, location?, description?, category?)`
  4. `calendar_update_event(event_id, ...)`
  5. `calendar_delete_event(event_id)`
  6. `calendar_check_availability(start_date, end_date, duration_minutes?)` -> strumento essenziale per permettere all'agente di negoziare o trovare slot liberi senza dover esaminare manualmente centinaia di righe di impegni privati.

### 3.2 Gestione Deterministica del Tempo & Timezone
- **Regola Fondamentale:** **Mai far calcolare all'LLM i fusi orari, l'ora legale (DST) o la matematica temporale.** L'LLM soffre di frequenti allucinazioni aritmetiche su date e giorni della settimana.
- **Iniezione del Contesto Temporale Dinamico:** Nel system prompt dell'agente deve essere sempre presente l'orario e il giorno corrente di riferimento:
  `Current Local Time: 2026-09-23T15:47:26+02:00 (Wednesday, Europe/Rome)`.
- **Parsing Deterministico sul Backend:**
  - Il backend deve accettare formati ISO-8601 standard (`2026-09-24T15:00:00+02:00` o UTC con `Z`).
  - Per espressioni in linguaggio naturale fornite dall'utente ("domani alle 15:00", "prossimo venerdì mattina"), il backend si appoggia a librerie deterministiche (es. `dateutil.parser`, `parsedatetime`) ancorate rigidamente al fuso orario configurato nell'istanza.
  - Tutti i timestamp a database sono memorizzati con indicazione esplicita UTC o con offset IANA (`Europe/Rome`).

### 3.3 Gestione delle Notifiche e dei Promemoria
- Gli eventi possono definire `reminders` (es. 10 minuti, 1 ora prima).
- Nelle architetture per homelab, l'agente può notificare l'utente tramite molteplici canali:
  - Notifica a schermo nella web app (Toast / Banner).
  - Webhook a Telegram, Discord o Home Assistant (es. far lampeggiare una luce o annunciare vocalmente l'evento tramite smart speaker).

---

## 4. Analisi dell'Architettura Attuale di `homelab-agent`

Il nostro stack `homelab-agent` è già dotato di un'infrastruttura modulare e matura, pronta per accogliere il Calendario in modo elegante:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             FRONTEND (React 19)                             │
│   [Chat Agent]   │   [Automations & Loops v2]   │   [Calendar View (NEW)]   │
└──────────────┬──────────────────┬─────────────────────────────┬─────────────┘
               │                  │                             │
               ▼                  ▼                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          FASTAPI BACKEND & REST API                         │
│   /api/chat      │   /api/automations           │   /api/calendar (NEW)     │
└──────────────┬──────────────────┬─────────────────────────────┬─────────────┘
               │                  │                             │
               ▼                  ▼                             │
┌───────────────────────────┐  ┌──────────────────────────┐     │
│   ToolRegistryManager     │  │   Automations Runner v2  │     │
│  - ModePolicy (chat/act)  │  │  - Deterministic Actions │     │
│  - Guardrails & Approvals │  │  - Agentic Tasks         │     │
│  - Audit Logging          │  │  - Template Engine       │     │
└──────────────┬────────────┘  └────────────┬─────────────┘     │
               │                            │                   │
               ▼                            ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CALENDAR REGISTRY & ENGINE                          │
│   - calendar_list_events / calendar_create_event / calendar_delete_event    │
│   - Local SQLite Storage (/data/calendar.db)                                │
│   - Sync Manager (CalDAV / Nextcloud / Google Calendar API / ICS feeds)     │
│   - IntegrationsManager (Cifratura Fernet AES credenziali terze parti)      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Registries dei Tool (`backend/registry/`)
- Esiste la classe base `BaseToolRegistry` e il manager `ToolRegistryManager`.
- Attualmente sono registrati: `MetaMCPRegistry`, `WebSearchRegistry`, `CodeExecRegistry`, `MemoryRegistry`, `VisionRegistry`, `EmailRegistry`, `AutomationRegistry`.
- Creando una nuova classe `CalendarRegistry` in `backend/registry/calendar_tool.py`:
  - I tool di calendario diventano immediatamente disponibili per l'Agent loop in modalità `act` e `plan`.
  - In `backend/mode_policy.py`, basta aggiungere `"calendar"` negli `allowed_registries`.

### 4.2 Guardrails, Sicurezza e Permission Engine (`backend/guardrails.py` & `backend/permissions.py`)
- `VIEW_TOOLS`: Contiene i tool di sola consultazione sicura (`list_containers`, `email_fetch_unread`, `web_search`, ecc.). Possiamo registrare qui:
  - `calendar_list_events`, `calendar_get_event`, `calendar_check_availability`, `calendar_list_calendars`.
  - Non richiedono approvazione umana e possono essere eseguiti istantaneamente.
- `HIGH_RISK_TOOLS` & Approvals:
  - `calendar_delete_event` e cancellazioni massive possono richiedere approvazione o confirmation card (specie se l'evento è stato creato manualmente dall'utente).
  - `calendar_create_event`: in modalità `normal` opera in modo autonomo con deduplicazione; in modalità `strict` genera una card di approvazione interattiva nella chat o un blocco `WAITING_APPROVAL` nelle automazioni.

### 4.3 Motore Automazioni v2 (`backend/automations/runner.py`)
- Il runner esegue step di tipo:
  - `StepType.DETERMINISTIC_ACTION`: Invocano qualsiasi tool registrato nel `ToolRegistryManager` passando parametri con templating (`{{steps.step_1.output.start_time}}`).
  - `StepType.AGENTIC_TASK`: Eseguono un prompt per l'agente che può utilizzare autonomamente i tool autorizzati.
- Non serve riscrivere il motore delle automazioni: una volta registrato il `CalendarRegistry`, le automazioni possono già richiamare `calendar_create_event` o `calendar_list_events` in modo deterministico oppure demandare all'agente l'estrazione e pianificazione.

### 4.4 Gestore Integrazioni e Segreti (`backend/integrations/manager.py`)
- `IntegrationManager` gestisce già credenziali cifrate con Fernet AES per `email`, `github`, `home_assistant`.
- Possiamo estenderlo con due nuovi `service_type`:
  - `caldav`: server URL, username, password, default calendar ID.
  - `google_calendar`: OAuth2 Client ID/Secret o Service Account JSON key.
- Dispone già del metodo `test_connection(integration_id)` che verifica in tempo reale la connettività e memorizza lo stato (`connected` / `error`, latenza ms, timestamp).

### 4.5 Frontend React 19 (`frontend/src/`)
- In `ThreadList.tsx` e `App.tsx` è presente il selettore viste:
  `currentView: 'chat' | 'automations'`
- Possiamo estendere `currentView` in `'chat' | 'automations' | 'calendar'`.
- Quando `currentView === 'calendar'`, l'applicazione mostrerà un componente dedicato `CalendarView` a tutto schermo, mantenendo la coerenza con il design system (vetro scuro, accenti cromatici, dark mode e responsività mobile con drawer a scomparsa).

---

## 5. Valutazione e Potenziamento delle Proposte dell'Utente

L'utente ha delineato una visione chiara:
> *"Sezione nella UI. Gestibile manualmente. Accessibile all'agent e alle automazioni (read & write). Scenari: agent che crea eventi, automazioni che creano eventi, agent/automazioni che ricavano info dal calendario (es. automazione che legge email con date/orari e le aggiunge al calendario). Integrabile con i maggiori calendari (es. Google)."*

### 5.1 Valutazione delle Proposte Iniziali
- **Valutazione:** **Eccellente e perfettamente allineata allo stato dell'arte.** Il calendario non è solo un widget grafico, ma una componente di stato centrale del contesto personale dell'utente.
- **Punto di Attenzione:** La gestione delle date relative nell'analisi di email o testi (es. "ci vediamo giovedì prossimo", "lunedì 15"). Se l'email è stata ricevuta 3 giorni fa ma l'automazione gira oggi, l'ancoraggio temporale deve riferirsi alla data di ricezione dell'email e non a `$now`.

### 5.2 Nuove Proposte & Scenari di Estensione ad Alto Valore Aggiunto

1. **Template Automazione Preconfigurato: "Email Meeting & Delivery Triage"**
   - Workflow pronto all'uso con trigger cron (es. ogni 2 ore).
   - *Step 1:* Lettura email recenti da mittenti fidati o con parole chiave di prenotazione/riunione (`email_fetch_unread`).
   - *Step 2:* Task Agentico o script con regex avanzate (stile Odysseus) per estrarre:
     - Titolo evento e orario (con rispetto del fuso orario).
     - Link virtuale (Google Meet, Zoom, Teams) inserito direttamente in `location`.
     - Dettagli sensibili nel campo `description`: codici volo, reservation number, PIN.
   - *Step 3:* Creazione deterministica dell'evento con deduplicazione automatica.
   - *Step 4:* Generazione di un report Markdown (artefatto) che riepiloga gli eventi aggiunti.

2. **Template Automazione: "Daily Morning Briefing"**
   - Trigger cron alle 07:30 del mattino.
   - *Step 1:* Interroga il calendario per gli eventi della giornata (`calendar_list_events` per `today`).
   - *Step 2:* Recupera le email non lette ad alta priorità e il meteo/stato homelab.
   - *Step 3:* L'agente genera un Markdown ben formattato salvato come Artefatto ("Briefing Giornaliero") e invia un riassunto all'utente.

3. **Strumento di Verifica Disponibilità (`calendar_check_availability`):**
   - Permette all'agente di rispondere istantaneamente a domande come: *"Quando sono libero giovedì per una call di 45 minuti?"*.
   - L'agente calcola i gap tra gli eventi esistenti nel range lavorativo configurato (es. 09:00 - 18:00) e propone 3 alternative concrete, senza inviare l'intero calendario al modello.

4. **Calendari Multipli con Categorie Cromatiche:**
   - Possibilità di gestire calendari separati:
     - 🔵 *Personale* (locale o CalDAV)
     - 🟢 *Lavoro / Studio* (Google Calendar o CalDAV)
     - 🟣 *Homelab / Manutenzioni* (eventi di backup, aggiornamenti Proxmox, rinnovi certificati)
   - L'agente può indirizzare gli eventi sul calendario appropriato.

5. **Automazioni Triggerate dal Calendario (Event-Driven / Proattive):**
   - Uno scheduler leggero che controlla gli eventi imminenti (es. 15 minuti prima di un evento con tag `#manutenzione-homelab`) e avvia un'automazione (es. snapshot Proxmox di sicurezza o avviso).

---

## 6. Proposta Architetturale per `homelab-agent`

### 6.1 Database & Modello Dati (`/data/calendar.db`)
Consigliamo un database SQLite dedicato (es. `/data/calendar.db`, configurabile in `config.py` come `CALENDAR_DB_PATH`) in modalità WAL (`PRAGMA journal_mode = WAL`), per isolare le operazioni di calendario dalle tabelle di checkpoint o da quelle dei workflow:

```sql
-- Calendari registrati (locali o sincronizzati)
CREATE TABLE IF NOT EXISTS calendars (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#3b82f6',
    source TEXT NOT NULL DEFAULT 'local', -- 'local', 'caldav', 'google', 'ics_subscription'
    sync_url TEXT,
    account_id TEXT,                      -- Riferimento a integrations.id
    is_visible INTEGER NOT NULL DEFAULT 1,
    is_read_only INTEGER NOT NULL DEFAULT 0,
    last_synced_at TEXT,
    sync_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Eventi di calendario
CREATE TABLE IF NOT EXISTS calendar_events (
    uid TEXT PRIMARY KEY,
    calendar_id TEXT NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    description TEXT DEFAULT '',
    location TEXT DEFAULT '',
    dtstart TEXT NOT NULL,                -- ISO-8601 (YYYY-MM-DDTHH:MM:SS)
    dtend TEXT NOT NULL,                  -- ISO-8601 (YYYY-MM-DDTHH:MM:SS)
    all_day INTEGER NOT NULL DEFAULT 0,
    is_utc INTEGER NOT NULL DEFAULT 1,
    rrule TEXT DEFAULT '',                -- RFC-5545 RRULE string
    recurrence_exdates TEXT DEFAULT '[]', -- JSON array di date escluse
    category TEXT DEFAULT 'general',      -- 'meeting', 'personal', 'flight', 'reminder', 'homelab'
    importance TEXT DEFAULT 'normal',     -- 'low', 'normal', 'high', 'critical'
    status TEXT DEFAULT 'confirmed',      -- 'confirmed', 'tentative', 'cancelled'
    reminder_minutes INTEGER DEFAULT NULL,
    remote_href TEXT,                     -- URL/path sul server remoto CalDAV/Google
    remote_etag TEXT,                     -- ETag per evitare sovrascritture concorrenti
    sync_pending TEXT DEFAULT NULL,       -- 'create', 'update', NULL
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Tombstones per cancellazioni remote
CREATE TABLE IF NOT EXISTS calendar_tombstones (
    uid TEXT PRIMARY KEY,
    calendar_id TEXT NOT NULL,
    remote_href TEXT,
    deleted_at TEXT NOT NULL,
    sync_attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_cal_events_dt ON calendar_events(dtstart, dtend);
CREATE INDEX IF NOT EXISTS idx_cal_events_cal ON calendar_events(calendar_id);
```

### 6.2 Tool Registry: `CalendarRegistry`
Implementazione di `backend/registry/calendar_tool.py`:
- `calendar_list_events(start_date, end_date, calendar_id, query)`
- `calendar_get_event(event_uid)`
- `calendar_create_event(summary, dtstart, dtend, duration, location, description, category, calendar_id, reminder_minutes)`
  - *Deduplicazione integrata:* controllo case-insensitive su `summary` + `dtstart`.
  - *Clickable Anchor:* restituisce `[Summary](#event-<uid>)` per interattività nella chat.
- `calendar_update_event(event_uid, ...)`
- `calendar_delete_event(event_uid)`
- `calendar_check_availability(date, duration_minutes, start_hour, end_hour)`
- `calendar_list_calendars()`

### 6.3 Driver di Integrazione & Sincronizzazione Multi-Provider
1. **CalDAV Connector (`backend/calendar_sync/caldav_driver.py`):**
   - Utilizzo di `caldav` (pure Python) e `icalendar`.
   - Compatibile con: **Google Calendar** (endpoint CalDAV), **Nextcloud**, **Apple iCloud**, **Fastmail**, **Radicale**.
   - Pull periodico (es. ogni 15 minuti tramite task APScheduler esistente) e push istantaneo on-write.
2. **Google Calendar Direct API (`backend/calendar_sync/google_driver.py`):**
   - Alternativa a CalDAV tramite Service Account o OAuth2 token gestito in `IntegrationManager`.
   - Vantaggi: generazione automatica link Google Meet, gestione inviti partecipanti via email.
3. **Sottoscrizioni iCal/ICS read-only (`backend/calendar_sync/ics_driver.py`):**
   - Importazione di calendari pubblici o privati da URL webcal/https (es. calendari sportivi, turni di lavoro, orari accademici).

### 6.4 API REST per il Frontend (`backend/api.py`)
Endpoint dedicati per la gestione manuale:
- `GET /api/calendar/calendars`: elenco calendari con colori e stato sync.
- `POST /api/calendar/calendars`: creazione o collegamento di un nuovo calendario.
- `DELETE /api/calendar/calendars/{id}`: eliminazione/scollegamento.
- `GET /api/calendar/events?start=...&end=...&calendars=...`: recupero eventi per la visualizzazione nella griglia.
- `POST /api/calendar/events`: creazione manuale di un evento.
- `PATCH /api/calendar/events/{uid}`: modifica manuale (drag-and-drop o form).
- `DELETE /api/calendar/events/{uid}`: cancellazione manuale.
- `POST /api/calendar/sync`: trigger manuale di sincronizzazione immediata ("Sync Now").

### 6.5 Interfaccia Utente Frontend (`frontend/src/components/calendar/CalendarView.tsx`)
Una UI moderna, fluida e ad alto impatto visivo in React 19:
- **Barra Superiore:**
  - Navigazione mese/settimana (Pulsanti Mese Precedente, Oggi, Successivo, Selettore data).
  - Toggle viste: **Mese** (griglia classica), **Settimana** (griglia oraria a 7 colonne), **Agenda** (elenco compatto ordinato cronologicamente).
  - Pulsante "+ Nuovo Evento" che apre il modale di creazione.
  - Indicatore di sincronizzazione con pulsante "Sync Now" e badge di stato connessione.
- **Sidebar Filtri:**
  - Checkbox per mostrare/nascondere i singoli calendari (con i relativi colori personalizzati).
  - Filtri per categoria (Meeting, Personale, Homelab, Scadenze).
  - Campo di ricerca rapida testuale.
- **Interazioni Utente:**
  - Click su una cella di giorno -> apre il modale pre-compilato con quella data.
  - Click su una pillola evento -> apre la scheda di dettaglio (con orari, note, link al meeting virtuale cliccabile, pulsante Modifica ed Elimina).
- **Mobile Friendly:**
  - Layout responsive che su smartphone compatta la vista mese in una riga di giorni con pallini colorati e sotto la lista dettagliata del giorno selezionato (stile Apple Calendar / Google Calendar mobile).

---

## 7. Tabella Comparativa Opzioni di Sincronizzazione Esterna

| Criterio | CalDAV (RFC 4791) | Google Calendar REST API | Webcal / iCal URL Feed |
| :--- | :--- | :--- | :--- |
| **Copertura Provider** | Universale (Google, Nextcloud, iCloud, Fastmail, Radicale) | Solo Google Workspace / Gmail | Qualsiasi calendario con link di esportazione .ics |
| **Direzionalità** | Bidirezionale (Lettura + Scrittura) | Bidirezionale (Lettura + Scrittura) | Sola Lettura (Read-only) |
| **Complessità Setup Utente** | Bassa/Media (URL server + Username + App Password) | Media/Alta (Richiede Cloud Console OAuth2 o Service Account) | Minima (Basta incollare l'URL del feed) |
| **Latenza di Scrittura** | Immediata (Push VEVENT via HTTP PUT) | Immediata (REST API JSON) | Non applicabile |
| **Funzionalità Avanzate** | Standard iCalendar (RRULE, VEVENT, VALARM) | Link Google Meet automatici, notifiche push native | Solo importazione eventi passivi |
| **Raccomandazione** | **Scelta Primaria per Homelab (Supporta Google + Self-Hosted)** | **Modulo Opzionale di Secondo Livello** | **Ottima come fonte dati secondaria** |

---

## 8. Piano di Implementazione a Fasi (Milestone)

Non modificando codice nella fase corrente, proponiamo la seguente roadmap strutturata per quando si deciderà di avviare lo sviluppo:

### Fase 1: Fondamenta Dati & Backend Local-First
- Creazione modulo SQLite `calendar.db` (`backend/calendar_db.py`).
- Implementazione del `CalendarRegistry` (`backend/registry/calendar_tool.py`) con i tool di base (`list`, `create`, `update`, `delete`, `check_availability`).
- Integrazione in `guardrails.py`, `mode_policy.py` e `ToolRegistryManager`.
- Test unitari completi di creazione, deduplicazione e recupero eventi.

### Fase 2: API REST & Frontend Calendar UI
- Esposizione endpoint REST in `backend/api.py`.
- Creazione della vista `CalendarView.tsx` e integrazione in `ThreadList.tsx` / `App.tsx`.
- Implementazione delle viste Mese, Settimana e Agenda con modali di creazione/modifica eventi.
- Test di responsività mobile e verifica temi dark/glass.

### Fase 3: Integrazione Automations & Loop
- Aggiornamento della documentazione e delle introspezioni per consentire alle automazioni di usare i tool di calendario sia in modalità deterministica sia agentica.
- Implementazione del template di automazione predefinito "Email to Calendar Triage" (con estrazione regex + LLM sicura).
- Implementazione del template "Daily Morning Briefing".

### Fase 4: Sincronizzazione Esterna (CalDAV & Google Calendar)
- Integrazione in `IntegrationManager` del supporto credenziali CalDAV e Google.
- Sincronizzazione periodica background (pull) e writeback reattivo su modifiche locali.
- Gestione conflitti, tombstone e gestione SSRF.

---

## 9. Conclusioni e Prossimi Passi

La proposta dell'utente è architetturalmente solida e ad alto valore d'uso. La combinazione di:
- Un'architettura **local-first** performante;
- Pattern di tolleranza e deduplicazione mutuati da **Odysseus**;
- L'aggancio nativo ai **Guardrail**, ai **Registries** e al motore **Automations v2**;
- Una UI dedicata moderna e reattiva;

rende questa funzionalità un'estensione naturale e potente per `homelab-agent`.

*Questo documento è pronto per la revisione da parte dell'utente prima di qualsiasi esecuzione di codice.*
