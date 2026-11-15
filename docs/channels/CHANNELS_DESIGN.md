# Canali di interazione: design

**Data:** 15 novembre 2026
**Stato:** decisioni del maintainer prese il 14/11/2026 ([sezione 3](#3-decisioni)). C0 (interfaccia) costruita il 15/11/2026 ([sezione 7](#7-c0-come-è-stata-costruita)).
**Contesto:** oggi l'agente si raggiunge solo dalla Web UI e risponde solo quando gli si scrive. L'obiettivo è un'interfaccia unica per i canali (Telegram per primo, poi notifiche, voce, schermi, occhiali), con la regola di sensibilità applicata a tutto ciò che esce verso un canale ([SENSITIVITY_DESIGN.md](../sensitivity/SENSITIVITY_DESIGN.md)).

---

## 1. In breve

- **Un canale è un adattatore** davanti al turno che esiste già: trasforma un messaggio in arrivo in un turno su una conversazione, consegna la risposta, rende le richieste di approvazione e consegna le notifiche che l'agente avvia. Dichiara cosa sa fare (lunghezza del testo, formattazione, pulsanti, tipi di input, livello ammesso), e l'agente adatta la risposta.
- **Ogni canale è una destinazione** della regola di sensibilità (`Destination(kind="channel")`). Una risposta che supera il livello del canale non parte: al suo posto arriva un avviso con il link alla conversazione nella Web UI, oppure, per Telegram e `private`, un pulsante che chiede conferma.
- **La conversazione è la stessa**: una chat di Telegram è legata a un thread, che si apre anche dalla Web UI (`/c/<id>`).
- **Telegram per primo**, con long polling: nessuna porta aperta verso l'esterno.

## 2. Cosa c'è oggi

Verificato sul ramo `dev` il 15/11/2026.

| Cosa | Dove | Nota per i canali |
| :--- | :--- | :--- |
| Avvio di un turno | `POST /v1/invoke_stream` → `run_agent_flow_stream` (`api/agent_runner.py`) | Mescola HTTP ed esecuzione; il lavoro vero gira in un thread con una `StreamSession`, già indipendente dal trasporto |
| Eventi del turno | `StreamSession.put/broadcast/subscribe` (`agent/stream_session.py`): `reasoning`, `content`, `metrics`, `retrieval`, `approval_required`, `status`, `final`, `error` | Più sottoscrittori ricevono gli stessi eventi: un canale è un sottoscrittore in più. Le parti in streaming non portano l'etichetta: si conosce solo con `final` |
| Risposta finale | `ChatResponse` (`api/schemas.py`): testo Markdown, traccia, `sensitivity`, campi dell'approvazione | Nessun campo per file o immagini; nessuna versione breve o parlata |
| Approvazioni | Il loop salva un checkpoint e chiude il turno con `final` (`approval_required: true`); `POST /v1/approvals/{id}/resolve` con `approve`, `approve_thread`, `approve_always`, `deny` e `resolved_by` libero; il turno riprende in background | Scadenza 300 s per la chat: troppo poco per una risposta da telefono |
| Autenticazione | Una sola `X-API-Key` condivisa, nessuna identità | Un canale autentica i suoi utenti a modo suo (Telegram: id numerico dell'utente) |
| Uscita verso un client | Nessun controllo: chi ha la chiave riceve tutto | Va aggiunto per i canali, non per la Web UI (che sta in LAN o su Tailscale) |
| Notifiche | `NotificationPolicy` (`on_success`, `on_failure`, `on_approval_needed`, `channels`, `destination_webhook`) nelle automazioni | Dichiarata e salvata, **mai letta**: oggi l'agente non avvisa nessuno |
| Immagini in arrivo | `POST /v1/upload`, poi data URL in `images` della richiesta | Una foto da Telegram segue la stessa strada |

Trovati durante la lettura, da correggere a parte: `StreamSession` dichiara `tool_used`, `execution_trace` e `plan_*` ma nessuno li scrive (lo `sync` li manda sempre vuoti); la Web UI ignora gli eventi `approval_required` e `status` (usa `final`).

## 3. Decisioni

Prese dal maintainer il 14/11/2026.

| # | Domanda | Decisione |
| :--- | :--- | :--- |
| 1 | Bot di Telegram | Lo crea il maintainer con BotFather, scrive il token nel `.env` dell'istanza e indica gli utenti Telegram ammessi |
| 2 | Livello dei dati verso Telegram | `internal` al massimo; `private` solo con una conferma. I messaggi passano dai server di Telegram e le chat dei bot non sono cifrate end-to-end |

## 4. Il design

### 4.1 L'interfaccia

Un pacchetto `app/channels/`:

| Pezzo | Cosa fa |
| :--- | :--- |
| `Channel` (classe base) | `id` (`"telegram"`), `capabilities`, `destination()` (la `Destination` con il suo livello), `start()`/`stop()` (il ciclo che riceve), `deliver(chat, message)`, `ask_approval(chat, request)`, `notify(chat, notification)` |
| `Capabilities` | Lunghezza massima di un messaggio, formattazione (Markdown, HTML, testo), pulsanti sì/no, input accettati (testo, foto, voce), stile della risposta da chiedere al modello (per esempio "breve, niente tabelle"), livello ammesso |
| `ChannelHub` | Registra i canali configurati e li avvia con l'applicazione (lifespan di FastAPI); un canale senza credenziali non parte |
| `start_turn(...)` (in `api/agent_runner.py`) | L'avvio del turno senza la parte HTTP, estratto da `run_agent_flow_stream`: lo usano la Web UI e i canali. Restituisce la `StreamSession` |
| `channel_threads` (tabella) | `(channel, chat_id) → thread_id` corrente, con data. Una chat nuova crea un thread nuovo; `/nuova` ne apre un altro |

Il turno sa da quale canale arriva (`channel` nello stato iniziale): la risposta del modello riceve lo stile del canale (una riga nel prompt della risposta), e le richieste di approvazione nate da quel turno ricevono la scadenza del canale.

### 4.2 Un messaggio in arrivo

1. Il canale riconosce l'utente. Telegram: l'id numerico deve stare in `TELEGRAM_ALLOWED_USERS`; gli altri messaggi vengono ignorati e contati, senza salvarne il testo.
2. Testo come lo scrive l'utente: etichetta della richiesta come oggi (pubblico salvo il livello della conversazione e i rilevatori). Un **messaggio inoltrato** (Telegram lo dice) è testo scritto da altri: entra come non attendibile, come una pagina web.
3. Foto: scaricata dal canale e passata come immagine della richiesta. Voce: trascritta dal servizio Whisper che esiste già, poi trattata come testo (fase C4).
4. `start_turn` sul thread della chat. Se il thread ha già un turno in corso, il messaggio non viene salvato e il canale risponde "c'è già un turno in corso: /stop per fermarlo" (oggi la Web UI in quel caso salva il messaggio e si aggancia al turno: per un canale è confuso).
5. Comandi: `/nuova` (conversazione nuova), `/stop` (ferma il turno), `/link` (link alla conversazione nella Web UI).

### 4.3 La risposta

1. Il canale si iscrive alla sessione e aspetta `final`; intanto mostra "sta scrivendo". Lo streaming parola per parola su Telegram (modificando il messaggio) è un miglioramento successivo: le parti in streaming non hanno etichetta, quindi andrebbero trattenute comunque fino a `final`.
2. **Controllo di sensibilità**: `can_flow(final.sensitivity, canale.destination())`.
   - Consentito: il testo viene reso nel formato del canale (Markdown → HTML di Telegram; tabelle e codice in blocchi monospazio; diviso in più messaggi oltre la lunghezza massima; oltre una soglia, l'inizio più il link alla Web UI).
   - `private` su Telegram (decisione 2): arriva "La risposta contiene dati privati" con due pulsanti, **Mostra qui** e **Apri nell'app**. "Mostra qui" invia il testo e finisce nell'audit come uscita di dati approvata verso `channel:telegram`.
   - `secret`, o un livello che il canale non ammette nemmeno con conferma: solo l'avviso e il link.
3. Ogni messaggio inviato a un canale è un'uscita di dati e va nella vista delle uscite (destinazione, etichetta, esito), come le chiamate ai tool.

### 4.4 Approvazioni

- Una richiesta nata da un turno del canale arriva come messaggio con il tool, un'anteprima accorciata degli argomenti, il motivo del rischio e i pulsanti **Approva**, **Per questa chat**, **Rifiuta**. "Sempre" resta solo nella Web UI: un permesso permanente si dà dove si vede tutta la richiesta.
- Anche la richiesta è un'uscita: l'anteprima mostra argomenti scritti dal turno, quindi passa lo stesso controllo della risposta (l'etichetta del turno in quel momento). Se non può partire, il messaggio dice solo "serve una conferma" con il link.
- Il pulsante chiama la stessa risoluzione della Web UI con `resolved_by = "telegram:<id utente>"`; il canale si iscrive al turno che riprende e consegna il risultato.
- **Scadenza**: per le richieste nate da un canale 30 minuti invece di 5 (da confermare con l'uso).
- Le regole della decisione 6 valgono come nella Web UI: il motivo della richiesta dice quali parole vengono da contenuto esterno.

### 4.5 Notifiche (l'agente scrive per primo)

- `NotificationPolicy` viene finalmente letta: alla fine di una run (successo o errore) e quando una run aspetta un'approvazione, il runner chiama `ChannelHub.notify(policy.channels, ...)`.
- Il contenuto passa lo stesso controllo: una notifica su una run privata dice "la run X è finita" con il link, senza il risultato.
- L'approvazione di una run si dà dal canale con gli stessi pulsanti (la scadenza delle run resta 24 ore).
- Il destinatario è l'utente ammesso (oggi il sistema ha un solo utente); `destination_webhook` resta per dopo.

### 4.6 Configurazione

Variabili di `backend/.env` (anche in `.env.example`, senza valori):

| Variabile | Contenuto |
| :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | Token del bot (vuoto: canale spento) |
| `TELEGRAM_ALLOWED_USERS` | Id numerici degli utenti ammessi, separati da virgola (obbligatoria con il token: senza, il canale non parte) |
| `TELEGRAM_CLEARANCE` | Livello che passa senza conferma: `public` o `internal` (default `internal`) |
| `WEB_UI_URL` | Indirizzo della Web UI per i link (è un indirizzo dell'installazione: sta nel `.env`, non nel codice) |

Il backend deve raggiungere `api.telegram.org` in uscita. Il client HTTP è codice del backend, non un tool: non passa dagli host ammessi di S0, e l'unica cosa che esce è ciò che il controllo del canale consente.

### 4.7 Sicurezza

- Chi controlla il token controlla il bot: il token sta solo nel `.env` dell'istanza.
- Un account Telegram compromesso dell'utente ammesso può dare comandi all'agente come la Web UI: per questo "Sempre" non si concede dal canale, e la modalità di sicurezza dei turni da canale è `normal` fissa (non `dangerous`).
- I messaggi inoltrati e le foto di altri entrano come contenuto non attendibile.

## 5. Ordine di costruzione

| Fase | Contenuto | Serve il maintainer? |
| :--- | :--- | :--- |
| **C0. Interfaccia** | `start_turn` estratto, pacchetto `channels`, tabella `channel_threads`, destinazione `channel:*` nella regola di sensibilità, un canale finto nei test che riceve e risponde | No |
| **C1. Telegram, testo** | Long polling, utenti ammessi, risposta con il controllo e il pulsante per `private`, `/nuova`, `/stop`, `/link` | Per la prova vera: il token e il proprio id utente |
| **C2. Approvazioni** | Pulsanti, risoluzione, ripresa del turno, scadenza del canale | Come C1 |
| **C3. Notifiche** | `NotificationPolicy` letta dal runner, notifiche di fine run e di approvazione in attesa | Come C1 |
| **C4. Foto e voce** | Foto come immagini della richiesta; note vocali trascritte da Whisper | Indirizzo del servizio Whisper nel `.env` |
| **C5. Altri canali** | Push self-hosted, endpoint OpenAI-compatibile per Home Assistant, voce | Dopo una misura dei tempi della voce (brief 05) |

## 6. Punti aperti

- **Streaming su Telegram** (modificare il messaggio man mano): vale la pena solo se l'attesa di `final` si rivela lunga nell'uso.
- **Scadenza delle approvazioni da canale**: 30 minuti è una stima.
- **Più utenti**: oggi il sistema ne ha uno solo; con più utenti servono un'identità vera nel backend (D5) e un legame utente-canale.
- **Link alla Web UI da fuori casa**: funzionano su Tailscale; senza, il pulsante "Apri nell'app" non porta da nessuna parte.

## 7. C0 come è stata costruita

Il 15/11/2026, su `dev`.

- **`start_turn`** ([agent_runner.py](../../backend/app/api/agent_runner.py)): l'avvio del turno senza la parte HTTP; la route di streaming lo usa e aggiunge solo l'SSE. Riceve `channel` (forza `security_mode="normal"`), `extra_tag` (contenuto scritto da altri) e `style_hint`. Anche `stop_turn` è separato dalla route.
- **Pacchetto [`channels/`](../../backend/app/channels/)**: `base.py` (capacità, messaggi, canale), `threads.py` (tabella `channel_threads` nel database delle conversazioni), `render.py` (divisione alla lunghezza del canale senza rompere i blocchi di codice, versione in testo semplice; l'HTML arriva con C1), `hub.py` (comandi, rifiuto con turno in corso, attesa della risposta con scadenza, controllo di sensibilità, risposte trattenute).
- **Controllo**: una risposta senza etichetta vale `private`. Le risposte trattenute per "Mostra qui" stanno in memoria per 10 minuti (al massimo 100): un riavvio le perde. "Mostra qui" vale una volta, solo per la chat a cui era destinata, e ricontrolla la regola.
- **Registro delle uscite**: ogni consegna di una risposta del modello va nell'audit come `channel_delivery`, con destinazione `channel:<id>`, etichetta ed esito (`allow`, `ask` per l'avviso con "Mostra qui", `approved`, `deny`), quindi compare nella vista delle uscite di dati. Il testo della risposta non viene salvato, solo la sua lunghezza.
- **Stile**: la riga di stile del canale arriva alle chiamate con ruolo `answer`. Limite noto: quando il modello scrive la risposta finale già nella chiamata di scelta del tool, quella riga non la vede.
- **Avvio**: l'hub parte e si ferma con l'applicazione; senza canali registrati non fa nulla (così è oggi su CT 125).
- **Verifica**: 55 test con un canale finto; 26 mutazioni colte su 26. Non provato con un turno vero (i test sul modello locale sono sospesi).

