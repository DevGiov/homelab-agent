# Specifiche Tecniche e Contratti Dati — Automations & Loops
**Progetto:** `homelab-agent`  
**Area:** Contratti API, Schemi Database, Pydantic Models e Specifiche Template  
**Stato:** Approvato per Implementazione  
**Data:** Settembre 2026

---

## 1. Schema Database SQLite (`automations.db`)

Il database dedicato `/data/automations.db` (o `./automations.db` in ambiente di sviluppo locale) viene configurato con:
```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 30000;
PRAGMA foreign_keys = ON;
```

### DDL delle Tabelle

```sql
-- 1. Definizioni delle automazioni
CREATE TABLE IF NOT EXISTS automation_definitions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    spec_json TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT 'user',
    source_type TEXT NOT NULL DEFAULT 'ui',
    source_reference TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_auto_enabled ON automation_definitions(enabled);

-- 2. Storico delle esecuzioni (Runs)
CREATE TABLE IF NOT EXISTS automation_runs (
    run_id TEXT PRIMARY KEY,
    automation_id TEXT NOT NULL,
    version_applied INTEGER NOT NULL,
    trigger_type TEXT NOT NULL,
    trigger_payload_json TEXT DEFAULT '{}',
    status TEXT NOT NULL,  -- pending, running, waiting_approval, completed, failed, blocked, cancelled, exhausted
    current_step_id TEXT,
    is_dry_run INTEGER NOT NULL DEFAULT 0,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    total_tokens INTEGER DEFAULT 0,
    total_duration_ms INTEGER DEFAULT 0,
    idempotency_key TEXT UNIQUE,
    associated_thread_id TEXT,
    error_message TEXT,
    FOREIGN KEY(automation_id) REFERENCES automation_definitions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_runs_auto_id ON automation_runs(automation_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON automation_runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_started ON automation_runs(started_at DESC);

-- 3. Singoli passaggi di esecuzione (Step Runs)
CREATE TABLE IF NOT EXISTS step_runs (
    step_run_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    status TEXT NOT NULL,  -- pending, running, completed, failed, skipped, waiting_approval
    attempt INTEGER NOT NULL DEFAULT 1,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    input_payload_json TEXT DEFAULT '{}',
    output_payload_json TEXT,
    error_message TEXT,
    tool_calls_json TEXT DEFAULT '[]',
    tokens_consumed INTEGER DEFAULT 0,
    approval_request_id TEXT,
    FOREIGN KEY(run_id) REFERENCES automation_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_step_run_parent ON step_runs(run_id);

-- 4. Richieste di approvazione persistenti
CREATE TABLE IF NOT EXISTS automation_approvals (
    request_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step_run_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    command_preview TEXT,
    command_prefix TEXT,
    risk_reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, approved, denied, expired
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    resolved_at DATETIME,
    resolved_by TEXT,
    resolution_action TEXT,  -- approve, deny
    FOREIGN KEY(run_id) REFERENCES automation_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_auto_appr_status ON automation_approvals(status);
CREATE INDEX IF NOT EXISTS idx_auto_appr_run ON automation_approvals(run_id);

-- 5. Registro degli artefatti prodotti
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step_run_id TEXT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,  -- report, diff_patch, json_data, test_log
    mime_type TEXT NOT NULL DEFAULT 'text/plain',
    storage_uri TEXT NOT NULL,
    checksum_sha256 TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(run_id) REFERENCES automation_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);
```

---

## 2. Definizione del Template MVP: Daily Email Briefing & Triage

Il template viene serializzato nel file `backend/automations/templates/daily_email_briefing.json`:

