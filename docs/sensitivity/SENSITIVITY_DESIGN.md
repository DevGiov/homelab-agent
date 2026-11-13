# Sensibilità dei dati: design

**Data:** 13 novembre 2026
**Stato:** decisioni prese il 13/11/2026 ([sezione 10](#10-decisioni)). Fasi S0 e S1 costruite lo stesso giorno ([9.1](#91-s0-come-è-stata-costruita), [9.2](#92-s1-come-è-stata-costruita)); S2-S4 non iniziate.
**Contesto:** oggi ogni chiamata a un modello resta su un server locale. Prima di aggiungere un provider cloud, un agente di coding esterno o un canale di chat su un servizio di terzi serve una regola, applicata dal codice, che dica quali dati possono andare dove.

Il documento descrive cosa esce oggi dal backend (verificato sul codice del ramo `dev`), il modello proposto (un'etichetta su ogni dato, un livello ammesso per ogni destinazione, un solo controllo), dove si aggancia al codice esistente e in che ordine costruirlo.

---

## 1. In breve

- Ogni dato che entra nel contesto di un modello ha un'**etichetta di sensibilità** tra quattro: `public`, `internal`, `private`, `secret`.
- Ogni destinazione fuori dal processo (un provider di modelli, il motore di ricerca, un tool, un canale) ha un **livello ammesso**: l'etichetta più alta che può ricevere.
- Una funzione sola, `can_flow(etichetta, destinazione)`, decide. È codice ordinario fuori dal modello, come il blocco dei comandi distruttivi che esiste già: il modello non può aggirarla a parole.
- Ciò che un modello scrive eredita l'etichetta più alta di ciò che ha letto. Vale anche per gli argomenti di un tool: una query di ricerca scritta da una chiamata che aveva in contesto un fatto privato è privata.
- Un flusso negato ha tre esiti, in quest'ordine: eseguire il passo su una destinazione che può ricevere il dato (il modello locale), chiedere all'utente mostrando il testo esatto che uscirebbe, oppure proporre una versione ripulita.
- Accanto alla sensibilità viaggia un secondo attributo, la **fiducia**: il testo che arriva dal web, da un'email o da un webhook non può dare ordini. Si progetta insieme perché usa lo stesso meccanismo.

**Cosa non garantisce.** Un modello può parafrasare un dato privato in un testo dall'aria innocua: l'etichetta lo segue comunque, perché si propaga per provenienza e non per contenuto, ma una versione "ripulita" scritta da un modello resta un'approssimazione. Il numero e il tipo di chiamate ai tool possono rivelare qualcosa. I sistemi che danno garanzie formali ristrutturano l'intero agente attorno a due modelli separati: qui si sceglie un controllo semplice e verificabile, e la separazione tra chi pianifica e chi legge resta il passo successivo se servirà.

## 2. Cosa esce oggi dal backend

Verificato il 13/11/2026 leggendo `backend/app`. I nomi di file sono relativi a quella cartella.

### 2.1 Punti di passaggio

| Punto | Dove | Cosa ci passa | Cosa sa fare oggi |
| :--- | :--- | :--- | :--- |
| Chiamata a un modello | `LLMProvider.chat` in `llm/providers.py` | Tutte le chiamate tranne una ([2.3](#23-flussi-che-saltano-i-punti-di-passaggio)). `agent/llm_calls.py` (`call_llm`, `call_llm_structured`) è il percorso comune del grafo, ma il router (`agent/mode_router.py`, `_ask_router_model`) e il titolo del thread (`memory/thread_store.py`, `generate_and_save_title`) chiamano il provider direttamente | Registra durata e token (`record_llm_call`). Non vede da dove viene il testo |
| Esecuzione di un tool | `ToolRegistryManager.execute_tool` in `registry/manager.py` | Tutti i tool dell'agent loop e delle automazioni | Blocco dei comandi distruttivi, approvazioni, audit (`security/policy.py`, `approvals.py`, `permissions.py`, `audit_log.py`) |
| Ricerca web | `execute_search` in `registry/web_search_service.py` | Il tool `web_search` e il prefetch | Controllo SSRF sugli indirizzi da scaricare (`is_safe_url`), isolamento del contenuto come non attendibile |
| Impostazioni per tool | `mcp/store.py`, tabella `mcp_tool_settings` | Attivo o no, rischio (`auto`, `view`, `confirm`, `blocked`) | Il posto naturale per l'etichetta dei risultati e il livello ammesso di un tool |

Il provider attivo è globale (`get_provider()`): oggi una chiamata non può scegliere una destinazione diversa dalle altre.

### 2.2 Destinazioni esistenti

| Destinazione | Dove | Cosa esce | Chi decide il contenuto | Protezione oggi |
| :--- | :--- | :--- | :--- | :--- |
| Server dei modelli (compatibile OpenAI, oppure Ollama) | `llm/providers.py` | L'intero prompt: richiesta, cronologia, memoria, profilo, risultati dei tool, pagine web, immagini | Codice | Nessuna: è locale per configurazione |
| Motore di ricerca (SearXNG, che inoltra ai motori pubblici) | `registry/search_providers.py`, `search_searxng_api` | La query | Router o modello; in mancanza, **il messaggio dell'utente così com'è** | Nessuna |
| DuckDuckGo, riserva diretta | `search_duckduckgo_html`, `search_duckduckgo_api` | La query | Come sopra | Nessuna |
| Pagine dei risultati | `registry/search_content.py` | L'indirizzo richiesto | Risultati della ricerca | SSRF a ogni redirect |
| `http_get` | `registry/web_search.py` | Indirizzo e intestazioni scelti dal modello | Modello | **Nessuna**: è tra i `VIEW_TOOLS`, quindi parte senza conferma, e non passa dal controllo SSRF |
| `inspect_image` con un indirizzo remoto | `registry/vision.py` | L'indirizzo richiesto | Modello | Nessuna, stesso caso di `http_get` |
| Tool dei server MCP | `registry/mcp.py`, `mcp/hub.py` | Gli argomenti | Modello | Rischio e approvazioni. Nulla dice se il server tiene i dati in casa o li inoltra a un servizio pubblico |
| Feed di calendario (`webcal`) | `calendar/sync.py` | Solo l'indirizzo del feed, scelto dall'utente | Utente | Nessuna necessaria |
| Sandbox del codice | `registry/code_exec.py` | Il codice scritto dal modello | Modello | Approvazione se la sandbox manca. **Da verificare** se la sandbox ha accesso alla rete |
| Client dell'utente (API e flusso SSE) | `api/`, `agent/stream_session.py` | Risposte, ragionamento, tracce | Codice | Chiave API |
| Log del processo | Vari `logger.info` | Query, comandi, output strutturati dei modelli (una ventina di righe di log includono contenuto) | Codice | Restano sulla macchina; diventano un'uscita il giorno che i log vengono spediti altrove |

Non sono uscite di dati: gli embedding (calcolati nel processo, `memory/vector_store.py`), i controlli di salute e gli eventi dei modelli (nessun dato dell'utente), la posta (`registry/email_tool.py` legge soltanto, le bozze restano locali e l'invio non esiste), la scrittura su calendari remoti (prevista dallo schema, non implementata).

### 2.3 Flussi che saltano i punti di passaggio

| Flusso | Perché conta |
| :--- | :--- |
| `inspect_image` chiama il server dei modelli con una richiesta HTTP propria (`registry/vision.py`, `requests.post`), senza passare da `LLMProvider.chat` | È l'unica chiamata a un modello che un controllo nel provider non vedrebbe. Usa sempre l'indirizzo del server locale, anche con un altro provider attivo |
| Il prefetch chiama `execute_search` direttamente (`agent/nodes/web_prefetch.py`) | La query non passa dal gestore dei tool: nessuna riga di audit, nessun guardrail |
| `http_get` e `inspect_image` scaricano un indirizzo scelto dal modello senza conferma e senza controllo SSRF | È la via d'uscita più ampia che esiste oggi: qualunque dato in contesto può finire nella query string o in un'intestazione di una richiesta verso un host arbitrario. È anche una via d'ingresso verso la rete locale |
| La modalità `safest` esenta `web_search` dalla conferma (`security/policy.py`, `enforce_guardrails`) | Coerente con il rischio di danno, non con il rischio di uscita dei dati |
| `GET /v1/uploads/{filename}` non chiede la chiave API (`api/routes/uploads.py`) | Le immagini caricate sono leggibili da chi conosce il nome del file (un identificatore casuale). Da tenere presente quando un'immagine sarà etichettata `private` |

I primi tre vanno corretti comunque, prima e a prescindere dalle etichette ([fase S0](#9-ordine-di-costruzione)). **Chiusi dalla fase S0 il 13/11/2026**, insieme a un quarto trovato strada facendo: `inspect_image` leggeva qualunque file locale del container ([9.1](#91-s0-come-è-stata-costruita)).

### 2.4 Ordine del grafo, rilevante per le etichette

`intake → recent_turns → mode_router → retrieve_memory → web_prefetch → (chat | ask | act | plan) → respond`

Il router decide la query del prefetch **prima** che la memoria sia letta: vede il messaggio dell'utente e gli ultimi 4 messaggi del thread, non il profilo né i fatti. È una proprietà utile e va conservata: una query scritta lì non può contenere ciò che sta solo in memoria.

## 3. Etichette

Quattro, ordinate. Ogni livello in più è una decisione che l'utente dovrebbe prendere spesso: quattro bastano a distinguere i casi che due non coprono (un segreto che nessun modello deve vedere; codice personale che può andare a un provider scelto ma non in una query di ricerca).

| Etichetta | Significato | Esempi |
| :--- | :--- | :--- |
| `public` | Potrebbe stare online | Domande generali, documentazione pubblica, risultati di una ricerca |
| `internal` | Mio, ma può andare a un provider che ho scelto | Codice di progetti personali, stato dell'infrastruttura senza segreti |
| `private` | Solo modelli locali | Memoria su persone, posta, calendario, conversazioni, salute, finanze, lavoro |
| `secret` | Nessun modello | Credenziali e token. Li gestisce già lo store cifrato delle integrazioni |

**Fiducia.** Ogni dato porta anche un attributo a due valori, `trusted` o `untrusted`. Non attendibile è tutto ciò che è stato scritto da altri e arriva senza che l'utente lo abbia letto: pagine web, corpo delle email, payload dei webhook, eventi di un feed esterno, testo dentro un'immagine, risultati di un tool che interroga fonti pubbliche. Il contenuto web è già marcato così (`wrap_untrusted_web_evidence`): la proposta estende lo stesso trattamento alle altre fonti e ne tiene traccia nell'etichetta.

In codice, un valore solo che si combina prendendo il massimo:

```python
class Label(IntEnum):
    PUBLIC = 0; INTERNAL = 1; PRIVATE = 2; SECRET = 3

@dataclass(frozen=True)
class Tag:
    label: Label
    untrusted: bool = False
    reasons: tuple[str, ...] = ()   # da dove viene: "memory.fact:42", "tool:email_fetch_unread", "user.floor"

def join(*tags: Tag) -> Tag: ...     # etichetta massima, untrusted se uno lo è, unione dei motivi
```

I motivi servono a spiegare all'utente perché una conversazione è riservata, e all'audit.

## 4. Da dove vengono le etichette

Tre fonti, in ordine di affidabilità. Solo le prime due sono deterministiche.

### 4.1 La sorgente

| Sorgente | Dove sta | Etichetta predefinita | Fiducia | Dove salvare l'etichetta |
| :--- | :--- | :--- | :--- | :--- |
| Messaggio scritto dall'utente | `thread_messages` | Il **livello della conversazione** ([4.3](#43-lutente)), `public` se l'utente non lo cambia | `trusted` | Nuova colonna `sensitivity` del messaggio |
| Immagine o file caricato | cartella degli upload | Come il messaggio che lo allega | `untrusted` per il testo che contiene | Con il messaggio |
| Risposta dell'assistente | `thread_messages` | Quella della chiamata che l'ha scritta | Come la chiamata | Colonna `sensitivity` |
| Riassunto del thread | `thread_summaries` | La più alta tra i messaggi coperti | | Nuova colonna |
| Profilo dell'utente | `memory/profile.py` | `private` | `trusted` | Fissa |
| Fatti ed entità | `vec_memory`, `memory_entities` | `private`; l'utente può abbassare un singolo fatto | `trusted` | `metadata_json` del fatto (esiste già) |
| Episodi e procedure | `vec_memory` (`kind='episode'`, `'procedure'`) e tabella `procedures` | Quella del turno da cui nascono | | `metadata_json` del record; nuova colonna in `procedures` |
| Documento della knowledge base | `vec_memory`, record `kind='kb'` | Scelta al caricamento, `internal` se non indicata | `trusted` (lo carica l'utente) | `metadata_json` dei chunk |
| Posta | IMAP, `email_fetch_unread` | `private` | `untrusted` | Regola del tool |
| Calendario | `calendar/db.py` | `private` | `untrusted` per gli eventi di un feed esterno | Regola del tool |
| Risultato di un tool MCP | | Per tool, nelle impostazioni ([4.4](#44-tool-mcp)) | Per tool | `mcp_tool_settings` |
| Ricerca web e pagine | | `public` | `untrusted` | Fissa |
| Payload di un webhook | automazioni | `internal` | `untrusted` | Fissa |
| Segreti delle automazioni e delle integrazioni | store cifrato | `secret` | | Fissa: non entrano in un prompt |

### 4.2 I rilevatori

Possono solo **alzare** un'etichetta, mai abbassarla. Girano sul messaggio dell'utente e sui risultati dei tool.

| Rilevatore | Porta a | Note |
| :--- | :--- | :--- |
| Chiavi e token (prefissi noti, PEM, stringhe ad alta entropia dopo `key=`, `token=`, `password=`) | `secret`: il tratto viene sostituito con `[RIMOSSO: chiave]` prima di entrare nel contesto | Nel risultato di un tool; nel messaggio dell'utente si avvisa invece di cancellare |
| IBAN, codice fiscale, numeri di carta, numeri di telefono, indirizzi email | `private` | Espressioni regolari con controllo della cifra di verifica dove esiste |
| Nomi delle entità di tipo `person` della memoria | `private` | La lista viene da `memory_entities`: il sistema conosce già le persone di cui l'utente ha parlato |
| Indirizzi di reti private e nomi host locali | `internal` | Riusa `is_private_address` di `search_security.py` |

Un rilevatore sbaglia in entrambe le direzioni. Per questo non è l'unica difesa (la sorgente e l'utente vengono prima) e ogni suo intervento è visibile nei motivi dell'etichetta.

### 4.3 L'utente

- **Livello della conversazione.** Un selettore accanto alle opzioni esistenti (ricerca web, incognito): `public` (predefinito), `internal`, `private`. È il livello minimo di tutto ciò che l'utente scrive in quel thread. Il sistema non può sapere che una frase è privata se nessuno glielo dice: questo è il modo di dirlo.
- **Incognito** resta un'altra cosa: non salva. Una conversazione può essere privata e salvata, o pubblica e in incognito.
- **Un fatto della memoria** si può marcare `internal` o `public` dalla vista Memoria, uno alla volta.
- **Declassare** una conversazione che ha raggiunto `private` è possibile solo all'utente, con una conferma, ed è una riga di audit.

### 4.4 Tool MCP

Ogni tool ha due valori nuovi in `mcp_tool_settings`, accanto a `risk`:

- `result_label`: l'etichetta dei suoi risultati, e se sono `untrusted`;
- `clearance`: il livello ammesso dei suoi argomenti ([sezione 6](#6-destinazioni)).

Entrambi hanno un valore per server, che l'utente imposta una volta, e l'eccezione per tool. Un server appena aggiunto parte dal valore più stretto: risultati `private`, argomenti ammessi fino a `public`. È scomodo per un server che gira in casa, ed è voluto: il sistema non può sapere se un server MCP inoltra altrove ciò che riceve, e la domanda va fatta a chi lo aggiunge.

Valori di partenza sensati per le famiglie di tool esistenti: stato dell'infrastruttura `internal`; output di comandi e log `private` (possono stampare qualunque cosa, e i rilevatori ne tolgono i segreti); risultati di ricerche su fonti pubbliche `public` e `untrusted`.

## 5. Propagazione

**Regola.** L'etichetta di una chiamata a un modello è la più alta tra le parti del suo prompt. Ciò che la chiamata scrive ha la stessa etichetta. Un dato salvato conserva l'etichetta con cui è stato scritto.

**Per chiamata, non per conversazione.** Se un solo fatto privato costringesse tutto il thread sul modello più debole, l'utente spegnerebbe la protezione. Le chiamate di un turno vedono cose diverse:

| Chiamata | Cosa vede | Etichetta tipica |
| :--- | :--- | :--- |
| Router (`_ask_router_model`) | Messaggio dell'utente, ultimi 4 messaggi | Quella del messaggio e di quei messaggi |
| Query per immagine (`formulate_visual_search_query`) | Messaggio e immagine | Come sopra |
| Selezione del tool, pianificazione | Richiesta, memoria, prefetch, osservazioni | Sale con la memoria e con ogni risultato letto |
| Sintesi finale | Tutto | La più alta del turno |
| Titolo del thread | Il primo messaggio | Quella del messaggio |
| Riassunto, consolidamento, estrazione dei fatti, distillazione | Messaggi del thread, fatti correlati | Quasi sempre `private` |

**Dove vive lo stato.** Non in una variabile di contesto: i tool in parallelo girano in un pool di thread che non la erediterebbe (`execute_tools_parallel`). L'etichetta si passa in modo esplicito:

- `AgentState` (stato del grafo) riceve un campo `tag`, alzato da ogni nodo che legge una sorgente: `recent_turns`, `retrieve_memory`, `web_prefetch`.
- `AgentLoop` tiene il proprio `tag`, lo alza a ogni osservazione (`_observe`) e lo include nel checkpoint (`_PROGRESS_FIELDS`), così un turno ripreso dopo un'approvazione non lo perde.
- `LLMProvider.chat` e `call_llm` ricevono un parametro `tag` **senza valore predefinito**. Una chiamata che non lo passa non parte: ogni punto del codice che invia testo a un modello deve dichiarare che cosa sta inviando, e i test lo verificano per costruzione.
- `execute_tool` riceve il `tag` della chiamata che ha scritto gli argomenti e restituisce, con il risultato, il `tag` del risultato.

**Argomenti dei tool.** Sono testo scritto da un modello, quindi portano l'etichetta della chiamata che li ha prodotti. È la regola che ferma l'uscita più realistica: il modello che, avendo in contesto un fatto su una persona, lo mette in una query di ricerca.

**Persistenza.** Il messaggio dell'assistente salva l'etichetta del turno. Al turno successivo la cronologia rientra con le etichette dei messaggi che contiene: una conversazione che ha toccato un dato privato resta privata finché quei messaggi sono nella finestra o nel riassunto.

## 6. Destinazioni

```python
@dataclass(frozen=True)
class Destination:
    id: str            # "provider:llamacpp", "search:web", "http:internet", "mcp:<server>", "channel:<nome>"
    kind: str          # model | search | http | mcp | sandbox | channel
    clearance: Label   # l'etichetta più alta che può ricevere
```

| Destinazione | Livello ammesso di partenza | Come si stabilisce |
| :--- | :--- | :--- |
| Provider di modelli locale | `private` | Impostazione **esplicita** del provider. Non si deduce dall'indirizzo: un indirizzo di rete locale può essere un proxy verso un servizio cloud |
| Provider di modelli cloud | `internal` | Per provider. L'utente può alzarlo per uno specifico, mai in automatico |
| Ricerca web (SearXNG e riserva) | `public` | Fisso |
| Scaricamento di un indirizzo (`http_get`, pagine, immagini remote) | `public` verso internet; `private` verso gli host elencati in una lista di host locali ammessi | Dall'host dell'indirizzo, con la stessa risoluzione DNS del controllo SSRF |
| Tool di un server MCP | Per server e per tool ([4.4](#44-tool-mcp)) | Impostazione |
| Sandbox del codice | `private` se senza rete, altrimenti `public` | Da verificare |
| Client dell'utente | `private` | Fisso |
| Canale di chat su servizio di terzi (futuro) | `internal` | Per canale |
| Canale ospitato in casa (futuro) | `private` | Per canale |
| Agente di coding esterno (futuro) | `internal`, e per repository | Per agente |

Nessuna destinazione ha livello `secret`: un segreto raggiunge un tool solo attraverso il meccanismo esistente delle automazioni (`secrets_whitelist`, `run_secrets.py`), che lo inserisce negli argomenti senza mostrarlo al modello. Resta fuori da questo design.

## 7. Il controllo

```python
def can_flow(tag: Tag, dest: Destination) -> Decision:
    """Pura e senza effetti: allow, oppure deny con il motivo e i `reasons` dell'etichetta."""
```

Un modulo nuovo, `security/flows.py`, con `Label`, `Tag`, `join`, `Destination`, il registro delle destinazioni e `can_flow`. Quattro punti di chiamata:

| Dove | Cosa controlla | Se negato |
| :--- | :--- | :--- |
| `LLMProvider.chat` | `tag` del prompt verso il provider | Errore `FlowDenied`. Non deve succedere: è la rete di sicurezza. La scelta giusta avviene prima, quando si sceglie il provider per quell'etichetta |
| `ToolRegistryManager.execute_tool` | `tag` degli argomenti verso la destinazione del tool (per `http_get` dipende dall'host) | Richiesta di approvazione di tipo "uscita di dati" |
| `execute_search` | `tag` della query verso `search:web` | Dal tool: come sopra. Dal prefetch: [7.2](#72-il-prefetch-web) |
| Adattatore di un canale (futuro) | `tag` del messaggio verso il canale | Il messaggio non parte; resta un avviso generico |

Ogni decisione negata e ogni autorizzazione dell'utente finiscono nell'audit. `audit_log` riceve le colonne `label`, `destination` e `flow`; `llm_calls` (metriche) riceve `label` e `destination`, così le valutazioni possono controllare le chiamate registrate.

### 7.1 I tre esiti di un flusso negato

1. **Eseguire altrove.** Vale per le chiamate ai modelli: il passo gira su un provider il cui livello ammesso basta. Richiede che il provider si scelga per chiamata (`get_provider_for(tag, ruolo)`) invece che una volta per tutte: è il punto di contatto con la scelta dei modelli per ruolo.
2. **Chiedere.** Vale per i tool e per la ricerca, che non hanno un equivalente locale. La scheda di approvazione mostra il **testo esatto** che uscirebbe e la destinazione ("Questa ricerca invierebbe ai motori pubblici: «…»"), con gli ambiti esistenti: una volta, per questa conversazione, sempre. È un tipo di approvazione distinto da quello dei comandi: aver autorizzato "sempre" `web_search` come tool non autorizza a metterci dentro dati privati.
3. **Ripulire.** Il modello locale riscrive il testo senza le parti private e l'utente vede il risultato prima dell'invio. È il meno affidabile dei tre, perché la pulizia la fa un modello: arriva per ultimo e mai senza conferma.

### 7.2 Il prefetch web

| Situazione | Comportamento proposto |
| :--- | :--- |
| Conversazione `public`, query scritta dal router da messaggi `public` | Come oggi |
| Il router non produce una query | Oggi parte il messaggio dell'utente così com'è. Resta ammesso solo se il messaggio è `public` |
| Query con etichetta sopra `public` (livello della conversazione alzato, rilevatore scattato, ultimi messaggi privati) con ricerca in `auto` | Nessun prefetch. L'interfaccia lo dice: "ricerca non eseguita: la conversazione contiene dati riservati" |
| Come sopra, con ricerca in `on` | Scheda di approvazione con la query, prima dell'invio |

Il prefetch passa dallo stesso controllo del tool e scrive la sua riga di audit, chiudendo il secondo flusso di [2.3](#23-flussi-che-saltano-i-punti-di-passaggio).

### 7.3 Contenuto non attendibile

La combinazione pericolosa è un agente che ha dati privati, legge contenuto scritto da altri e ha un modo di far uscire dati. La regola di sensibilità copre già l'uscita: con un dato privato in contesto, una richiesta verso internet viene negata o chiesta, chiunque l'abbia suggerita. L'attributo `untrusted` aggiunge tre cose:

- la scheda di approvazione avverte quando il testo da inviare è stato scritto dopo la lettura di contenuto non attendibile;
- le autorizzazioni "per questa conversazione" e "sempre" di tipo "uscita di dati" **non valgono** in un turno che ha letto contenuto non attendibile: si chiede di nuovo;
- per i comandi pre-approvati che modificano qualcosa, l'idea era la stessa: dopo aver letto una pagina web o un'email, un comando di scrittura torna a chiedere conferma anche se il suo prefisso era nella lista dei permessi.

Il terzo punto **resta da valutare** (decisione 6). L'obiezione del maintainer: lo stesso comando può essere innocuo il 99% delle volte; bloccarlo moltiplica le richieste senza garantire che il caso pericoloso venga riconosciuto, perché finisce sommerso tra le altre. Una conferma utile deve essere rara: serve un criterio più stretto del solo "ha letto contenuto non attendibile" (per esempio il comando o i suoi argomenti contengono testo che viene da quel contenuto).

## 8. Cosa vede l'utente

- **Indicatore.** Un'etichetta discreta sulla conversazione quando il livello è `internal` o più alto, con i motivi al passaggio del mouse ("fatto della memoria", "risultato di `email_fetch_unread`"). Quando l'etichetta impedisce qualcosa, il messaggio lo dice nel punto in cui succede.
- **Selettore del livello** nella barra delle opzioni della chat.
- **Scheda "uscita di dati"**, variante della scheda di approvazione esistente: destinazione, testo che uscirebbe, motivi dell'etichetta, avviso se c'è contenuto non attendibile.
- **Memoria:** etichetta per fatto, modificabile. **Knowledge base:** etichetta al caricamento. **Server MCP:** due campi per server e per tool, accanto al rischio.

## 9. Ordine di costruzione

Ogni fase è utile da sola e lascia il sistema funzionante.

| Fase | Contenuto | Effetto per l'utente |
| :--- | :--- | :--- |
| **S0. Chiusura dei flussi scoperti** (fatta il 13/11/2026, [9.1](#91-s0-come-è-stata-costruita)) | `http_get` e `inspect_image`: lista degli host ammessi modificabile dalla UI, conferma per gli host pubblici fuori lista, blocco per quelli locali fuori lista, host dichiarati dalle automazioni. `inspect_image` chiama il modello attraverso `LLMProvider.chat` e legge solo file della directory dei dati. Il prefetch passa dal gestore dei tool, con audit | Una conferma in più per `http_get` verso internet. Indipendente dal resto: sono difetti di oggi |
| **S1. Etichette e controllo, con sole destinazioni locali** (fatta il 13/11/2026, [9.2](#92-s1-come-è-stata-costruita)) | `security/flows.py`; parametro `tag` obbligatorio in `chat` e `call_llm`; etichette alle sorgenti della tabella 4.1; `tag` in `AgentState` e `AgentLoop`; controllo in `execute_tool` e `execute_search`; colonne di audit e metriche; rilevatori | Cambia solo la ricerca: in un turno con dati privati chiede o non parte |
| **S2. Interfaccia** | Indicatore, selettore, scheda "uscita di dati", etichette in Memoria, knowledge base e server MCP | L'utente vede e corregge le etichette |
| **S3. Valutazioni** | Suite `flows` in `app/evals`: un fatto privato con una stringa riconoscibile, un compito che invoglia a cercarlo sul web, un provider finto con livello `internal` che registra ciò che riceve. Passa se la stringa non compare in nessuna uscita registrata | Un numero al posto di un'impressione, da rifare a ogni modello |
| **S4. Prima destinazione non locale** | Scelta del provider per chiamata, secondo etichetta e ruolo | Arriva con il primo provider cloud, non prima |

Test deterministici di S1, oltre a quelli di `can_flow`: ogni tool del catalogo ha una destinazione; ogni chiamata a `chat` passa un `tag` (il parametro obbligatorio lo impone); l'etichetta di una risposta non è mai più bassa di quella di una parte del suo prompt; un turno ripreso dal checkpoint conserva l'etichetta.

**Costo permanente.** Ogni nuova sorgente e ogni nuova destinazione vanno classificate, per sempre. Il design lo rende obbligatorio invece che facoltativo: una sorgente senza etichetta o una chiamata senza `tag` non passa i test.

### 9.1 S0 come è stata costruita

Il modulo è `backend/app/security/network.py`; la lista sta nella tabella `allowed_hosts` di `checkpoints.db`.

| Regola | Dettaglio |
| :--- | :--- |
| Schemi | Solo `http` e `https` |
| Host in lista | Parte senza chiedere, anche se è nella rete locale. Una voce è un nome (`example.com`, solo quello), `*.example.com` (dominio e sottodomini, almeno due livelli) o un indirizzo IP |
| Host della policy dell'automazione | `permission_policy.allowed_hosts`: valgono come in lista, solo durante le run di quell'automazione. Il gestore dei tool li legge dalla definizione a ogni chiamata |
| Host locale fuori lista | Bloccato in ogni modalità, `dangerous` compresa: è la protezione SSRF. Locale = nome di rete locale, IP privato o riservato, o nome che risolve anche su un solo IP privato. Un nome che non si risolve è bloccato |
| Host pubblico fuori lista | Richiesta di approvazione con capability `net:<host>` e anteprima della richiesta (indirizzo completo, intestazioni; i valori di quelle di accesso sono coperti). "Una volta" e "per questa chat" come per gli altri tool; "sempre" aggiunge l'host alla lista (origine "approvazione"). In modalità `dangerous` parte senza chiedere |
| Redirect | Seguiti a mano, al massimo 5. Ogni passo rifà il controllo SSRF; un passo verso un host pubblico fuori lista è ammesso, perché lo sceglie il server. Le intestazioni scelte dal modello non passano a un host diverso |
| Lista predefinita | 18 servizi pubblici usati in lettura (Wikipedia, GitHub, registri di pacchetti, arXiv, documentazione, Open-Meteo...), inseriti una volta sola: una voce tolta non torna, salvo "Ripristina predefiniti". Nessun host di un'installazione |
| `inspect_image` locale | Solo file sotto `DATA_DIR` (upload, artefatti), anche nella forma `/v1/uploads/<nome>`. Prima leggeva qualunque percorso del container |
| Agent loop | `http_get` e `inspect_image` non entrano più nelle chiamate in parallelo (lì un'approvazione non sospende il turno). Un'approvazione in attesa o un blocco non finiscono nella cache dei risultati |
| Prefetch | Passa da `ToolRegistryManager.execute_tool("web_search", …)` con l'argomento interno `detail: "full"`: guardrail, impostazione del tool (un `web_search` bloccato blocca anche il prefetch) e riga di audit. Gli eventi di avanzamento arrivano con `run_with_event_sink` |
| Audit | Le chiamate in parallelo ora portano `automation_id`, `run_id` e `step_run_id` come le altre |

Interfaccia: sezione "Host ammessi" in Impostazioni > Sicurezza; campo degli host nella scheda "Budget & Guardrail" dell'automazione; nelle schede di approvazione di rete il pulsante "sempre" dice che aggiunge l'host. API: `GET/POST /v1/security/allowed-hosts`, `DELETE /v1/security/allowed-hosts/{host}`, `POST /v1/security/allowed-hosts/defaults`.

La lista dice dove si può andare senza chiedere, non che cosa si può mandare: un indirizzo verso un host in lista può portare dati nella query string. Lo copre il controllo delle etichette di S1, che vale anche per gli host in lista.

**Limite noto.** Il controllo risolve il nome prima della richiesta e la richiesta lo risolve di nuovo: un DNS che cambia risposta tra le due (DNS rebinding) può portare a un indirizzo privato. Vale anche per lo scaricamento delle pagine della ricerca, che usa lo stesso controllo. Chiuderlo richiede di collegarsi all'IP verificato, cosa che con HTTPS complica il controllo del certificato: rimandato.

### 9.2 S1 come è stata costruita

Moduli: `backend/app/security/flows.py` (etichette, destinazioni, regole dei tool, `can_flow`) e `backend/app/security/detectors.py` (rilevatori).

**Chiamate ai modelli.** `tag` è obbligatorio in `LLMProvider.chat`, `call_llm`, `call_llm_structured`, `route_turn`, nei passi di pianificazione e nel prefetch: 18 punti del codice, ognuno dichiara che cosa invia. `chat` confronta il tag con il livello ammesso del provider e, se non basta, non parte (`FlowDenied`). Il livello è un'impostazione esplicita: `LLAMA_CPP_CLEARANCE` e `OLLAMA_CLEARANCE`, default `private`; va abbassata a `internal` se l'indirizzo porta a un servizio cloud. `llm_calls` (metriche) registra etichetta e destinazione di ogni chiamata.

**Sorgenti.**

| Sorgente | Etichetta | Dove sta |
| :--- | :--- | :--- |
| Messaggio dell'utente | Livello della conversazione, alzato dai rilevatori | `thread_messages.sensitivity`; il livello in `thread_metadata.sensitivity`, impostato dal campo `sensitivity` della richiesta di chat |
| Risposta dell'assistente, riassunto | Quella del turno; il riassunto la più alta tra i messaggi che copre | `thread_messages.sensitivity`, `thread_summaries.sensitivity` |
| Profilo | `private` | |
| Fatti | `private`, salvo un'etichetta nel fatto | campo `sensitivity` nei metadati |
| Episodi | Quella del turno da cui nascono (`private` per quelli precedenti) | metadati |
| Procedure | `internal` | |
| Documenti della knowledge base | Scelta al caricamento, default `internal` | metadati di ogni pezzo |
| Risultati dei tool interni | Tabella in `flows.py` (memoria e posta `private`, ricerca `public` non attendibile...) | |
| Risultati dei tool MCP | Classificazione del server; output di comandi e log sempre `private` | tabella `mcp_flow_settings` (API `/v1/security/mcp-flows`) |
| Ricerca preventiva, immagini allegate | `public`, non attendibili | |
| Payload di un webhook | `internal`, non attendibile | |

Un server MCP senza classificazione vale come il più stretto: risultati `private`, argomenti solo `public` (decisione 5). La classificazione di un'installazione non sta nel repository.

**Rilevatori.** Sul messaggio dell'utente tutti i tipi (segreti, IBAN, codice fiscale, carte, telefoni, email, nomi delle persone della memoria, indirizzi della rete locale). Un segreto scritto dall'utente porta il messaggio a `private`, non a `secret`: lo vede il modello locale, ma non esce. Sui risultati dei tool solo i tipi che non scattano su output tecnici (segreti, IBAN, codice fiscale, email, persone): telefono e carta davano falsi positivi su byte e uptime. I segreti nei risultati vengono sostituiti da `[RIMOSSO: segreto]` prima di entrare nel contesto.

**Propagazione.** `AgentState.tag` (tutto ciò che il turno ha in contesto) e `routing_tag` (richiesta e ultimi 4 messaggi, ciò che vede il router). `AgentLoop.tag` sale a ogni risultato letto, viaggia con ogni chiamata a un modello e a un tool ed entra nel checkpoint. Lo stesso per l'esecuzione di un piano. Le automazioni ricavano il tag della run da ciò che è salvato: i valori scritti nella definizione sono una scelta dell'autore (`public`); salgono i risultati degli step e il payload di un webhook. La risposta dell'API porta `sensitivity` (etichetta, non attendibilità, motivi).

**Controllo.** Nel `ToolRegistryManager`, dopo i guardrail esistenti. Un flusso negato chiede un'approvazione di tipo "uscita di dati": capability `flow:<destinazione>:<etichetta>`, anteprima del testo che uscirebbe. Vale una volta o per la chat; "sempre" vale per la chat, perché un livello ammesso si alza dalle impostazioni. Il permesso per la chat non vale in un turno che ha letto contenuto non attendibile (decisione 6). Nessuna modalità di sicurezza salta il controllo, `dangerous` compresa. Un segreto è bloccato. Approvare un'uscita verso un URL vale anche come conferma di rete per quell'host. L'audit registra etichetta, destinazione ed esito (`allow`, `ask`, `approved`, `deny`).

**Diverso dal design.**

- Ricerca preventiva in modalità `on` con dati non pubblici: non mostra una scheda di approvazione, perché il prefetch gira prima del loop e non si può sospendere. Non parte, e l'evento `web_prefetch.skipped` dice perché; il loop può ancora cercare, chiedendo conferma.
- Chiamate in parallelo: quelle che chiederebbero un'approvazione di uscita passano in sequenza, dove la richiesta sospende il turno.

**Trovato strada facendo.**

- L'esecuzione di un piano strutturato chiamava i server MCP direttamente, senza il gestore dei tool: niente audit e niente controlli. Ora passa dal gestore. Il rollback dichiarativo chiama ancora il server direttamente (ripete un'operazione sulla stessa destinazione del passo che annulla).
- `calendar_import_feed` scaricava un URL scelto dal modello senza il controllo di rete di S0: ora segue le stesse regole di `http_get`.

**Effetto pratico atteso, da misurare.** Con il profilo compilato ogni turno con memoria diventa `private` e ogni ricerca del loop chiede conferma; dopo un tool dell'infrastruttura il turno è almeno `internal`, e così la ricerca. La ricerca preventiva continua a girare finché la richiesta e gli ultimi messaggi sono pubblici. Se le conferme risultano troppe, la strada indicata dal design è separare la chiamata che scrive la query (che vedrebbe solo la richiesta) da quella che legge la memoria.

## 10. Decisioni

Prese dal maintainer il 13/11/2026.

| # | Domanda | Decisione | Note |
| :--- | :--- | :--- | :--- |
| 1 | Etichetta predefinita di ciò che l'utente scrive | `public`, alzata dal livello della conversazione e dai rilevatori | Con `internal` ogni ricerca web chiederebbe conferma |
| 2 | Stato dell'infrastruttura (nomi, indirizzi, stato dei servizi) | `internal`; output di comandi e log `private` | |
| 3 | Un provider cloud senza conservazione dei dati può ricevere `private`? | No. `private` si concede solo a mano, provider per provider | |
| 4 | Quando mostrare l'etichetta | Da `internal` in su, e sempre quando impedisce qualcosa | |
| 5 | Un server MCP nuovo | Parte dal livello più stretto; lo classifica chi lo aggiunge | |
| 6 | Sospensione dei permessi dopo contenuto non attendibile ([7.3](#73-contenuto-non-attendibile)) | Per le uscite di dati: attiva da subito (in S1). Per i comandi: da valutare | Il motivo è in 7.3: troppe conferme nascondono quella che conta |
| 7 | `http_get` verso internet | Conferma, salvo host ammessi; le automazioni dichiarano i loro host nella policy; lista base di host sicuri da subito, tutto modificabile dalla UI | Fatto in S0 ([9.1](#91-s0-come-è-stata-costruita)) |

## 11. Alternative scartate

| Alternativa | Perché no |
| :--- | :--- |
| Un modello che giudica la sensibilità di ogni messaggio | Inaffidabile, e un errore è un'uscita di dati; aggiunge una chiamata a ogni passo. Resta utile solo come rilevatore che alza |
| Etichetta unica per conversazione | Semplice, ma un solo dato privato sposta tutto sul modello più debole |
| Due agenti separati, uno privato e uno no | Due memorie e due insiemi di tool; l'utente diventa lo smistatore |
| Variabile di contesto per l'etichetta del turno | Meno codice da toccare, ma si perde nei thread dei tool in parallelo e nasconde quali chiamate vedono cosa |
| Separazione completa tra modello che pianifica e modello che legge, con tracciamento di ogni valore | Dà garanzie vere, ma riscrive l'agent loop. Le etichette per chiamata sono il primo passo in quella direzione |
