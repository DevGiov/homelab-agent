# Impostazioni modificabili dalla Web UI: design

**Data:** 27 novembre 2026
**Stato:** principio deciso dal maintainer il 27/11/2026; R1 (canali e Telegram) in costruzione.
**Contesto:** oggi il backend legge 39 impostazioni dal `.env` all'avvio. Solo i provider di modelli si gestiscono dalla Web UI ([PROVIDERS_DESIGN.md, 5.8](../providers/PROVIDERS_DESIGN.md#58-provider-gestiti-dalla-web-ui-pu)). Cambiare il resto vuol dire entrare nel container, scrivere il file e ricreare il backend.

---

## 1. Il principio

Decisione del maintainer del 27/11/2026:

> Quando possibile, un'impostazione si cambia dalla Web UI mentre il servizio gira, invece di stare scritta solo nel `.env`.

- **Il `.env` resta il valore di base**, campo per campo, come per i provider: la UI sovrascrive un campo, "Ripristina il .env" lo riporta al valore del file. Un'istanza nuova parte dal `.env` e funziona senza passare dalla UI.
- **Effetto subito** quando si può (il componente si ricostruisce sotto un lock, come i provider). Quando serve un riavvio, la UI lo dice accanto al campo e dopo il salvataggio ("Salvato: vale dal prossimo riavvio del backend").
- **Restano solo nel `.env`** le impostazioni che servono prima che la UI esista o che la proteggono: la chiave dell'API e di cifratura, `ALLOW_INSECURE`, le origini CORS, il limite di richieste, i percorsi dei dati. Cambiarle dalla UI vorrebbe dire poter togliere la protezione della UI stessa.
- **Credenziali** in sola scrittura (`{set, source}`), cifrate con `secret_box`; senza `API_SECRET_KEY` non si salvano (409 `no_secret_key`). È la regola dei provider.
- **Cosa decide chi riceve i dati o chi comanda l'agente** (livello di un canale, utenti ammessi) chiede una conferma per allargarsi e finisce nell'audit, solo con i nomi dei campi.
- **Nessun tool dell'agente** raggiunge queste API: un test lo controlla, come per i provider.

## 2. Inventario

| Impostazioni | Dove | Fase |
| :--- | :--- | :--- |
| `API_SECRET_KEY`, `ALLOW_INSECURE`, `CORS_ORIGINS`, `RATE_LIMIT`, `DATA_DIR` e percorsi derivati | Solo `.env` | — |
| Provider: `LLAMA_CPP_URL`, `OLLAMA_URL`, `DEFAULT_MODEL`, `*_CLEARANCE`, Bedrock e AWS | UI, subito | ✅ PU |
| Canali: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `TELEGRAM_CLEARANCE`, `WEB_UI_URL`, `CHANNEL_REPLY_TIMEOUT_SECONDS` | UI, subito (il canale si riavvia da solo) | **R1** |
| Ricerca web: `SEARXNG_URL`, `SEARXNG_ENGINES`, `SEARCH_PRIMARY_LANG`, `SEARCH_FALLBACK_LANG` | UI, subito | R2 |
| Agente: `AGENT_OBSERVATION_LIMIT`, `TRUNCATION_LIMIT`, `AGENT_INTERLEAVED_THINKING` | UI, subito | R2 |
| Servizi: `WATCHDOG_URL`, `FIRECRACKER_API_URL`, `FIRECRACKER_LOG_URL`, `FIRECRACKER_KERNEL_PATH`, `FIRECRACKER_ROOTFS_PATH` | UI, subito | R2 |
| Metriche e automazioni: `METRICS_SAMPLE_INTERVAL_S`, `METRICS_RETENTION_DAYS`, `ENABLE_AUTOMATION_SCHEDULER` | UI; il campionatore e lo scheduler si riavviano da soli, se non si può: "dal prossimo riavvio" | R2 |
| MetaMCP: `METAMCP_URL`, `METAMCP_API_KEY` | UI, con riconnessione del client MCP | R3 |

Una variabile nuova si classifica qui quando si aggiunge (anche "solo `.env`", con il motivo).

## 3. Il meccanismo (R1)

Un modulo generico, `app/core/runtime_settings.py`, che R2 e R3 riusano. I provider restano sul loro modulo ([provider_config.py](../../backend/app/llm/provider_config.py)), che ha regole proprie (indirizzo, livello, tipi).

