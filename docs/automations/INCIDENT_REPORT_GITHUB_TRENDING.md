# Incident & Autopsy Report — Fallimento Creazione Automazioni Agentiche (GitHub Trending)

**Data dell'Analisi:** 21 Settembre 2026  
**Ambiente:** Homelab Proxmox CT 125 (`192.168.1.185` / `agent-dev.deggio.local`)  
**Modulo Coinvolto:** `backend/automations/` e `backend/registry/automations_tool.py`  
**Oggetto:** Autopsia approfondita dei tentativi di generazione autonoma dell'automazione *'GitHub Trending Daily Report'* da parte dell'agente LLM.

---

## 1. Sintesi Esecutiva

Durante i test di creazione autonoma da chat, l'agente LLM ha effettuato 3 tentativi di generazione di una nuova automazione ricorrente per il monitoraggio dei repository trending su GitHub:
- **Tentativo 1**: Creazione riuscita a livello DB (`github-trending-daily-report`), ma **fallimento immediato all'esecuzione** (`Errore esecuzione tool 'web_search': Parametro 'query' mancante`).
- **Tentativo 2**: Creazione riuscita a livello DB (`auto-github-trending-daily`), ma **fallimento all'avvio del runner** (`Step 'step_1' mancante`).
- **Tentativo 3**: Fallimento in fase di generazione/chiamata tool (chiamata non completata o rifiutata dal parsing dello schema).

L'indagine ha rivelato che il problema **non è un limite intrinseco dei modelli compatti o self-hosted**, bensì una serie di **falle di rigidità nel parser di normalizzazione (`normalize_proposal`)** e l'**assenza di un harness con schema contract guidato e validazione pre-flight**.

---

## 2. Autopsia Tecnica dei Singoli Tentativi

### 2.1 Tentativo 1 — `github-trending-daily-report`

- **Definizione Registrata nel DB (`automations.db`):**
  ```json
  {
    "id": "github-trending-daily-report",
    "name": "GitHub Trending Daily Report",
    "workflow": {
      "initial_step_id": "fetch_trending_data",
      "steps": [
        {
          "step_id": "fetch_trending_data",
          "name": "Cerca Trending su GitHub",
          "type": "agent_task",
          "action_or_tool": "web_search",
          "arguments": {
            "query": "site:github.com trending repositories today programming"
          }
        },
        ...
      ]
    }
  }
  ```

- **Cosa è accaduto nel codice:**
  1. Il modello LLM ha denominato i parametri dello step come `"arguments": { "query": ... }` (convenzione standard OpenAI/Gemini Tool Calling) anziché `"parameters"` o `"params"`.
  2. Il metodo `AutomationDefinition.normalize_proposal()` in `backend/automations/models.py` conteneva:
     ```python
     if not s.get("parameters"):
         s["parameters"] = s.get("params") or {}
     ```
     Poiché non verificava `arguments` né `args`, `s["parameters"]` è stato inizializzato come dizionario vuoto `{}`.
  3. Il modello ha indicato `"type": "agent_task"`. Il controllo in `normalize_proposal`:
     ```python
     raw_type = str(s.get("type", "")).lower()
     if raw_type in ("llm_call", "agent", "llm"):
         s["type"] = StepType.AGENTIC_TASK.value
     ```
     Non includeva `"agent_task"`. Di conseguenza, lo step è decaduto in `StepType.DETERMINISTIC_ACTION` con parametri vuoti.
  4. Al momento dell'esecuzione da parte del Runner (`runner.py`):
     ```python
     res = tool_registry.execute_tool("web_search", args={})
     ```
     `web_search` ha sollevato l'eccezione: `Parametro 'query' mancante.`, portando la run allo stato `FAILED`.

---

### 2.2 Tentativo 2 — `auto-github-trending-daily`

- **Definizione Registrata nel DB:**
  ```json
  {
    "id": "auto-github-trending-daily",
    "name": "GitHub Trending Daily Report",
    "workflow": [
      {
        "id": "step_1_search",
        "name": "Cerca Trending",
        "tool": "web_search",
        "args": { "query": "trending github repositories" }
      },
      {
        "id": "step_2_report",
        "name": "Genera Report",
        "type": "llm",
        "prompt": "Sintetizza i repo..."
      }
    ]
  }
  ```

