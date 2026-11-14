# Provider di modelli e ruoli: design

**Data:** 14 novembre 2026
**Stato:** design scritto; decisioni del maintainer prese il 14/11/2026 ([sezione 3](#3-decisioni)). Nessuna fase costruita.
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
| 4 | Credenziali | Le crea il maintainer e le scrive nel `.env` dell'istanza; gli agenti non leggono quel file |
| 5 | Dati `private` verso il cloud | Mai in automatico: si concede a mano, provider per provider (decisione 3 del design della sensibilità) |

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

1. manda la chiave come `Authorization: Bearer`;
2. costruisce il payload senza i campi di llama.cpp, e traduce il ragionamento in ciò che l'endpoint accetta (da decidere modello per modello, sezione 4);
3. non carica modelli e non consulta il watchdog;
4. l'elenco dei modelli viene dalla configurazione.

Il provider esiste solo se la sua chiave è impostata: senza, il comportamento resta quello di oggi.

Variabili di `backend/.env` (i nomi veri, anche in `.env.example`):

| Variabile | Contenuto | Default |
| :--- | :--- | :--- |
| `BEDROCK_API_KEY` | Chiave API di Bedrock | vuoto: provider spento |
| `BEDROCK_REGION` | Regione AWS | nessuno: obbligatoria con la chiave |
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
| `prefetch` | Riassunto della ricerca web iniziale | Pagine web |
| `filter_memory` | Scelta dei ricordi pertinenti | La richiesta e i ricordi candidati |
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

- **Impostazioni, scheda "Provider":** per ogni provider lo stato (configurato o no, raggiungibile), il livello ammesso, i modelli con i prezzi, il tetto e la spesa del mese; in fondo il tetto totale.
- **Selettore dei modelli:** i modelli cloud compaiono con il nome del provider.
- **Metriche:** costo nel riepilogo e per modello, e una tabella per ruolo.
- **Turno:** un avviso quando una chiamata è andata al modello locale per l'etichetta o per il tetto.

## 6. Ordine di costruzione

Ogni fase lascia il sistema funzionante; le prime due non chiedono nessuna chiave.

| Fase | Contenuto | Serve il maintainer? |
| :--- | :--- | :--- |
| **P0. Ruoli** | Argomento `role` obbligatorio, colonna nelle metriche, riepilogo per ruolo | No |
| **P1. Costo e tetti** | Prezzi e tetti nel database e nelle API, costo salvato a ogni chiamata, spesa del mese; scheda "Provider" e costo nelle Metriche | No (si prova con un prezzo finto sul modello locale) |
| **P2. Provider cloud** | `CloudOpenAIProvider`, variabili di Bedrock, `choose_provider` con i ripieghi per etichetta e tetto | Per i test veri sì: la chiave, la regione, i modelli. I test automatici usano un server finto |
| **P3. Misura** | Le suite di valutazione su uno o due modelli cloud, confronto con la tabella locale; quante volte scatta il ripiego | Sì (costa crediti) |
| **P4. OpenRouter** | Le sue variabili; preferenze sulla conservazione dei dati impostate in modo esplicito | Sì: la chiave |
| **P5. Preferenza per ruolo** | Solo se P3 lo giustifica | No |

## 7. Cosa deve fare il maintainer per P2

1. Nella console AWS, nella regione scelta: abilitare l'accesso ai modelli da usare e creare una chiave API di Bedrock.
2. Scrivere in `backend/.env` dell'istanza `BEDROCK_API_KEY`, `BEDROCK_REGION`, `BEDROCK_MODELS` (e `BEDROCK_CLEARANCE` se diverso da `public`).
3. Ricreare il backend (`up -d backend`: `restart` non rilegge `.env`).

## 8. Punti aperti

- **Quali modelli.** Dipende da cosa accetta le Chat Completions nella regione scelta: si decide con la chiave in mano.
- **Ragionamento sui modelli cloud.** I profili di `reasoning.py` sono dei modelli locali; per ogni modello cloud va scritto il suo.
- **Cache del prompt.** Cambiare provider a metà turno la perde; sul cloud ha un prezzo diverso. Da guardare in P3.
- **Embedding tramite provider.** Da valutare con tre numeri: qualità del richiamo rispetto al modello locale sulle suite di memoria, costo di ricalcolare tutta la memoria a ogni cambio di modello, e il fatto che ogni testo della memoria uscirebbe dal homelab (oggi molti sono `private`: non potrebbero).
- **Conservazione dei dati presso il provider.** Da leggere per Bedrock e per OpenRouter prima di alzare un livello ammesso sopra `public`.