```json
{
  "id": "tpl-daily-email-briefing",
  "name": "Daily Email Briefing & Triage",
  "description": "Legge le email non lette ricevute dall'ultima esecuzione, le classifica per urgenza, genera un riepilogo strutturato e prepara bozze di risposta senza invio automatico.",
  "version": 1,
  "enabled": true,
  "triggers": [
    {
      "id": "trg-daily-cron",
      "type": "cron",
      "cron_expression": "30 8 * * 1-5",
      "timezone": "Europe/Rome",
      "enabled": true
    },
    {
      "id": "trg-manual",
      "type": "manual",
      "enabled": true
    }
  ],
  "workflow": {
    "initial_step_id": "fetch_emails",
    "steps": [
      {
        "step_id": "fetch_emails",
        "name": "Recupero Email Recenti",
        "type": "deterministic_action",
        "action_or_tool": "email_fetch_unread",
        "parameters": {
          "max_emails": 20,
          "unread_only": true
        },
        "timeout_seconds": 30
      },
      {
        "step_id": "triage_emails",
        "name": "Triage e Classificazione Urgenza",
        "type": "agentic_task",
        "prompt_template": "Analizza il seguente elenco di email ricevute:\n{{steps.fetch_emails.output.emails}}\n\nPer ciascuna email:\n1. Identifica il mittente e l'argomento chiave.\n2. Classifica l'urgenza (ALTA, MEDIA, BASSA).\n3. Determina se richiede una risposta da parte dell'utente.\n4. Estrai eventuali scadenze o richieste d'azione immediate.\n\nFornisci un riepilogo analitico chiaro e organizzato per priorità decrescente.",
        "timeout_seconds": 90
      },
      {
        "step_id": "prepare_drafts",
        "name": "Generazione Bozze di Risposta",
        "type": "agentic_task",
        "prompt_template": "Sulla base del triage precedente:\n{{steps.triage_emails.output}}\n\nPer ogni email con urgenza ALTA o MEDIA che richiede una risposta, genera una bozza di risposta professionale ed esaustiva, mantenendo il tono opportuno.\nUsa il tool 'email_create_draft' per salvare ciascuna bozza nell'account.\nNON tentare in nessun caso di inviare le email: salva solo le bozze.",
        "timeout_seconds": 120
      },
      {
        "step_id": "generate_report_artifact",
        "name": "Generazione Artefatto Markdown",
        "type": "deterministic_action",
        "action_or_tool": "save_briefing_artifact",
        "parameters": {
          "title": "Daily Email Briefing & Triage Report",
          "content_source": "steps.triage_emails.output"
        },
        "timeout_seconds": 15
      }
    ]
  },
  "permission_policy": {
    "execution_identity": "email-assistant-sa",
    "allowed_tools": ["email_fetch_unread", "email_create_draft", "save_briefing_artifact"],
    "allowed_registries": ["email", "code", "memory"],
    "security_mode": "normal",
    "require_approval_for": [],
    "target_scopes": {
      "allowed_containers": [],
      "allowed_repos": [],
      "allowed_recipients": []
    },
    "secrets_whitelist": ["IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"],
    "dry_run_supported": true
  },
  "budget": {
    "max_duration_seconds": 300,
    "max_llm_calls": 8,
    "max_tool_calls": 25,
    "max_tokens": 40000,
    "max_retries_per_step": 2
  },
  "notification_policy": {
    "on_success": true,
    "on_failure": true,
    "on_approval_needed": true,
    "channels": ["ui_inbox"]
  }
}
```

---

## 3. Specifiche API REST (`/v1/automations/*`)

Tutti gli endpoint risiedono sotto il prefisso `/v1/automations` e richiedono l'header di autenticazione `X-API-Key: {API_SECRET_KEY}` (o bearer token compatibile).