- **Cosa è accaduto nel codice:**
  1. Il modello ha passato `workflow` come lista di step anziché come oggetto con `initial_step_id` e `steps`.
  2. `normalize_proposal` ha tentato di normalizzare la lista:
     ```python
     if isinstance(wf, list):
         steps = list(wf)
         initial_id = steps[0].get("step_id", "step_1") if (steps and isinstance(steps[0], dict)) else "step_1"
         d["workflow"] = {"initial_step_id": initial_id, "steps": steps}
     ```
     Nel payload del modello, il primo step usava il campo `"id": "step_1_search"`, non `"step_id"`.
     Di conseguenza, `steps[0].get("step_id")` ha restituito `None`, e `initial_id` ha assunto il fallback hardcoded `"step_1"`.
  3. Poco più sotto, nel ciclo di normalizzazione degli step:
     ```python
     if not s.get("step_id"):
         s["step_id"] = s.get("id") or f"step_{idx+1}"
     ```
     Il primo step è stato salvato con `step_id = "step_1_search"`.
  4. **Incoerenza Fatale**: Il workflow è stato registrato con `initial_step_id = "step_1"`, ma nessun elemento nella lista degli step possedeva `step_id == "step_1"`.
  5. All'avvio della run, il Runner ha eseguito:
     ```python
     step_def = next((s for s in auto_def.workflow.steps if s.step_id == current_step_id), None)
     if not step_def:
         auto_db.update_run_status(run_id, RunStatus.FAILED.value, error_message=f"Step '{current_step_id}' mancante")
     ```
     La run è fallita in 0 millisecondi con l'errore: `Step 'step_1' mancante`.
  6. Inoltre, anche in questo caso il modello aveva usato `"args"` invece di `"params"`, per cui anche se il primo step fosse partito, sarebbe fallito subito dopo per `query` mancante.

---

### 2.3 Tentativo 3 — Fallimento di Generazione

Nel terzo tentativo, il modello non ha generato la chiamata o ha tentato di comporre un JSON non conforme senza riuscire a completare il tool call.
**Causa:**
1. Il tool `create_custom_automation` aveva una descrizione troppo sintetica (`"Oggetto JSON conforme al modello AutomationDefinition con campi: id, name, description, triggers, workflow (con steps), permission_policy, budget."`), senza specificare la struttura esatta di uno step, né fornire uno snippet di esempio.
2. Nel system prompt di `agent_loop.py` non era presente alcuna istruzione che illustrasse all'agente come strutturare un workflow sequenziale, quali tool invocare e come passare i dati tra step (`{{steps.<id>.output}}`).

---

## 3. Lezioni Apprese sull'Agent Harnessing (SOTA 2026)

Lavorando con modelli compatti, self-hosted (es. 8B–14B parametrizzati su vLLM/Ollama/Proxmox) o quantizzati:
1. **La tolleranza sintattica dell'Harness deve essere asimmetrica**:
   Non possiamo imporre al modello una rigidità da compilatore C++ su nomi di chiavi intercambiabili (`parameters` vs `params` vs `args` vs `arguments`). L'harness deve normalizzare attivamente tutti i sinonimi comuni.
2. **Validazione Pre-Flight Obbligatoria (Fail-Fast a livello Tool)**:
   Se un'automazione definisce `initial_step_id = "step_1"`, ma lo step `"step_1"` non esiste, o se uno step richiede il tool `web_search` senza fornire il parametro `query`, il tool `create_custom_automation` **deve rifiutare il salvataggio** e restituire un messaggio esplicito all'agente in chat:
   > *"Errore di validazione: lo step iniziale 'step_1' non corrisponde a nessuno step definito (trovati: ['step_1_search']). Correggi l'ID o fornisci la definizione."*  
   Questo innesca il meccanismo naturale di auto-correzione dell'agente nello stesso turno di conversazione.
3. **Iniezione del Contesto Operativo (Context Grounding)**:
   L'agente deve ricevere nel prompt l'elenco esatto delle integrazioni attive (es. email configurata, chiavi API disponibili, tool del registry abilitati) per evitare allucinazioni su servizi inesistenti.