- **Sezioni dichiarate nel codice.** Ogni sezione ha un id (`channels`, poi `search`, ...), i campi con l'attributo di `Settings` da cui viene il valore di base, il tipo e il validatore, quali sono credenziali, e una funzione `apply()` chiamata dopo un salvataggio (sotto un lock) che rende effettivo il cambio. Un campo che non si applica subito ha `restart: true`.
- **Tabella `runtime_settings` in `mcp.db`:** `(section, key, value_json, updated_at)`; le credenziali di una sezione in una riga cifrata `(section, "__secrets__", sealed)`. Una riga assente = vale il `.env`.
- **Lettura:** `runtime_settings.get(section, key)` restituisce il valore effettivo (UI, altrimenti `.env`, altrimenti default). Il codice che oggi legge `settings.telegram_*` o `settings.web_ui_url` legge da qui.
- **Audit:** `settings_update`, `settings_reset`, con sezione e nomi dei campi; mai i valori delle credenziali.

## 4. Canali (R1)

- **Campi della sezione `channels`:** `web_ui_url` (URL http/https o vuoto), `reply_timeout_seconds` (intero 30-3600).
- **Campi della sezione `telegram`:** `enabled` (bool, default vero se c'è il token), `allowed_users` (lista di id interi positivi), `clearance` (`public` o `internal`; `private` non si concede mai: decisione 2 di [CHANNELS_DESIGN.md](../channels/CHANNELS_DESIGN.md)); credenziale `bot_token`.
- **Applicare:** dopo un salvataggio della sezione `telegram` il hub ferma il canale Telegram se c'è, lo toglie, ne costruisce uno nuovo dai valori effettivi e lo avvia. Senza token, spento o senza utenti ammessi: resta fermo, e lo stato lo dice. Il hub guadagna `unregister(channel_id)` e `replace(channel)`.
- **Conferme:** alzare `clearance` da `public` a `internal`, e aggiungere un id ad `allowed_users`, vogliono `confirm: true` (409 `confirm_required` senza): chi è ammesso comanda l'agente. Togliere un utente o abbassare il livello no.
- **Prova:** "Prova il bot" chiama `getMe` con il token salvato o con quello della bozza e restituisce solo `{ok, bot_username, error}`. Il token non torna mai indietro, nemmeno nell'errore (la redazione di [telegram.py](../../backend/app/channels/telegram.py)).
- **Stato:** `running` (il ciclo di polling è attivo), `last_error` (l'ultimo errore della Bot API, già ripulito), `ignored` (messaggi scartati per tipo).

## 5. API (contratto di R1)

Tutte con la chiave dell'API. Errori come i provider: `{"detail": {"code", "message"}}`, 409 per i conflitti, 422 per un valore non valido, 404 per una sezione che non esiste.

```
GET  /v1/settings/channels
  -> {"web_ui_url": {"value", "source"}, "reply_timeout_seconds": {"value", "source"},
      "telegram": {"enabled": {"value", "source"}, "allowed_users": {"value": [int], "source"},
                   "clearance": {"value", "source"}, "secrets": {"bot_token": {"set": bool, "source": "env"|"ui"|null}},
                   "status": {"running": bool, "last_error": str|null, "ignored": {kind: int}}},
      "can_store_secrets": bool}
     # source: "env" | "ui" | "default"

PATCH /v1/settings/channels
  {"fields"?: {"web_ui_url"?: str|null, "reply_timeout_seconds"?: int|null},
   "telegram"?: {"fields"?: {"enabled"?: bool|null, "allowed_users"?: [int]|null, "clearance"?: str|null},
                 "secrets"?: {"bot_token"?: str|null}},
   "confirm"?: bool}
  -> come GET          # null = togli il valore della UI (torna al .env)
  409 confirm_required (livello alzato o utente aggiunto senza confirm), 409 no_secret_key

POST /v1/settings/channels/reset           -> come GET   # toglie ogni valore della UI dei canali
POST /v1/settings/channels/telegram/test   corpo facoltativo {"secrets": {"bot_token": str}}
  -> {"ok": bool, "bot_username": str|null, "error": str|null}
```

## 6. Interfaccia (R1)

Una scheda "Canali" nelle impostazioni:

- **Telegram:** stato (attivo, fermo con il motivo, ultimo errore), interruttore, token in sola scrittura con "Prova il bot" (mostra `@nome_del_bot`), utenti ammessi (lista di id, aggiungi e togli; aggiungere chiede conferma: "L'utente <id> potrà dare comandi all'agente"), livello senza conferma (`public` o `internal`, alzarlo chiede conferma), "Ripristina il .env". Un aiuto breve: come creare il bot con BotFather e come trovare il proprio id (per esempio scrivendo a un bot come @userinfobot).
- **Generale:** indirizzo della Web UI per i link, attesa massima della risposta.
- Ogni campo dice da dove viene il valore (`.env`, UI, default), come nella scheda Provider.

## 7. Ordine di costruzione

| Fase | Contenuto |
| :--- | :--- |
| **R1** | Modulo generico, sezione `channels` con Telegram, scheda "Canali", riavvio a caldo del canale |
| **R2** | Ricerca web, limiti dell'agente, watchdog, Firecracker, metriche, scheduler |
| **R3** | MetaMCP con riconnessione |
