# Provider di modelli e ruoli: design

**Data:** 14 novembre 2026
**Stato:** decisioni del maintainer prese il 14/11/2026 e il 26/11/2026 ([sezione 3](#3-decisioni)). P0 (ruoli) costruita il 15/11/2026; P1 (costo, prezzi, tetti) costruita il 15/11/2026 nel backend; P2 (Bedrock e ripieghi) costruita, rivista e installata il 26/11/2026. L'interfaccia di P1 è assorbita da PU, i provider gestiti dalla Web UI ([sezione 5.8](#58-provider-gestiti-dalla-web-ui-pu)), in costruzione.
**Contesto:** oggi ogni chiamata a un modello va a un server in casa. L'obiettivo è aggiungere provider cloud (prima AWS Bedrock, poi OpenRouter), sapere quanto costa ogni chiamata, fermarsi a un tetto di spesa e scegliere il provider chiamata per chiamata, senza far uscire dati che la destinazione non può ricevere ([SENSITIVITY_DESIGN.md](../sensitivity/SENSITIVITY_DESIGN.md), fase S4).

---

## 1. In breve

- Un provider cloud è un altro `OpenAICompatProvider`: Bedrock espone un endpoint compatibile con le Chat Completions di OpenAI che accetta una chiave API. Nessun gateway in mezzo e nessuna libreria nuova.
- Ogni chiamata a un modello dichiara un **ruolo** (instradare, pianificare, scegliere il tool, rispondere, consolidare la memoria, ...), come già dichiara un'etichetta. Il ruolo finisce nelle metriche: prima di spostare qualcosa nel cloud si vede quale ruolo consuma cosa.
- Ogni chiamata ha un **costo**, calcolato dai token e dal prezzo del modello al momento della chiamata, e salvato con lei.
- I **tetti di spesa** si impostano dalla Web UI, per provider e in totale. Raggiunto un tetto, la chiamata va al modello locale e l'interfaccia lo dice.
- La scelta del provider per una chiamata combina tre cose, in quest'ordine: l'etichetta dei dati (un provider non riceve ciò che supera il suo livello), il tetto, la preferenza per ruolo.

## 2. Cosa c'è oggi

Verificato sul ramo `dev` il 14/11/2026.

| Cosa | Dove | Nota |
| :--- | :--- | :--- |
| Provider registrati | `app/llm/providers.py`: `llamacpp` (`OpenAICompatProvider` verso llama-swap) e `ollama` (facoltativo) | Uno solo è attivo, per tutte le chiamate (`set_active_provider`, scelto dal selettore dei modelli) |
| Punto di passaggio unico | `LLMProvider.chat(..., tag=...)` | Controlla `can_flow(tag, provider_destination(name))` e registra la chiamata; `tag` è obbligatorio |
| Livello ammesso di un provider | `LLAMA_CPP_CLEARANCE`, `OLLAMA_CLEARANCE` in `.env`; un provider sconosciuto vale `internal` | Impostazione esplicita, non dedotta dall'indirizzo |
| Metriche | `observability/store.py`, tabella `llm_calls`: provider, modello, token (prompt, cache, risposta), tempi, errore, etichetta, destinazione | Nessun ruolo, nessun costo |
| Ragionamento | `app/llm/reasoning.py`: un profilo per famiglia di modelli, scelto dal nome | I profili sono dei modelli locali |
| Cose di llama.cpp nel provider generico | `return_progress`, `chat_template_kwargs`, `reasoning_budget_tokens` nel payload; caricamento del modello (`ensure_model_loaded`); il watchdog delle risorse (`unavailable_reason`); elenco dei modelli da `/models` | Un endpoint cloud può rifiutare campi che non conosce e non ha modelli da caricare |
| Chiamate a un modello | 16 punti: router, piano, selezione del tool, risposta, sintesi, riscrittura pulita, prefetch, filtro della memoria, estrazione dei fatti, consolidamento, procedure, titolo, visione, rollback, sintesi dopo un'approvazione, valutazioni | Si distinguono solo per `reasoning_phase`, che è un testo per l'interfaccia |

## 3. Decisioni

Prese dal maintainer il 14/11/2026.

| # | Domanda | Decisione |
| :--- | :--- | :--- |
| 1 | Primo provider | AWS Bedrock (ci sono crediti), poi OpenRouter |
| 2 | Tetto di spesa | Impostabile dalla Web UI, per provider e in totale: i saldi sono molto diversi |
| 3 | Embedding | Restano locali. Offrirli anche tramite provider è da valutare con i numeri ([sezione 8](#8-punti-aperti)) |
| 4 | Credenziali | Le crea il maintainer e le scrive nel `.env` dell'istanza oppure, dal 26/11, nella Web UI (decisione 6); gli agenti non leggono quel file |
| 5 | Dati `private` verso il cloud | Mai in automatico: si concede a mano, provider per provider (decisione 3 del design della sensibilità) |

Prese dal maintainer il 26/11/2026 ([sezione 5.8](#58-provider-gestiti-dalla-web-ui-pu)):

| # | Domanda | Decisione |
| :--- | :--- | :--- |
| 6 | Dove si configurano i provider | Nella Web UI: modificare, attivare e disattivare, eliminare, aggiungerne di nuovi (anche motori compatibili OpenAI come un altro llama-server o vLLM). Il `.env` resta il valore di base |
| 7 | Come si unisce al `.env` | Campo per campo: un campo non impostato dalla UI prende il valore del `.env` |
| 8 | Cambio di indirizzo | Riporta il livello ammesso a `public` finché il maintainer non lo conferma per il nuovo indirizzo |
| 9 | Credenziali senza `API_SECRET_KEY` | Il salvataggio è rifiutato: la chiave di cifratura ricadrebbe su una stringa nota |
| 10 | Provider attivo | Nessuno "switch" globale. Il selettore dei modelli mostra tutti i provider attivi raggruppati per provider, e ogni richiesta porta il suo provider: due conversazioni possono usare in contemporanea un provider locale e uno cloud |

## 4. Bedrock: cosa è stato verificato

Dalla documentazione AWS, letta il 14/11/2026 ([Chat Completions API](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html), [Endpoint availability](https://docs.aws.amazon.com/bedrock/latest/userguide/models-endpoint-availability.html)). Niente è stato provato con una chiave vera.

- **Endpoint:** `https://bedrock-runtime.{region}.amazonaws.com/openai/v1/chat/completions`, quello consigliato per le applicazioni nuove. Autenticazione con una chiave API di Bedrock come `Authorization: Bearer`, oppure SigV4.
- **Nessun elenco dei modelli** su quell'endpoint (`GET /models` risponde 404): i modelli offerti vanno scritti nella configurazione.
- **Identificativi dei modelli** propri di Bedrock (per esempio `openai.gpt-oss-120b-1:0`), o un profilo di inferenza tra regioni.
- **Un secondo endpoint**, `bedrock-mantle.{region}.api.aws/v1`, ha l'elenco dei modelli e alcuni modelli che l'altro non ha; il prefisso del percorso cambia da modello a modello. Si usa solo se serve un modello che manca sul primo.
- **Da verificare con la chiave:** quali modelli accettano le Chat Completions (la scheda di ogni modello lo dice; per i modelli Claude va controllato), i campi che l'endpoint rifiuta, se lo streaming riporta i token usati (`stream_options.include_usage`), `response_format` con uno schema JSON, il controllo del ragionamento.

## 5. Il design

### 5.1 Il provider cloud

Una sottoclasse di `OpenAICompatProvider`, `CloudOpenAIProvider`, che cambia quattro cose:

1. si autentica con la chiave API come `Authorization: Bearer`, oppure firma la richiesta con le credenziali AWS (SigV4). Per la firma: `botocore` come dipendenza o la firma scritta nel backend, da decidere in P2 (la prima è una libreria in più, la seconda un centinaio di righe da provare contro gli esempi ufficiali);
2. costruisce il payload senza i campi di llama.cpp, e traduce il ragionamento in ciò che l'endpoint accetta (da decidere modello per modello, sezione 4);
3. non carica modelli e non consulta il watchdog;
4. l'elenco dei modelli viene dalla configurazione.

Il provider esiste solo se la sua chiave è impostata: senza, il comportamento resta quello di oggi.

Variabili di `backend/.env` (i nomi veri, anche in `.env.example`):

| Variabile | Contenuto | Default |
| :--- | :--- | :--- |
| `BEDROCK_API_KEY` | Chiave API di Bedrock (autenticazione `Bearer`) | vuoto |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` | In alternativa alla chiave API: credenziali AWS (firma SigV4). Stessi nomi di EXAMEN e degli SDK di AWS | vuoto. Senza chiave né credenziali il provider è spento |
| `AWS_REGION` | Regione AWS (stesso nome di EXAMEN) | nessuno: obbligatoria con le credenziali |
| `BEDROCK_MODELS` | Identificativi dei modelli offerti, separati da virgola | nessuno: obbligatoria con la chiave |
| `BEDROCK_CLEARANCE` | Livello più alto che può ricevere: `public` o `internal` | `public` |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODELS`, `OPENROUTER_CLEARANCE` | Lo stesso per OpenRouter | provider spento, `public` |

`private` non è un valore ammesso da `.env` per un provider cloud: si concede dalla Web UI, con una conferma, e resta nell'audit.

### 5.2 Ruoli

`LLMProvider.chat` e `call_llm` ricevono un argomento `role`, obbligatorio e senza default come `tag`: una chiamata nuova che non lo dichiara fa fallire i test.

| Ruolo | Chiamate di oggi | Cosa vede |
| :--- | :--- | :--- |
| `route` | Router della modalità | Il messaggio dell'utente e gli ultimi messaggi |
| `plan` | Piano e sua revisione | La richiesta, il catalogo dei tool |
| `select_tool` | Scelta del tool a ogni passo | La richiesta, il catalogo, i risultati precedenti |
| `rewrite_exit` | Riscrittura pulita di un'uscita | Solo ciò che la destinazione può ricevere |
| `answer` | Risposta della chat, risposta diretta, sintesi finale, sintesi dopo un'approvazione | Tutto ciò che il turno ha raccolto |
| `prefetch` | Ricerca web iniziale: la query, anche da un'immagine allegata | La richiesta, l'immagine |
| `summarize` | Riassunto progressivo della conversazione | I messaggi della conversazione |
| `consolidate` | Estrazione dei fatti, consolidamento, procedure | Conversazioni intere |
| `title` | Titolo della conversazione | Il primo messaggio |
| `vision` | Descrizione di un'immagine | Immagini |
| `rollback` | Piano di rollback | I passi eseguiti |
| `eval` | Giudizio nelle valutazioni | Casi di prova |

Il ruolo va nella tabella `llm_calls` (colonna `role`) e nel riepilogo delle metriche: chiamate, token e costo per ruolo.

### 5.3 Costo

- **Prezzi:** per ogni coppia provider e modello, dollari per milione di token di prompt, di prompt in cache e di risposta. Si impostano dalla Web UI e stanno in una tabella del database delle metriche. Un modello senza prezzo costa zero e l'interfaccia lo segnala per i provider cloud.
- **Costo di una chiamata:** calcolato quando la chiamata finisce e salvato con lei (`llm_calls.cost_usd`): cambiare un prezzo non riscrive il passato.
- **Cosa non è:** il saldo vero dell'account. È la nostra contabilità, token per prezzo. I crediti AWS e il saldo di OpenRouter si leggono dai loro pannelli.

### 5.4 Tetti

- Due tipi, in dollari al mese: uno per provider e uno totale. Vuoto vuol dire nessun tetto.
- Prima di ogni chiamata a un provider cloud: se la spesa del mese di quel provider, o quella totale, ha raggiunto il tetto, la chiamata va al provider locale.
- L'interfaccia lo dice nel turno ("tetto di spesa raggiunto: risposta dal modello locale") e la chiamata resta nelle metriche con il motivo.
- Il controllo guarda la spesa già registrata: una chiamata lunga può superare il tetto di quanto costa lei stessa.

### 5.5 Scelta del provider per chiamata

Oggi c'è un provider attivo per tutto. Diventa una funzione, `choose_provider(role, tag)`, chiamata da `call_llm`:

1. **Preferenza:** il provider e il modello scelti dall'utente nel selettore, oppure, quando esiste, la preferenza del ruolo (5.6).
2. **Etichetta:** se il provider preferito non può ricevere l'etichetta dei dati (`can_flow`), si usa il provider locale. Oggi quel caso alza `FlowDenied`; con un provider cloud diventa un ripiego, perché è il caso normale e non un errore.
3. **Tetto:** se è raggiunto, provider locale.

Il motivo del ripiego (`label`, `budget`) va nelle metriche e, per il turno, nell'interfaccia.

Conseguenza: con un modello cloud selezionato, un turno che tocca dati privati continua sul modello locale da quel passo in poi. Il modello locale va caricato, e i due modelli hanno capacità diverse: va misurato quanto spesso succede e quanto costa in tempo.

### 5.6 Preferenza per ruolo

Dopo il turno intero su un provider (5.5) e solo se i numeri lo giustificano: una tabella ruolo → `solo locale`, `preferisci locale`, `cloud ammesso`, con il modello. La prima combinazione da provare è quella del brief: il cloud pianifica (`plan`, `select_tool`), il locale legge i risultati (`answer`). Prima di costruirla si misura l'alternativa semplice sulle suite di valutazione: un modello cloud per tutto il turno.

### 5.7 Interfaccia

Sostituita dalla [sezione 5.8.7](#587-interfaccia). Restano da qui:

- **Metriche:** costo nel riepilogo e per modello, e una tabella per ruolo.
- **Turno:** un avviso quando una chiamata è andata al modello locale per l'etichetta o per il tetto.

### 5.8 Provider gestiti dalla Web UI (PU)

Decisioni 6–10. Oggi i provider nascono all'avvio dal `.env`, uno solo è "attivo" per tutte le chiamate (`_ACTIVE_PROVIDER_NAME`, `set_active_provider`, `POST /v1/providers/active`) e una richiesta di chat porta solo il nome del modello.

#### 5.8.1 Un modello si sceglie con il suo provider

- **Riferimento:** una scelta di modello è la coppia `(provider, model)`. `ChatRequest` (e le altre richieste che oggi hanno `model`) riceve `provider`; la conversazione salva entrambi.
- **Niente provider attivo globale:** `_ACTIVE_PROVIDER_NAME`, `set_active_provider` e `POST /v1/providers/active` spariscono (cambiamento non retrocompatibile, ammesso in dev). Una richiesta senza `provider` usa il **provider predefinito** (impostazione della UI, di base `llamacpp`).
- **Le chiamate interne del turno** (router, piano, tool, risposta, titolo, ispezione delle immagini) usano il provider del turno, sempre attraverso `choose_provider`. Il provider del turno arriva esplicito o in un `contextvars` impostato all'inizio del turno; se si usa un contextvar, va copiato nei thread che il turno apre (`contextvars.copy_context`), altrimenti un thread vedrebbe il provider predefinito.
- **Lavoro in background** non legato a un turno (consolidamento della memoria, procedure, automazioni senza un modello scelto): il provider predefinito.
- **Concorrenza:** due turni simultanei con provider diversi non si scambiano mai provider, modello o modello caricato. È un requisito con un test: due turni in parallelo, uno su un provider finto locale e uno su un provider finto cloud, e ogni chiamata registrata con il provider del suo turno.
- **Provider disattivato o eliminato:** una richiesta che lo nomina risponde 409 con il motivo, senza ripiegare da sola su un altro provider. Il selettore lo mostra non disponibile sulla conversazione che lo usava.

#### 5.8.2 Configurazione: dove sta e come si unisce al `.env`

- **Tabella `provider_configs` in `mcp.db`**, accanto a prezzi e tetti: `name` (chiave, identificativo stabile: minuscole, cifre, `-`; mai `total`), `kind`, `display_name`, `enabled`, i campi del tipo (JSON), `clearance`, `clearance_url`, `encrypted_secrets` (cifrati con `secret_box`), `updated_at`.
- **Provider del `.env`**: `llamacpp`, `ollama`, `bedrock`, e `openrouter` quando arriva (P4). Ogni campo non impostato dalla UI prende il valore del `.env`. Ogni campo restituito dalle API dice da dove viene (`env`, `ui`, `default`); `null` in una modifica riporta quel campo al `.env`.
- **Provider aggiunti dalla UI** non hanno un `.env` dietro: tutti i loro campi vengono dalla tabella.
- **Eliminare:** un provider aggiunto dalla UI si elimina, con i suoi prezzi e il suo tetto (le metriche passate restano). Un provider del `.env` non si elimina, perché al riavvio tornerebbe: si disattiva, e "Ripristina il .env" toglie tutte le modifiche della UI.
- **Tipi:**

| `kind` | Per | Campi | Credenziali |
| :--- | :--- | :--- | :--- |
| `openai_compat` | Un motore in casa compatibile OpenAI: llama-swap, llama-server, vLLM, LM Studio | `base_url`, `default_model`, `llama_cpp` (sì/no: progresso, caricamento dei modelli, watchdog, campi del ragionamento di llama.cpp) | Chiave API facoltativa (`Bearer`) |
| `ollama` | Ollama | `base_url`, `default_model` | Nessuna |
| `bedrock` | AWS Bedrock | `region`, `models` | Chiave API di Bedrock, oppure chiave di accesso, segreto e token di sessione AWS |
| `openai_cloud` | Un servizio cloud compatibile OpenAI (OpenRouter in P4 è questo tipo con `base_url` fisso) | `base_url`, `models` | Chiave API (`Bearer`), obbligatoria |

- **Cambiare tipo** non è ammesso: si crea un altro provider.
- **A caldo:** salvare ricostruisce il provider e lo sostituisce nell'elenco sotto un lock. Le chiamate già partite finiscono con l'oggetto vecchio. Nessun riavvio.

#### 5.8.3 Il livello ammesso segue l'indirizzo

- Il livello concesso si salva con l'indirizzo per cui è stato concesso (`clearance_url`; per Bedrock la regione). **Livello effettivo** = quello salvato se l'indirizzo attuale è lo stesso, altrimenti `public` (decisione 8). Per un provider del `.env` lo stesso: `LLAMA_CPP_CLEARANCE` vale per `LLAMA_CPP_URL`, non per un indirizzo cambiato dalla UI.
- **Alzare** il livello chiede una conferma esplicita nella richiesta (`confirm: true`); la UI la chiede con un dialogo che dice l'indirizzo e cosa potrà ricevere. **Abbassarlo** non chiede nulla.
- **Provider cloud** (`bedrock`, `openai_cloud`): dal `.env` al massimo `internal`, come oggi; `private` solo dalla UI, con la conferma.
- **Un provider nuovo** nasce `public`. Un provider sconosciuto a `provider_destination` vale `public` (oggi vale `internal`: con provider creati dalla UI non basta più).
- **Provider di ripiego:** il ripiego per etichetta e per tetto (5.5) va a un provider indicato nelle impostazioni, di base `llamacpp`, al posto della costante `LOCAL_PROVIDER`. Deve avere livello effettivo `private` ed essere attivo: finché è il ripiego non si disattiva né si elimina, e un cambio di indirizzo che gli abbassa il livello va confermato.

#### 5.8.4 Credenziali

- **Sola scrittura:** le API non le restituiscono mai. Per ogni credenziale dicono `{set, source}` (`env`, `ui`, oppure non impostata).
- **Senza `API_SECRET_KEY`** il salvataggio di una credenziale risponde 409 e non salva nulla (decisione 9).
- **Credenziale illeggibile** (`API_SECRET_KEY` cambiata): il provider non si costruisce, la UI dice "credenziale illeggibile, inseriscila di nuovo".
- **Cosa protegge la cifratura:** le copie e i backup del database, non chi entra nel container (la chiave sta nel `.env` sullo stesso disco). Per Bedrock: credenziali dedicate con i soli permessi di invocazione, o una chiave API di Bedrock; i tetti di spesa restano il paracadute.

#### 5.8.5 Audit e confini

- Ogni creazione, modifica, attivazione, eliminazione e cambio di livello va nel log di audit: chi, quando, quali campi. Mai il valore di una credenziale.
- Queste API sono solo dell'utente, dietro `verify_api_key`. Nessun tool dell'agente le raggiunge: un test lo fissa.
- "Prova connessione" chiama l'indirizzo configurato e restituisce solo stato, tempo ed eventuale numero di modelli, non il corpo della risposta.

#### 5.8.6 API

| Metodo e percorso | Cosa fa |
| :--- | :--- |
| `GET /v1/providers` | Tutti i provider: tipo, nome visibile, attivo, campi con la loro origine, credenziali `{set, source}`, livello salvato ed effettivo, raggiungibile, predefinito, ripiego |
| `POST /v1/providers` | Crea un provider (nasce `public`) |
| `PATCH /v1/providers/{name}` | Modifica campi e credenziali; `null` riporta un campo al `.env` |
| `DELETE /v1/providers/{name}` | Elimina un provider della UI; 409 per uno del `.env` o per il ripiego |
| `POST /v1/providers/{name}/reset` | Provider del `.env`: toglie tutte le modifiche della UI |
| `PUT /v1/providers/{name}/clearance` | `{level, confirm}`: alzare senza `confirm` risponde 409 |
| `POST /v1/providers/{name}/test` | Prova la connessione, con la configurazione salvata o con quella inviata |
| `PUT /v1/providers/settings` | Provider predefinito e provider di ripiego |
| `GET /v1/models` | Il catalogo per il selettore: i provider attivi, ciascuno con nome, tipo, locale o cloud, livello effettivo, raggiungibile, e i suoi modelli con i dettagli di oggi (visione, caricato) |

Restano quelle di P1 per prezzi, tetti e spesa (`/v1/providers/costs`, `.../price`, `.../ceilings`).

#### 5.8.7 Interfaccia

- **Impostazioni, scheda "Provider":** un elenco di provider con stato (attivo, raggiungibile), tipo e livello effettivo. Per ciascuno:
  - il modulo del suo tipo, con accanto a ogni campo l'origine ("da .env", "dalla UI") e il pulsante per tornare al `.env`;
  - le credenziali in sola scrittura;
  - interruttore attivo e disattivo;
  - "Prova connessione";
  - il livello, con il dialogo di conferma per alzarlo e l'avviso quando un cambio di indirizzo l'ha riportato a `public`;
  - prezzi dei modelli, tetto e spesa del mese (P1);
  - "Elimina" per i provider della UI, "Ripristina il .env" per quelli del `.env`.

  Sotto: "Aggiungi provider", il tetto totale, il provider predefinito e quello di ripiego.
- **Selettore dei modelli:** i modelli di tutti i provider attivi, raggruppati sotto il nome del provider, con un'indicazione locale o cloud e il livello. Un provider non raggiungibile resta nell'elenco, segnato. La scelta è per conversazione.
- **Turno:** l'avviso di ripiego (5.7) dice anche verso quale provider.

## 6. Ordine di costruzione

Ogni fase lascia il sistema funzionante; le prime due non chiedono nessuna chiave.

| Fase | Contenuto | Serve il maintainer? |
| :--- | :--- | :--- |
| **P0. Ruoli** | Argomento `role` obbligatorio, colonna nelle metriche, riepilogo per ruolo | No |
| **P1. Costo e tetti** | Prezzi e tetti nel database e nelle API, costo salvato a ogni chiamata, spesa del mese; scheda "Provider" e costo nelle Metriche | No (si prova con un prezzo finto sul modello locale) |
| **P2. Provider cloud** | `CloudOpenAIProvider`, variabili di Bedrock, `choose_provider` con i ripieghi per etichetta e tetto | Per i test veri sì: la chiave, la regione, i modelli. I test automatici usano un server finto |
| **PU. Provider dalla Web UI** (5.8) | PU1: provider per richiesta, via il provider attivo globale. PU2: `provider_configs`, unione con il `.env`, ricostruzione a caldo, livello legato all'indirizzo, credenziali, audit, API. PU3: scheda "Provider" e selettore raggruppato (assorbe l'interfaccia di P1) | No: si prova con provider finti e con un secondo motore locale. Bedrock dal vivo quando ci sono le credenziali |
| **P3. Misura** | Le suite di valutazione su uno o due modelli cloud, confronto con la tabella locale; quante volte scatta il ripiego | Sì (costa crediti) |
| **P4. OpenRouter** | Le sue variabili; preferenze sulla conservazione dei dati impostate in modo esplicito | Sì: la chiave |
| **P5. Preferenza per ruolo** | Solo se P3 lo giustifica | No |

### 6.1 P0 e P1 come sono state costruite

Il 15/11/2026, su `dev`.

- **Ruoli** ([roles.py](../../backend/app/llm/roles.py)): `role` è obbligatorio, senza default, in `LLMProvider.chat`, `call_llm` e `call_llm_structured`; un ruolo sconosciuto è un `ValueError` prima che la richiesta parta. Un test con `ast` controlla che ogni chiamata del backend lo passi, e un altro fissa i ruoli di ogni file. Rispetto alla tabella 5.2 si è aggiunto `summarize` (il riassunto progressivo della conversazione, che non sceglie ricordi): `filter_memory` è stato tolto perché nessuna chiamata filtra la memoria.
- **Metriche**: `llm_calls.role` e `llm_calls.cost_usd`; riepilogo per ruolo, costo totale, per modello, per ruolo e per intervallo nella serie temporale.
- **Prezzi e tetti** ([costs.py](../../backend/app/llm/costs.py)): tabelle `model_prices` e `spend_ceilings` in `mcp.db`, accanto alle altre impostazioni modificabili dalla UI (non nel database delle metriche, che si sfoltisce). Mese di calendario in UTC.
- **Convenzione dei token**: `prompt_tokens` comprende quelli in cache (llama.cpp: `prompt_n + cache_n`; OpenAI: per definizione). Costo = (prompt − cache) × prezzo d'ingresso + cache × prezzo della cache + risposta × prezzo d'uscita.
- **API**: `GET /v1/providers/costs` (prezzi, tetti, spesa del mese per provider e totale, tetti raggiunti); `PUT`/`DELETE /v1/providers/{nome}/models/{modello}/price`; `PUT`/`DELETE /v1/providers/ceilings/{provider o total}`. Gli identificativi dei modelli con `/`, `:` e `.` sono provati.
- **Conservazione delle metriche**: le chiamate del mese in corso non vengono più cancellate dalla pulizia a 30 giorni, altrimenti a fine mese la spesa del primo giorno spariva e i tetti contavano meno.
- **Da fare in P2**: leggere `prompt_tokens_details.cached_tokens` dalla risposta dei provider cloud (oggi i token in cache si leggono solo da llama.cpp, quindi sul cloud sarebbero pagati a prezzo pieno); `ceiling_reached` esiste ma non è ancora nel percorso delle chiamate; nessun provider può chiamarsi `total`, il nome del tetto complessivo.
- **Interfaccia**: da fare (scheda "Provider" e costo nelle Metriche).

## 7. Cosa deve fare il maintainer per P2

1. Nella console AWS, nella regione scelta: abilitare l'accesso ai modelli da usare.
2. Credenziali, una delle due:
   - una chiave API di Bedrock (`BEDROCK_API_KEY`), la più semplice;
   - le credenziali AWS (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`), con gli stessi nomi del `.env` di EXAMEN, da cui si possono copiare. Meglio però credenziali dedicate con i soli permessi di Bedrock (`bedrock:InvokeModel` e `bedrock:InvokeModelWithResponseStream`): quelle di EXAMEN possono avere altri permessi (DynamoDB), e una chiave per servizio si revoca senza toccare l'altro. Gli agenti non leggono né copiano il `.env` di EXAMEN.
3. Scrivere in `backend/.env` dell'istanza le credenziali, `AWS_REGION` e `BEDROCK_MODELS` (e `BEDROCK_CLEARANCE` se diverso da `public`). Dopo PU si possono inserire invece nella scheda "Provider" della Web UI, senza riavviare. EXAMEN usa `us-east-1`: se conta dove finiscono i dati, una regione UE, controllando che i modelli scelti ci siano.
3. Ricreare il backend (`up -d backend`: `restart` non rilegge `.env`).

## 8. Punti aperti

- **Quali modelli.** Dipende da cosa accetta le Chat Completions nella regione scelta: si decide con la chiave in mano.
- **Ragionamento sui modelli cloud.** I profili di `reasoning.py` sono dei modelli locali; per ogni modello cloud va scritto il suo.
- **Cache del prompt.** Cambiare provider a metà turno la perde; sul cloud ha un prezzo diverso. Da guardare in P3.
- **Embedding tramite provider.** Da valutare con tre numeri: qualità del richiamo rispetto al modello locale sulle suite di memoria, costo di ricalcolare tutta la memoria a ogni cambio di modello, e il fatto che ogni testo della memoria uscirebbe dal homelab (oggi molti sono `private`: non potrebbero).
- **Conservazione dei dati presso il provider.** Da leggere per Bedrock e per OpenRouter prima di alzare un livello ammesso sopra `public`.