| Metodo | Path | Descrizione | Parametri / Body | Risposta (HTTP Status) |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/v1/automations` | Elenco di tutte le definizioni registrate | Query: `enabled: Optional[bool]` | `200 OK`: `List[AutomationSummary]` |
| `POST` | `/v1/automations` | Crea o registra una nuova definizione | Body: `AutomationDefinition` | `201 Created`: `AutomationDefinition` |
| `GET` | `/v1/automations/{id}` | Recupera i dettagli completi di un'automazione | Path: `id` | `200 OK`: `AutomationDefinition`, `404 Not Found` |
| `PUT` | `/v1/automations/{id}` | Aggiorna spec, abilitazione o trigger | Path: `id`, Body: `AutomationDefinition` | `200 OK`: `AutomationDefinition` |
| `DELETE` | `/v1/automations/{id}` | Elimina l'automazione e rimuove i trigger schedulati | Path: `id` | `200 OK`: `{"deleted": true, "id": str}` |
| `POST` | `/v1/automations/{id}/run` | Avvia manualmente una run dell'automazione | Path: `id`, Query: `dry_run: bool = false`, Body: `Optional[TriggerPayload]` | `202 Accepted`: `AutomationRun` |
| `GET` | `/v1/automations/runs` | Elenco storico delle run | Query: `status: Optional[str]`, `automation_id: Optional[str]`, `limit: int = 50` | `200 OK`: `List[AutomationRunSummary]` |
| `GET` | `/v1/automations/runs/{run_id}` | Dettaglio completo di una singola run, step e artefatti | Path: `run_id` | `200 OK`: `AutomationRunDetail` |
| `POST` | `/v1/automations/runs/{run_id}/cancel` | Arresta forzatamente una run in esecuzione | Path: `run_id` | `200 OK`: `{"cancelled": true, "run_id": str}` |
| `GET` | `/v1/automations/approvals` | Inbox delle approvazioni in sospeso per le automazioni | Query: `run_id: Optional[str]` | `200 OK`: `List[ApprovalItem]` |
| `POST` | `/v1/automations/runs/{run_id}/approvals/{approval_id}/resolve` | Approva o rifiuta un'azione privilegiata riprendendo la run | Path: `run_id`, `approval_id`, Body: `ResolveApprovalRequest` | `200 OK`: `{"status": "approved"\|"denied", "resumed": bool}` |
| `GET` | `/v1/automations/templates` | Elenco dei template predefiniti disponibili | Nessuno | `200 OK`: `List[AutomationTemplate]` |
| `GET` | `/v1/automations/artifacts/{artifact_id}/download` | Download del file artefatto generato | Path: `artifact_id` | `200 OK`: File stream / `FileResponse` |

---

## 4. Specifiche del Frontend UI

### 1. Routing e Navigazione in `App.tsx`
Nel componente radice `App.tsx`, il layout presenta un selettore di vista nella testata/drawer:
- `currentView === 'chat'`: visualizza `ThreadList`, `Chat`, `ToolLog`.
- `currentView === 'automations'`: visualizza `AutomationsView`.

### 2. Struttura del Componente `AutomationsView.tsx`
Tab bar orizzontale in stile glassmorphism:
1. **Automations**: Tabella/Griglia delle automazioni registrate:
   - Nome, descrizione, badge tipo trigger (Cron `08:30`, Manuale, Webhook).
   - Toggle switch attivo/disattivo (richiama `PUT /v1/automations/{id}`).
   - Pulsanti: *Run Now* (avvio immediato), *Dry Run* (anteprima sicura), *Modifica*, *Visualizza Storico*.
2. **Run History**: Elenco cronologico di tutte le esecuzioni:
   - Badge stato colorato: verde (`completed`), ambra (`waiting_approval`), rosso (`failed`), blu (`running`).
   - Durata, token totali consumati, trigger scatenante, orario avvio.
   - Click sulla riga apre il `RunInspectorModal`.
3. **Approvals Inbox**: Visualizzazione compatta delle run bloccate su `WAITING_APPROVAL`:
   - Scheda di allerta con preview del comando shell o azione API.
   - Motivazione del rischio rilevata da guardrail.
   - Pulsanti di azione rapida: **Approve (Resume)**, **Deny (Abort)**.
4. **Templates**: Galleria con card descrittive per l'avvio rapido:
   - *Daily Email Briefing & Triage*
   - *Proxmox Storage & VM Health Checker*
   - *Homelab Backup Verifier*
   - Pulsante *Crea da Template* che apre il form pre-compilato.

### 3. Struttura del Componente `RunInspectorModal.tsx`
Modal con animazione fade-in e backdrop blur:
- **Intestazione**: Nome automazione, ID run, timestamp e badge di stato in tempo reale.
- **Step Timeline**: Sequenza verticale di tutti gli step definiti:
  - Icona di stato (check verde, spinner rotante, punto esclamativo rosso).
  - Nome step, tipo (`deterministic` vs `agentic`), durata e consumi token.
  - Sezione espandibile con i log dei tool chiamati (con parametri e output formattato).
- **Tab Artefatti**: Se la run ha prodotto artefatti (es. report markdown del briefing), questi vengono renderizzati con formattazione markdown completa e possibilità di download.
