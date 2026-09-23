# Implementation Walkthrough & Progress Tracker — Calendar Integration

**Progetto:** `homelab-agent`  
**Data Creazione:** 24 Settembre 2026  
**Stato Complessivo:** 🟡 IN CORSO — ~45% Completato (Backend avviato con bug di allineamento, Frontend da avviare)  
**Documento di Riferimento:** [`docs/CALENDAR_INTEGRATION_RESEARCH.md`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/docs/CALENDAR_INTEGRATION_RESEARCH.md)  
**Reference Codebase:** [`odysseus`](file:///home/deggio/Desktop/coding/progetti/homelab/odysseus) (`routes/calendar_routes.py`, `src/tools/calendar.py`)

---

## 1. Stato Avanzamento Generale per Milestone

```
[█████████░░░░░░░░░░░] 45% Completato (5 / 6 Componenti Backend avviati, Frontend 0%)
```

| Milestone | Descrizione | Stato | File Coinvolti | Note / Bloccanti |
| :--- | :--- | :---: | :--- | :--- |
| **M0** | Database Dedicato SQLite & Schema | 🟡 90% | [`calendar_db.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/calendar_db.py), [`config.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/config.py) | Schema e test base funzionanti; allineamento DDL pulito (no legacy shims) con colonne `source_type`/`source_id`. |
| **M1** | Tool Registry & Integrazione Agent Loop | 🟢 100% | [`calendar_tool.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/registry/calendar_tool.py), [`guardrails.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/guardrails.py), [`mode_policy.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/mode_policy.py) | Completo: durate naturali, smart dedup, batching, ancore markdown, registrato in ask/act/plan. |
| **M2** | FastAPI REST API Router | 🟡 85% | [`calendar_router.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/calendar_router.py), [`api.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/api.py) | Endpoint definiti e router montato in `api.py`. Chiamate dirette alle nuove API pulite di `calendar_db`. |
| **M3** | Sync Engine Multi-Provider | 🟡 60% | [`calendar_sync.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/calendar_sync.py), [`integrations/manager.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/integrations/manager.py) | Parser iCal RFC 5545 e fetch feed funzionanti; manca CalDAV nativo (writeback a due vie). |
| **M4** | Integrazione Automations & Loops v2 | 🟡 75% | [`automations/runner.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/automations/runner.py), [`templates/email_to_calendar_sync.json`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/automations/templates/email_to_calendar_sync.json) | Template pronto, runner esteso. ⚠️ **Bloccato da SyntaxError alla riga 735 di `runner.py`**. |
| **M5** | Frontend React 19 Calendar UI | 🔴 0% | `frontend/src/components/calendar/CalendarView.tsx`, `App.tsx`, `ThreadList.tsx` | Componenti UI da implementare con Dark Glassmorphism, viste Mese/Settimana/Agenda. |
| **M6** | Deploy Live & Test Browser (CT 125) | 🔴 0% | Proxmox CT 125 (`agent-dev.deggio.local`) | Git push dev, docker restart/build, API test e test visivo con `browser_subagent`. |

---

## 2. Walkthrough Dettagliato dei File Implementati

### 2.1 Database & Persistenza Dati
* **File:** [`backend/calendar_db.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/calendar_db.py) (584 righe) e [`backend/config.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/config.py)
* **Cosa è stato realizzato:**
  - Configurato `CALENDAR_DB_PATH` in Pydantic Settings con percorso default `/data/calendar.db` (o fallback locale `backend/calendar.db`).
  - Connessione SQLite isolata con `PRAGMA journal_mode = WAL`, `PRAGMA synchronous = NORMAL`, busy timeout 30s.
  - Creazione tabelle:
    1. `calendars`: ID, nome, colore, sorgente (`local`, `caldav`, `google`), `sync_url`, `is_visible`, `is_read_only`.
    2. `calendar_events`: UID, `calendar_id`, `summary`, `description`, `location`, `dtstart`, `dtend`, `all_day`, `is_utc`, `rrule`, `category`, `importance`, `status`, `reminder_minutes`, `sync_pending`.
    3. `calendar_tombstones`: per tracciare cancellazioni remote differite.
  - Seed iniziale di due calendari: `"Personale"` (`#3b82f6`) e `"Homelab"` (`#8b5cf6`).
  - Funzioni:
    - `list_calendars()`, `get_calendar()`, `save_calendar()`, `delete_calendar()`
    - `list_events()` con filtri su range temporale (`dtend >= start_dt` e `dtstart <= end_dt`), ID calendario, categoria e ricerca full-text LIKE.
    - `get_event(uid)`
    - `save_event(event_dict)` con gestione automatica insert/update e calcolo `sync_pending`.
    - `delete_event(uid)` con creazione automatica tombstone se sorgente remota.
    - `find_existing_event(summary, dtstart, calendar_id)` per deduplicazione case-insensitive e prefisso data.
    - `find_free_slots(target_date, duration_minutes, start_hour, end_hour)`: algoritmo deterministico per calcolare slot liberi (gap finder) fondendo intervalli occupati sovrapposti.
* **Test Associato:** [`backend/test_calendar_db.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/test_calendar_db.py) — **4/4 test superati**.

---

### 2.2 Agent Tool Registry
* **File:** [`backend/registry/calendar_tool.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/registry/calendar_tool.py) (515 righe)
* **Cosa è stato realizzato:**
  - Registrato `CalendarRegistry` come sottoclasse di `BaseToolRegistry`.
  - Tool esposti al modello LLM:
    1. `calendar_list_calendars`: lista calendari configurati.
    2. `calendar_list_events`: ricerca eventi in un intervallo con filtri per categoria/testo.
    3. `calendar_get_event`: dettaglio evento singolo per UID.
    4. `calendar_create_event`: supporta creazione singola o batch `events: [...]`. Implementa normalizzazione date, calcolo durate espresse in linguaggio naturale (`"30m"`, `"1h"`, `"1h30m"`), smart deduplication preventiva e restituzione di ancore Markdown cliccabili `[Titolo](#event-<uid>)`.
    5. `calendar_update_event`: modifica evento esistente.
    6. `calendar_delete_event`: cancellazione evento.
    7. `calendar_check_availability`: ricerca slot orari liberi per una specifica giornata e range lavorativo.
  - Integrazione nei Guardrails e Mode Policy:
    - [`backend/registry/manager.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/registry/manager.py): registrazione automatica all'avvio.
    - [`backend/mode_policy.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/mode_policy.py): abilitato registry `"calendar"` in modalità `ask`, `act` e `plan`.
    - [`backend/guardrails.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/guardrails.py): assegnazione categorie `calendar.read`, `calendar.write`, `calendar.destructive` e inserimento di `calendar_delete_event` in `HIGH_RISK_TOOLS`.

---

### 2.3 API REST FastAPI
* **File:** [`backend/calendar_router.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/calendar_router.py) (255 righe) e [`backend/api.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/api.py)
* **Cosa è stato realizzato:**
  - Router `/v1/calendar` protetto con autenticazione header `X-API-Key`.
  - Modelli Pydantic per validazione input: `CalendarCreateRequest`, `CalendarUpdateRequest`, `EventCreateRequest`, `EventUpdateRequest`.
  - Endpoint implementati:
    - `GET /v1/calendar/calendars` & `POST /v1/calendar/calendars`
    - `PUT /v1/calendar/calendars/{calendar_id}` & `DELETE /v1/calendar/calendars/{calendar_id}`
    - `GET /v1/calendar/events` & `GET /v1/calendar/events/upcoming`
    - `GET /v1/calendar/events/{event_id}` & `POST /v1/calendar/events`
    - `PUT /v1/calendar/events/{event_id}` & `DELETE /v1/calendar/events/{event_id}`
    - `GET /v1/calendar/availability`
    - `POST /v1/calendar/sync`
  - Inizializzazione automatica del DB in `api.py` (`init_calendar_db()` nel lifespan).

---

### 2.4 Motore di Sincronizzazione iCal
* **File:** [`backend/calendar_sync.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/calendar_sync.py) (188 righe) e [`backend/integrations/manager.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/integrations/manager.py)
* **Cosa è stato realizzato:**
  - Parser iCal/ICS nativo RFC 5545 `parse_ical_text()`: gestisce line unfolding (righe con spazio iniziale), estrazione `VEVENT`, `UID`, `SUMMARY`, `DESCRIPTION`, `LOCATION`, `DTSTART`, `DTEND`, `STATUS`, `CATEGORIES`.
  - Parser datetime iCal `_parse_ical_datetime()` con conversione a ISO-8601.
  - Sincronizzatore `fetch_and_sync_ical_feed()` con supporto a protocolli `webcal://`, `http://`, `https://` ed esecuzione di upsert nel DB locale.
  - Funzione `sync_all_external_calendars()` collegata a `IntegrationManager`.
  - Validatore di connessione `_test_calendar_connection()` in `IntegrationManager` per testare in tempo reale URL feed o server CalDAV.

---

### 2.5 Integrazione Automations & Loops v2
* **File:** [`backend/automations/models.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/automations/models.py), [`backend/automations/runner.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/automations/runner.py), [`backend/automations/templates/email_to_calendar_sync.json`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/automations/templates/email_to_calendar_sync.json)
* **Cosa è stato realizzato:**
  - Esteso `ExecutionPolicy.allowed_registries` per includere `"calendar"` come default.
  - Aggiunta la gestione dello step `StepType.CALENDAR` in `runner.py` per azioni `create`, `list`, `delete`, `update`.
  - Creato il template di automazione predefinito `"Email to Calendar Event Sync"`:
    - Trigger: cron orario (`0 * * * *`) o manuale.
    - Step 1: Recupero email non lette (`email_fetch_unread`).
    - Step 2: Estrazione agentica con LLM (`calendar_create_event` con ancoraggi markdown).
    - Step 3: Salvataggio artefatto di riepilogo sincronizzazione (`save_artifact`).

---

## 3. Discrepanze e Bug Bloccanti Attualmente Presenti nel Codice

L'ispezione approfondita del codice e dei test ha rivelato tre problemi di allineamento che bloccano l'esecuzione:

### 🔴 1. SyntaxError in `backend/automations/runner.py`
* **Posizione:** Riga 735-740.
* **Causa:** Durante l'inserimento dello step calendario, è rimasto un blocco `return {` incompleto e non chiuso prima del commento `# Step Calendario`.
* **Impatto:** Errore bloccante (`SyntaxError: '{' was never closed`). Il backend FastAPI e il modulo automazioni non possono essere importati.

### 🟡 2. Mismatch Funzioni / Nomi Metodi tra `calendar_router.py` / `calendar_sync.py` e `calendar_db.py`
In `calendar_db.py` sono state usate firme generiche (`save_event`, `save_calendar`), mentre i router e i sync invocano metodi specifici con nomi diversi:
1. `create_event(event_dict)` & `update_event(uid, updates)`: invocati da `calendar_router.py`, `calendar_sync.py` e `runner.py`, ma `calendar_db.py` definisce solo `save_event(event_dict)`.
2. `get_event_by_id(uid)`: invocato da router e sync, ma in `calendar_db.py` si chiama `get_event(uid)`.
3. `create_calendar(data)` & `update_calendar(cal_id, updates)`: invocati dal router, ma in `calendar_db.py` esiste solo `save_calendar(data)`.
4. `get_upcoming_events(days)`: invocato da `calendar_router.py`, ma mancante in `calendar_db.py`.
5. `check_conflict(start_time, end_time, calendar_id)`: invocato da `calendar_router.py` in `/availability`, ma non implementato in `calendar_db.py` (esiste solo `find_free_slots`).
6. `_calculate_dtend(dtstart, duration)`: invocato da `calendar_router.py`, ma implementato localmente solo in `calendar_tool.py`.

### 🟡 3. Colonne `source_type` e `source_id` Mancanti in `calendar_events`
`calendar_sync.py`, `runner.py` e il test [`test_calendar.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/test_calendar.py) memorizzano e verificano i campi `source_type` (es. `"manual"`, `"automation"`, `"sync"`) e `source_id` (run ID o feed URL). La tabella `calendar_events` non possiede queste colonne nel `CREATE TABLE`.

---

## 4. Cosa Manca per Completare l'Integrazione

### Fase A: Correzione e Chiusura Backend (Priorità 1)
- [ ] Correggere la sintassi di [`backend/automations/runner.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/automations/runner.py).
- [ ] Aggiungere colonne `source_type TEXT DEFAULT 'manual'` e `source_id TEXT DEFAULT NULL` a `calendar_events` in [`backend/calendar_db.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/calendar_db.py).
- [ ] Esporre in [`backend/calendar_db.py`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/backend/calendar_db.py) gli alias e le funzioni helper attese:
  - `create_event(data)` e `update_event(uid, data)`
  - `get_event_by_id(uid)`
  - `create_calendar(data)` e `update_calendar(cal_id, updates)`
  - `get_upcoming_events(days=7)`
  - `check_conflict(start_time, end_time, calendar_id=None)`
  - `_calculate_dtend(dtstart, duration)`
- [ ] Verificare che l'intera suite di test passi:
  - `test_calendar_db.py`
  - `test_calendar_tool.py`
  - `test_calendar.py`

### Fase B: Frontend React 19 UI (Priorità 2)
- [ ] Estendere il tipo `currentView: 'chat' | 'automations' | 'calendar'` in:
  - [`frontend/src/App.tsx`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/frontend/src/App.tsx)
  - [`frontend/src/ThreadList.tsx`](file:///home/deggio/Desktop/coding/progetti/homelab/homelab-agent/frontend/src/ThreadList.tsx)
- [ ] Aggiungere il pulsante di navigazione "Calendario" (icona `Calendar` da `lucide-react`) nel View Switcher di `ThreadList.tsx`.
- [ ] Creare `frontend/src/components/calendar/CalendarView.tsx`:
  - Barra superiore con pulsanti navigazione mese/settimana, toggle vista (**Mese**, **Settimana**, **Agenda**), pulsante "+ Nuovo Evento", indicatore sincronizzazione.
  - Sidebar filtri con checkbox calendari colorati e categorie.
  - Griglia mese reattiva con badge per ciascun evento.
  - Vista settimana con colonne orarie.
  - Vista agenda compatto ordinato cronologicamente.
  - Modale interattivo per creare/modificare/cancellare eventi.
- [ ] Intercettare il click sugli ancoraggi markdown `[Titolo](#event-<uid>)` nei messaggi di chat per switchare alla vista calendario evidenziando l'evento.

### Fase C: CalDAV Avanzato & Automazioni Extra (Priorità 3)
- [ ] Implementare worker per propagare i tombstones remoti (`calendar_tombstones`) via DELETE e push eventi con ETag su server CalDAV/Google.
- [ ] Creare il template di automazione `"Daily Morning Briefing"` (`templates/daily_morning_briefing.json`).
- [ ] Aggiungere `icalendar` e librerie sync a `requirements.txt`.
