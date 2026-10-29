# Memoria dell'agente: ricerca e proposta per modalità

**Data:** 29 ottobre 2026
**Stato:** ricerca e proposta, nessuna modifica al codice
**Contesto:** rimozione di Letta concordata il 29/10; la memoria va tenuta interamente nel backend

Il documento raccoglie i tipi di memoria per agenti LLM descritti in letteratura e nei sistemi in produzione, li confronta con quello che `homelab-agent` ha oggi e propone quali integrare, in che modo e per quale modalità (chat, ask, act, plan). Le fonti sono in fondo, numerate; i numeri riportati sono quelli dichiarati dagli autori, spesso su benchmark conversazionali in inglese con modelli cloud, e vanno presi come indicazioni di tendenza, non come previsioni per il nostro deploy.

---

## 1. In sintesi

- La tassonomia di riferimento (CoALA, ripresa da tutte le survey 2026) distingue **memoria di lavoro** (il contesto del turno) e tre memorie a lungo termine: **semantica** (fatti), **episodica** (esperienze) e **procedurale** (come fare le cose). Filesystem, database vettoriale e grafo sono *supporti*, non tipi: ognuno può ospitare qualunque tipo.
- Le evidenze più solide dicono che **conta più come l'agente gestisce il contesto che il supporto scelto**: un agente con soli file e grep ottiene su LoCoMo il 74%, più di Mem0 con grafo (68,5%) [9]; uno studio sistematico sui filesystem di memoria trova che l'organizzazione dimezza il costo di ricerca su archivi grandi ma **non migliora le risposte**, e si degrada col crescere dell'archivio salvo con il modello gestore più forte [2].
- Per noi pesano due vincoli: il modello locale è debole nella gestione autonoma della memoria (LFM2.5 al 67% sulla suite `memory`, 12% su `planning`) e il prompt processing a freddo è di circa 100 token/s, quindi **ogni token di memoria iniettato costa latenza**. Le tecniche che delegano molto al modello (note che si riorganizzano da sole, grafi estratti dall'LLM, espansione temporale delle query) sono le più rischiose.
- Oggi la memoria è **identica per tutte le modalità**: `retrieve_memory` gira prima del router e costruisce lo stesso contesto (finestra recente, riepilogo, 3 fatti) per chat, ask, act e plan; l'estrazione dei fatti avviene a ogni turno in `respond`. Gli episodi più ricchi che abbiamo (piani, tracce di esecuzione e rollback in `thread_store`) non vengono mai riletti.
- Proposta: una **politica di memoria per modalità** (cosa si legge, quanto, cosa si scrive), più tre aggiunte in ordine di rapporto valore/costo: **memoria episodica delle esecuzioni** per act e plan, **memoria procedurale** curata (istruzioni e note sui tool, piani riusciti come modelli) e un **consolidamento in background** che sostituisca l'estrazione a ogni turno. Grafo temporale completo, filesystem gestito dall'agente e servizi esterni (Mem0, Zep) sono sconsigliati per ora.

---

## 2. Tassonomia

### 2.1 Il riferimento: CoALA e le survey 2026

CoALA adatta agli agenti LLM la tassonomia delle architetture cognitive classiche (ACT-R, SOAR) [10]. Le survey del 2026 la riprendono con varianti:

- un ciclo **scrittura → gestione → lettura**, con tre assi: estensione temporale, supporto di rappresentazione, politica di controllo (chi decide cosa scrivere e quando) [11];
- l'aggiunta di una memoria **sensoriale** (buffer transitorio di input grezzi) e la distinzione tra memoria dell'agente e memoria dell'utente [12];
- la vista a livello di modello: KV cache, stati ricorrenti, parametri scrivibili [13];
- la constatazione che la **memoria procedurale è il quadrante meno studiato** e che quasi nessun sistema supporta bene tutti i tipi insieme [11][14].

| Tipo | Che cosa contiene | Esempi nei sistemi | Equivalente umano |
| :--- | :--- | :--- | :--- |
| **Di lavoro** | il contesto del turno: prompt, messaggi recenti, risultati dei tool | finestra di contesto, scratchpad, compattazione | memoria a breve termine |
| **Semantica** | fatti e preferenze, indipendenti da quando sono stati appresi | fatti Mem0, blocchi `human`/`persona` di Letta, `USER.md` e `MEMORY.md` di OpenClaw | sapere che Roma è la capitale |
| **Episodica** | esperienze datate: conversazioni, esecuzioni, esiti | archivio delle conversazioni, riflessioni di Reflexion, episodi di LangMem | ricordare cosa è successo martedì |
| **Procedurale** | come comportarsi e come fare le cose | `AGENTS.md`/`CLAUDE.md`, prompt ottimizzati, workflow e skill | saper andare in bicicletta |
| **Parametrica** | conoscenza nei pesi del modello | fine-tuning, LoRA | — |

### 2.2 Supporti (dove sta la memoria)

| Supporto | Punti di forza | Punti deboli |
| :--- | :--- | :--- |
| **File Markdown** | i modelli sanno già usare list, grep e read; leggibili e modificabili a mano; versionabili | niente transazioni né concorrenza; ricerca solo per parole chiave; schema che deriva; l'organizzazione si degrada |
| **Database vettoriale** | ricerca semantica su testi parafrasati; scala | perde termini esatti (ID, IP, nomi di CT); la soglia di pertinenza va tarata; opaco |
| **Indice testuale (BM25/FTS)** | termini esatti, economico | nessuna sinonimia |
| **Grafo di conoscenza** | relazioni multi-salto, validità temporale | costoso da costruire (molte chiamate LLM), qualità legata all'estrazione |
| **Relazionale** | transazioni, cronologia, audit, filtri strutturati | richiede uno schema |

L'articolo di Oracle riassume il compromesso così: **il filesystem vince come interfaccia, il database come supporto** [1]. Nel loro esperimento un agente su file e uno su database ottengono risultati simili su un corpus piccolo; su un corpus grande con domande vaghe, 29,7% contro 87,1% (giudice LLM, campione piccolo, esperimento del fornitore). Le scritture concorrenti senza lock perdono voci in silenzio. La raccomandazione è un ibrido: ergonomia da file per l'agente, garanzie da database sotto, ed evitare di affiancare quattro database diversi (vettoriale, documentale, grafo, relazionale).

---

## 3. I tipi di memoria in dettaglio

### 3.1 Memoria di lavoro e gestione del contesto

Non è persistente, ma è dove si decide la qualità: tutto il resto della memoria serve a riempirla bene.

- **Compattazione:** vicino al limite si riassume la conversazione e si riparte dal riassunto. Il prompt di compattazione va tarato su tracce reali, prima massimizzando il richiamo e poi la precisione; svuotare i vecchi risultati dei tool è la forma più sicura [8].
- **Note strutturate:** l'agente scrive progressi e dipendenze fuori dal contesto (una lista di cose da fare, un `NOTES.md`) e le rilegge dopo un reset [8]. Letta usa un blocco di memoria per lo "stato della ricerca" di un agente di ricerca [15].
- **Recupero anticipato o al momento:** il pre-recupero (embedding prima dell'inferenza) è veloce; il recupero al momento tramite tool dà contesti più piccoli e aggiornati ma richiede buoni tool. L'ibrido raccomandato: precaricare ciò che è stabile ed essenziale, cercare il resto con i tool [8].
- **Salvare prima di compattare:** OpenClaw, prima di compattare, esegue un turno silenzioso in cui l'agente salva ciò che va ricordato; il turno può solo aggiungere testo nuovo alla nota del giorno [4].
- **Il contesto lungo non sostituisce la memoria:** su LongMemEval i modelli a contesto lungo perdono dal 30 al 60% leggendo tutta la cronologia (~115k token) invece delle sole sessioni pertinenti [16].

**Da noi:** `retrieve_memory` tiene gli ultimi 20 messaggi entro 6000 token stimati, con un riepilogo incrementale sopra i 30 messaggi, e aggiunge fino a 3 fatti di altri thread con punteggio > 0,35. Lo fa per tutte le modalità, anche per chat (timeout 15 s, nessun tool). Con il prompt processing a ~100 token/s a cache fredda, 6000 token di memoria valgono fino a un minuto di attesa.

### 3.2 Memoria semantica: fatti e profilo

**Fatti estratti (stile Mem0).** Dopo ogni scambio un LLM estrae fatti candidati e, confrontandoli con i più simili già salvati, sceglie tra aggiungere, aggiornare, cancellare o non fare nulla. Mem0 dichiara +26% sul giudice LLM rispetto alla memoria di OpenAI su LoCoMo, con −91% di latenza p95 e oltre il 90% di token in meno rispetto al contesto completo (1,8k contro 26k token) [5]. Una critica nota che su LoCoMo un semplice contesto completo arriva a ~73%, sopra il miglior Mem0 (~68%), e che LoCoMo non valuta gli aggiornamenti di conoscenza [9].

**Profilo o memoria centrale (stile Letta, OpenClaw).** Un blocco piccolo, sempre nel prompt, con le preferenze stabili e le decisioni permanenti. OpenClaw separa `USER.md` (preferenze, con data di osservazione e stato attivo/superato, budget di caricamento proprio) da `MEMORY.md` (fatti durevoli e decisioni), entrambi caricati a inizio sessione; se superano il budget vengono troncati nel prompt ma non su disco [4]. Letta permette all'agente di modificare questi blocchi da solo con appositi tool [15].

**Lezioni ricorrenti:**
- Gli agenti **aggiungono bene ma compattano male**: invece di generalizzare ("ignora le email commerciali") elencano ogni mittente [3].
- **Comprimere in fatti fa perdere dettaglio**: su LongMemEval memorizzare i singoli scambi funziona meglio che i fatti estratti, che però aiutano le domande su più sessioni. La combinazione migliore usa i fatti come **chiave di indicizzazione aggiuntiva** del testo originale: +9,4% di richiamo e +5,4% di accuratezza [16].
- Anche un sistema semplice regge se le scritture sono sicure: Odysseus tiene i ricordi in un JSON con categoria e contatore d'uso, cerca con Jaccard più vettori e rifiuta di riscrivere l'archivio se non riesce a leggerlo, per non sostituirlo con una lista vuota [6].
- Le note che riguardano azioni future devono dire quando valgono, quando scadono e chi le ha stabilite; la memoria **non è una policy** e non sostituisce approvazioni e sandbox [4].

**Da noi:** i fatti di D3 (sqlite-vec, embedding `paraphrase-multilingual-MiniLM-L12-v2` a 384 dimensioni, deduplicazione a 0,95, entità nella stessa chiamata) coprono il modello Mem0 tranne l'aggiornamento e la cancellazione automatici: un fatto smentito resta accanto a quello nuovo. Non esiste un profilo: le preferenze dell'utente competono con gli altri fatti per i 3 posti del recall.

### 3.3 Memoria semantica strutturata: grafi di conoscenza

- **Grafo temporale (Zep/Graphiti):** tre sottografi (episodi grezzi, entità e relazioni estratte, comunità riassunte) e un modello **bitemporale**: quando un fatto è vero e quando il sistema l'ha appreso. Un fatto smentito non si cancella: il suo arco riceve `invalid_at`. Zep dichiara fino a +18,5% di accuratezza su LongMemEval e −90% di latenza rispetto al contesto completo, e 94,8% contro 93,4% di MemGPT su DMR [17].
- **Grafo per il recupero multi-salto (HippoRAG):** si costruisce un grafo dalle entità del corpus e si lancia un PageRank personalizzato a partire dalle entità della domanda. Fino a +20% su 2WikiMultiHopQA, alla pari su HotpotQA, 10–30 volte più economico del recupero iterativo; la qualità dipende dall'estrazione, che l'LLM fa in modo approssimativo [18].
- **Mem0 con grafo:** circa +2% rispetto alla versione base [5].
- **Note collegate che evolvono (A-MEM):** ogni memoria diventa una nota alla Zettelkasten con descrizione, parole chiave, tag e collegamenti scelti dall'LLM; una nota nuova può riscrivere il contesto di quelle vecchie. Valutato soprattutto su dialoghi, non su ambienti con azioni [19].

**Da noi:** le entità di D3 con relazioni per co-occorrenza sono un grafo minimo. Il grafo più utile per un homelab però **esiste già fuori dall'agente**: CT, IP, DNS (Pi-hole), proxy (NPM), servizi e host sono interrogabili tramite i tool MCP. Un grafo dell'infrastruttura sincronizzato da quelle API sarebbe esatto e gratuito in chiamate LLM; estrarlo dalle conversazioni lo renderebbe approssimativo e presto obsoleto.

### 3.4 Memoria episodica: conversazioni

- **Livelli di MemGPT/Letta:** memoria centrale sempre visibile, memoria di richiamo (cronologia delle conversazioni, cercabile) e archivio (testi arbitrari) [15].
- **LongMemEval** misura cinque capacità: estrazione di informazioni, ragionamento su più sessioni, ragionamento temporale, aggiornamento della conoscenza e **astensione** (dire "non lo so"). Le indicazioni progettuali [16]:
  - indicizzare i **singoli scambi** invece delle sessioni intere;
  - usare i fatti estratti come chiave aggiuntiva (vedi 3.2);
  - indicizzare con data e far ricavare all'LLM l'intervallo temporale della domanda: +11,3% di richiamo sulle domande temporali, ma **solo con un modello forte**, perché uno debole inventa o perde i riferimenti;
  - in lettura, prima prendere appunti sui passaggi recuperati e poi rispondere (Chain-of-Note con formato JSON): fino a +10 punti anche con recupero perfetto.
- **Ricerca ibrida:** un repository di terzi riporta su LongMemEval-S un richiamo delle sessioni giuste del 95,2% nei primi 5 risultati combinando BM25 e vettori [16]. OpenClaw usa la stessa combinazione per trovare anche ID e simboli esatti [4].
- **Recupero pesato (Generative Agents):** il punteggio somma pertinenza (coseno), recenza (decadimento esponenziale) e importanza (assegnata dall'LLM) [20].

**Da noi:** le conversazioni sono salvate quattro volte (checkpoint LangGraph, `thread_store`, JSONL e Letta) ma non sono cercabili tra thread: il recall usa solo i fatti. Domande come "cosa avevamo detto sul backup del NAS?" funzionano solo se all'epoca è stato estratto un fatto.

### 3.5 Memoria episodica: esperienze ed esecuzioni

- **Reflexion:** dopo un tentativo fallito l'agente scrive una riflessione verbale su cosa è andato storto e la rilegge al tentativo successivo; 91% pass@1 su HumanEval contro 80% di GPT-4. Funziona quando il segnale di valutazione è chiaro; con test generati dall'agente stesso i falsi positivi lo ingannano [21].
- **Case-based reasoning:** recuperare casi passati simili, adattarli e imparare dall'esito [22]. Nel campo operativo un caso Amazon (232 incidenti in 17 settimane) usa i runbook come memoria e propone correzioni dove sono lacunosi [22]. Uno studio Microsoft sull'analisi delle cause trova invece che **aggiungere le discussioni di incidenti passati non migliora** i risultati, mentre l'agente ReAct che interroga i dati vivi è molto più accurato sui fatti [22]: l'esperienza passata aiuta a scegliere *cosa controllare*, non sostituisce il controllo.
- **Episodi di LangMem:** schema osservazione → ragionamento → azione → esito, per ricordare come è stata risolta una situazione [7].

**Da noi:** `thread_store.thread_messages` conserva per ogni risposta `mode`, `tool_used`, `plan_structure_json`, `execution_trace_json` e `rollback_trace_json`. Sono episodi completi e **strutturati**, ottenibili senza chiamate LLM, ma nessuno li rilegge: un piano che è fallito per lo stesso motivo la settimana scorsa non lascia traccia nel piano di oggi.

### 3.6 Memoria procedurale

- **File di istruzioni (`AGENTS.md`, `CLAUDE.md`, skill):** il comportamento di base vive in file che l'agente legge e, con approvazione, modifica. LangSmith Agent Builder parte da un `AGENTS.md` di una riga che, dopo settimane di correzioni in linguaggio naturale, contiene regole di formato e casi particolari senza che l'utente l'abbia mai modificato a mano. **Ogni modifica richiede approvazione umana**, soprattutto contro la prompt injection; i file con schema (tool, skill) vengono validati e gli errori tornano al modello. La parte più difficile è stata il prompt su quando ricordare e dove mettere cosa [3]. Claude Code carica `CLAUDE.md` per intero e solo l'inizio dell'indice della memoria automatica (circa 200 righe), caricando i file di dettaglio al bisogno; la memoria va trattata come un suggerimento da verificare [23].
- **Ottimizzazione del prompt (LangMem):** dalle tracce con feedback si ricava una versione migliorata delle istruzioni, senza toccare i pesi [7].
- **Workflow ricavati dalle esecuzioni (Agent Workflow Memory):** dalle traiettorie riuscite si estraggono routine riutilizzabili. Su WebArena +51,1% di successo relativo sul miglior metodo autonomo e +7,9% su workflow scritti da esperti; la versione online impara dalle proprie esecuzioni giudicate corrette da un valutatore [24].
- **Memoria procedurale modulare (LEGOMem):** memorie di compito intero per l'orchestratore e di sottocompito per gli esecutori; la memoria dell'orchestratore conta di più per pianificare e **i modelli piccoli ne beneficiano in modo evidente** [25].
- **Consolidare invece di accumulare:** ridurre le traiettorie a un insieme limitato di workflow in linguaggio naturale dà risultati comparabili con circa 3,5 volte meno token di memoria [26].
- **Skill nello studio sui filesystem:** su ALFWorld un esecutore forte rende meglio con il registro grezzo degli episodi (87,1%) che con la guida distillata (82,1%); un **esecutore debole fa il contrario** (52,9% senza memoria, 66,4% con gli episodi, 76,4% con la guida). Un gestore più forte che costruisce le skill aggiunge circa 13 punti [2].

**Da noi:** la memoria procedurale è tutta statica: prompt nel codice, `ModePolicy`, catalogo dei tool, compensazioni di rollback dichiarate. Le valutazioni di D4 mostrano errori che sono procedurali, non di ragionamento: `release_ip` chiamato con il nome host invece dell'IP, `vmid "CT 120"` invece di `120`, piani incompleti. Sono esattamente le correzioni che una nota sui tool o un piano modello eviterebbero.

### 3.7 Memoria su filesystem

- **Letta Filesystem:** con quattro tool (grep, search_files, open, close) e gpt-4o-mini, 74,0% su LoCoMo semplicemente salvando le conversazioni in file. La spiegazione: i modelli sono addestrati intensamente sulle operazioni su file grazie al codice [9].
- **Memory tool di Anthropic:** l'agente legge e scrive file sotto `/memories`; il tool gira lato client e `/memories` è solo un prefisso che l'applicazione mappa su qualunque storage, anche un database. Il gestore deve impedire l'uscita dalla directory [27]. Si affianca alla rimozione automatica dei vecchi risultati dei tool dal contesto [8].
- **OpenClaw:** Markdown nel workspace (`USER.md`, `MEMORY.md`, note giornaliere `memory/AAAA-MM-GG.md`), ricerca ibrida, flush prima della compattazione e "dreaming" (vedi 3.8) [4].
- **Lo studio sistematico (arXiv 2607.26637)** [2] confronta, sugli stessi dati, una gerarchia organizzata dall'agente, un deposito integrale e il recupero a chunk:
  - **Correttezza:** nessun vincitore. Su LoCoMo gerarchia 86,1%, deposito 84,2%, chunk 81,6%. Su PersonaMem 32k la gerarchia curata **crolla al 37,5%** contro il 78,1% del deposito.
  - **Costo:** sugli archivi grandi l'organizzazione dimezza il costo per domanda (circa 1,4 ¢ contro 4,0 ¢); su quelli piccoli è indifferente.
  - **Degrado:** riorganizzare senza una regola esplicita di conservazione perde contenuto (REALTALK dal 77,6% al 41,2%); l'aderenza alla struttura si erode con la crescita, tranne con il gestore più forte.
  - **I tool contano quanto il modello:** cambiare il set di tool rimodella l'archivio quanto cambiare il modello.
  - **Chi cerca conta più di chi organizza:** passando da un modello piccolo a uno grande nella ricerca la correttezza sale da ~62% a ~79%, con il costo che passa da meno di 1 ¢ a ~19 ¢ per domanda.

**Valutazione per noi:** il filesystem come *interfaccia* per testi brevi, curati e letti per intero (istruzioni, profilo) è ottimo: leggibile, modificabile dall'utente, nessuna ricerca necessaria. Un filesystem *gestito e riorganizzato dall'agente* è sconsigliato: il nostro gestore è un modello debole, proprio il caso in cui lo studio osserva il degrado. Inoltre le automazioni scrivono in parallelo alla chat, il caso in cui i file senza lock perdono dati [1].

### 3.8 Consolidamento in background ("sonno")

- **Generative Agents:** periodicamente, o quando l'importanza accumulata supera una soglia, l'agente "riflette" sui ricordi recenti e ne ricava conclusioni di livello più alto, salvate come nuovi ricordi [20].
- **Letta sleep-time:** un secondo agente lavora quando il principale è inattivo e riscrive i blocchi di memoria condivisi [15].
- **OpenClaw dreaming:** un job cron fa una passata completa; i candidati devono superare soglie di punteggio, frequenza di richiamo e varietà di domande; una chiamata senza tool sceglie fusioni e sostituzioni dopo un controllo a regole, e le decisioni non valide ricadono su "solo aggiunta". **I contenuti non fidati o generati dal sistema sono esclusi dalla promozione**; solo la promozione profonda scrive `MEMORY.md`, mentre i riassunti delle fasi finiscono in un diario per la revisione umana [4].
- **LangChain** pianifica lo stesso: un job giornaliero che rilegge le conversazioni e aggiorna la memoria, più un comando `/remember` esplicito [3]. LangMem chiama "subconscia" questa estrazione, contrapposta a quella "cosciente" fatta dall'agente con i tool durante il turno [7].

Il vantaggio per noi è doppio: toglie una chiamata LLM dal percorso di ogni turno (oggi `remember_turn` gira dentro `respond`) e permette di elaborare in blocco, di notte, quando il server LLM è libero, con un contesto più ampio (l'intera conversazione invece del singolo scambio, utile contro i fatti estratti dalle chiacchiere).

### 3.9 Sicurezza e governo della memoria

- **Avvelenamento:** MINJA inserisce record malevoli nella memoria con le sole domande di un utente normale, con il 98,2% di successo nell'inserimento e il 76,8% nell'indurre il ragionamento malevolo; uno studio successivo mostra che in condizioni realistiche le percentuali calano [28]. AgentPoison supera l'80% di successo avvelenando meno dello 0,1% della base [28].
- **Contromisure che ricorrono nei sistemi:** provenienza su ogni record; esclusione dei contenuti non fidati dalla promozione [4]; approvazione umana per le modifiche alle istruzioni [3]; spazi separati per utente [7]; la memoria non decide i permessi [4].
- **Per noi:** il rischio concreto è il web. Le modalità ask, act e plan leggono pagine tramite SearXNG e il prefetch; un fatto o, peggio, una procedura ricavati da una pagina potrebbero spingere l'agente verso un'azione distruttiva in act. La memoria procedurale deve quindi accettare solo contenuti di provenienza utente o esecuzione verificata, mai web.

### 3.10 Memoria parametrica e altro

Fine-tuning e LoRA per "ricordare" non sono applicabili: modelli condivisi tra servizi sul router llama.cpp, nessun budget di addestramento, e la conoscenza dell'homelab cambia ogni settimana. Il riuso della KV cache invece conta: llama.cpp riutilizza il prefisso comune tra richieste, quindi **la memoria stabile va messa all'inizio del prompt** (profilo, istruzioni) e quella variabile in fondo, altrimenti ogni turno ripaga l'intero prompt processing.

---

## 4. Cosa ha oggi `homelab-agent`

| Tipo | Implementazione | Scrittura | Lettura | Limiti |
| :--- | :--- | :--- | :--- | :--- |
| Di lavoro | `retrieve_memory`: ultimi ≤20 messaggi entro 6000 token, riepilogo su file `summary_<thread>.txt` | riepilogo generato sopra 30 messaggi | prima del router, identico per tutte le modalità | budget fisso anche per chat; nessuna pulizia dei risultati dei tool |
| Conversazioni | checkpoint LangGraph, `thread_store`, JSONL, Letta | intake e respond | solo nel thread corrente | quattro copie; nessuna ricerca tra thread |
| Semantica (fatti) | `vec_memory` kind `fact` + `memory_entities`, `memory_fact_entities` | `remember_turn` a ogni turno, dentro `respond` | 3 fatti di altri thread con punteggio > 0,35; tool `recall_memory` | fatti smentiti non invalidati; nessun profilo; solo vettori, niente parole esatte |
| Semantica (documenti) | `vec_memory` kind `kb` | caricamento manuale | tool `knowledge_search` | — |
| Episodica (esecuzioni) | `thread_messages`: piano, traccia di esecuzione e rollback | a ogni risposta | mai | — |
| Procedurale | prompt nel codice, `ModePolicy`, catalogo tool, compensazioni dichiarate | solo sviluppo | sempre | nessun apprendimento; nessuna nota sui tool |
| Audit | `audit_log` | operazioni sensibili | UI e API | non è memoria dell'agente |

Va anche ricordato quello che l'agente **non deve ricordare**: lo stato dell'infrastruttura (container accesi, IP assegnati, record DNS) cambia fuori dall'agente ed è interrogabile con i tool. Un fatto come "CT 125 ha IP 192.168.1.185" è utile come suggerimento su dove guardare, ma in act va sempre verificato prima di agire.

---

## 5. Memoria per modalità

### 5.1 Perché differenziare

Le quattro modalità hanno budget e rischi molto diversi (`mode_policy.py`):

| Modalità | Tool | Timeout | Ragionamento | Che cosa le serve ricordare |
| :--- | :--- | :--- | :--- | :--- |
| chat | nessuno | 15 s | 0 | chi è l'utente e di cosa si sta parlando |
| ask | fino a 5, lettura | 30 s | 2048 | cosa sa l'agente e cosa si è detto in passato |
| act | fino a 10, anche MCP | 120 s | 8192 | come si usano i tool, cosa è successo le altre volte, cosa verificare |
| plan | fino a 15 | 300 s | illimitato | piani che hanno funzionato, fallimenti e compensazioni |

Le evidenze sostengono la differenziazione: lo studio sui filesystem trova che la forma di memoria migliore dipende da chi la usa (esecutore debole → guida distillata, forte → episodi grezzi) [2]; LEGOMem trova che memorie diverse servono all'orchestratore e agli esecutori [25]; Anthropic raccomanda di precaricare il poco che è stabile e cercare il resto con i tool [8].

C'è un vincolo di architettura: oggi il recupero avviene prima del router. Differenziare richiede di spostare la composizione della memoria **dopo** il routing (o renderla dipendente dalla modalità scelta), lasciando prima del router solo ciò che serve a decidere la modalità: gli ultimi messaggi e la modalità precedente.

### 5.2 Politica proposta

| | chat | ask | act | plan |
| :--- | :--- | :--- | :--- | :--- |
| **Profilo** (precaricato, inizio prompt) | sì | sì | sì | sì |
| **Finestra e riepilogo** | piccola (~1500 token) | media | media | media |
| **Fatti** | no, salvo preferenze nel profilo | precaricati (soglia) + `recall_memory` | precaricati sulle entità citate, marcati come da verificare | come act |
| **Ricerca nelle conversazioni** | no | tool `search_conversations` | no | no |
| **Episodi di esecuzione** | no | no | i 2–3 più simili, compressi (tool, esito, errore) | i 3–5 più simili, con piano ed esito |
| **Procedure** | no | no | note sui tool scelti (iniettate con lo schema del tool) | piani modello pertinenti + note sui tool del catalogo |
| **Scrittura** | preferenze e decisioni esplicite | fatti dalle risposte, con provenienza (mai dal web senza conferma) | episodio deterministico dalla traccia; lezione proposta se fallito | episodio con piano; proposta di piano modello se riuscito e approvato |

Principi trasversali:
- **Budget per modalità** in `ModePolicy` (token di memoria e numero di elementi per tipo), in modo che chat non paghi il recupero di act.
- **Ordine nel prompt:** istruzioni, profilo e procedure prima (stabili, riusano la KV cache), poi elementi recuperati, infine messaggi recenti.
- **Provenienza e fiducia** su ogni record (`user`, `conversation`, `tool`, `web`, `consolidation`), con le procedure limitate a `user` e `tool` verificato.
- **Validità temporale invece di cancellazione:** un fatto smentito riceve `invalid_at` e un riferimento al fatto che lo sostituisce (modello Graphiti [17], in SQLite).

---

## 6. Valutazione delle opzioni

Punteggi indicativi: valore per il nostro caso, costo di implementazione, rischio con il modello locale.

| Opzione | Valore | Costo | Rischio | Verdetto |
| :--- | :--- | :--- | :--- | :--- |
| Politica di memoria per modalità | alto (latenza chat, rilevanza act/plan) | basso | basso | **sì, prima di tutto** |
| Profilo / memoria centrale | alto | basso | basso se scritto con approvazione | **sì** |
| Episodi di esecuzione (act/plan) | alto: errori ricorrenti | medio (deterministici, nessun LLM in scrittura) | basso | **sì** |
| Note sui tool e procedure curate | alto: errori di D4 sui parametri | basso | medio senza approvazione | **sì, con approvazione** |
| Piani modello (stile AWM) | medio-alto: planning al 12% | medio | medio: piani obsoleti | **sì, dopo gli episodi**, misurato con la suite `planning` |
| Consolidamento in background | medio: meno latenza, fatti migliori | medio | medio: fusioni sbagliate | **sì**, con decisioni a regole e ripiego a "solo aggiunta" |
| Ricerca ibrida (FTS5 + vettori) | medio: ID, IP, nomi | basso (FTS5 è in SQLite) | basso | **sì** |
| Ricerca nelle conversazioni | medio (ask) | medio | basso | **sì**, indicizzando i singoli scambi |
| Validità temporale dei fatti | medio | basso | basso | **sì**, insieme al consolidamento |
| Grafo dell'infrastruttura da API | medio | medio | basso (dati esatti) | più avanti, se servono domande multi-salto |
| Grafo temporale completo (Graphiti, Neo4j) | basso-medio | alto | alto: estrazione LLM | **no** per ora |
| Note auto-evolutive (A-MEM) | basso | medio | alto: riscritture del modello debole | **no** |
| Filesystem gestito dall'agente | basso | medio | alto: degrado e concorrenza | **no**; sì a un'interfaccia da file per profilo e procedure |
| Espansione temporale delle query con LLM | basso | basso | alto: serve un modello forte [16] | **no**; filtri temporali espliciti sì |
| Servizi esterni (Mem0, Zep, Letta) | basso | medio | medio: stesse dipendenze di Letta | **no** |
| Memoria parametrica | — | alto | — | **no** |

### Pro e contro delle aggiunte consigliate

**Profilo.** Pro: le preferenze non competono più con i fatti per il recall; costa poche centinaia di token, riusabili dalla cache. Contro: va mantenuto piccolo; se l'agente lo modifica da solo tende ad accumulare [3], quindi le modifiche vanno proposte e approvate (o fatte dall'utente nella vista Memoria).

**Episodi di esecuzione.** Pro: dati già presenti e strutturati, nessuna chiamata LLM per scriverli; colpiscono gli errori ricorrenti; il recupero per somiglianza della richiesta e per tool coinvolti è semplice. Contro: un episodio vecchio può descrivere un'infrastruttura che non c'è più, quindi vanno mostrati come "l'ultima volta è successo questo" con data; da soli non migliorano la diagnosi rispetto ai dati vivi [22].

**Note sui tool e procedure.** Pro: correggono errori sistematici a costo minimo (una riga accanto allo schema del tool); sono leggibili e modificabili dall'utente. Contro: sono il bersaglio naturale dell'avvelenamento, quindi solo da fonti fidate e con approvazione; vanno validate contro il catalogo (un tool rinominato rende la nota obsoleta).

**Piani modello.** Pro: è la tecnica con l'evidenza più forte per i modelli piccoli [2][25] e affronta la suite peggiore (planning 12%). Contro: un piano modello sbagliato si ripete ovunque; serve un criterio di successo affidabile (esecuzione completata senza rollback e confermata dall'utente) e un numero limitato di modelli consolidati [26].

**Consolidamento in background.** Pro: toglie latenza dal turno, vede la conversazione intera, può fondere duplicati e invalidare fatti smentiti. Contro: una fusione sbagliata cancella informazione; va reso reversibile (validità temporale, diario delle decisioni) e va eseguito quando il server LLM è libero, rispettando il vincolo di un solo modello caricato.

---

## 7. Piano proposto

Ogni passo è misurabile con l'harness di D4: prima si aggiunge la suite, poi si cambia la memoria.

| Passo | Contenuto | Misura |
| :--- | :--- | :--- |
| **M0** | Rimozione di Letta; una sola fonte per le conversazioni (`thread_store`, eliminando la copia JSONL o viceversa); riepilogo nel database invece che su file | test esistenti |
| **M1** | Suite di valutazione `recall`: aggiornamento di conoscenza, domande temporali, astensione, richiamo tra thread (casi in stile LongMemEval) | baseline |
| **M2** | Composizione della memoria dopo il routing; budget per modalità in `ModePolicy`; profilo precaricato e modificabile nella vista Memoria; ordine del prompt per la cache | latenza p50 di chat nelle Metriche; suite `recall` |
| **M3** | Episodi di esecuzione (kind `episode`) ricavati da `execution_trace_json`/`rollback_trace_json`, recuperati in act e plan; ricerca ibrida FTS5 + vettori | suite `tools`, `planning`, `rollback` |
| **M4** | Memoria procedurale: note sui tool e piani modello, proposti dall'agente dopo esecuzioni riuscite o corrette dall'utente, approvati nella UI | suite `planning`, `tools` |
| **M5** | Consolidamento notturno come automazione: estrazione dei fatti in blocco al posto di `remember_turn`, deduplicazione, validità temporale, diario delle decisioni | suite `memory`, `recall` |
| più avanti | Ricerca nelle conversazioni per ask; grafo dell'infrastruttura sincronizzato dalle API | da valutare |

---

## 8. Fonti

1. Oracle Developers, *A Practical Guide to Choosing the Right Memory Substrate for Your AI Agents* — [blogs.oracle.com](https://blogs.oracle.com/developers/comparing-file-systems-and-databases-for-effective-ai-agent-memory-management), [dev.to](https://dev.to/oracledevs/a-practical-guide-to-choosing-the-right-memory-substrate-for-your-ai-agents-33hj)
2. Zhou et al., *Filesystem-Based Memory for LLM Agents: Organization, Evolution, and Sustainability*, luglio 2026 — [arXiv 2607.26637](https://arxiv.org/abs/2607.26637)
3. LangChain, *How we built Agent Builder's memory system* — [langchain.com](https://www.langchain.com/blog/how-we-built-agent-builders-memory-system)
4. OpenClaw, *Memory* — [docs.openclaw.ai](https://docs.openclaw.ai/concepts/memory)
5. Chhikara et al., *Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory* — [arXiv 2504.19413](https://www.emergentmind.com/papers/2504.19413), [riepilogo dei numeri](https://dev.to/crabtalk/mem0-what-three-memory-scopes-actually-cost-1kpc)
6. Odysseus (riferimento nel workspace, `references/odysseus/src/memory*.py`): memoria in JSON con categorie, contatore d'uso, somiglianza Jaccard più vettori, scritture atomiche che falliscono in modo sicuro se il file non è leggibile
7. LangMem, *Long-term Memory in LLM Applications* — [guida concettuale](https://langchain-ai.github.io/langmem/concepts/conceptual_guide), [lancio](https://blog.langchain.com/langmem-sdk-launch)
8. Anthropic, *Effective context engineering for AI agents* — [anthropic.com](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents); *Managing context on the Claude Developer Platform* — [anthropic.com](https://www.anthropic.com/news/context-management)
9. Letta, *Benchmarking AI Agent Memory: Is a Filesystem All You Need?* — [letta.com](https://www.letta.com/blog/benchmarking-ai-agent-memory); critica — [Towards AI](https://pub.towardsai.net/mem0-vs-zep-vs-letta-a-folder-of-text-files-shouldnt-beat-the-61k-star-memory-layer-9d7e65c5799c)
10. Sumers et al., *Cognitive Architectures for Language Agents* (CoALA), arXiv 2309.02427
11. *LLM Agent Memory: A Survey from a Unified Representation–Management Perspective* — [preprints.org](https://www.preprints.org/manuscript/202603.0359); *Memory for Autonomous LLM Agents* — [alphaxiv 2603.07670](https://www.alphaxiv.org/abs/2603.07670)
12. *A Survey of Agent Memory in the Second Half* — [alphaxiv 2602.06052](https://www.alphaxiv.org/abs/2602.06052); *From Storage to Experience* — [arXiv 2605.06716](https://arxiv.org/pdf/2605.06716); *Always-On Agents: Persistent Memory, State, and Governance* — [arXiv 2606.30306](https://arxiv.org/pdf/2606.30306)
13. *Memory for Large Language Models* — [arXiv 2607.25380](https://arxiv.org/pdf/2607.25380)
14. *PlugMem* — [arXiv 2603.03296](https://arxiv.org/pdf/2603.03296); *Procedural Graphs* — [arXiv 2609.09153](https://arxiv.org/pdf/2609.09153)
15. Letta, *Memory blocks* — [letta.com](https://www.letta.com/blog/memory-blocks); *MemGPT and Letta* — [letta.com](https://letta.com/blog/memgpt-and-letta)
16. Wu et al., *LongMemEval* (ICLR 2025) — [arXiv 2410.10813](https://arxiv.org/html/2410.10813v2); richiamo ibrido su LongMemEval-S — [agentmemory](https://cdn.jsdelivr.net/gh/rohitg00/agentmemory@main/benchmark/LONGMEMEVAL.md)
17. Rasmussen et al., *Zep: A Temporal Knowledge Graph Architecture for Agent Memory* — [arXiv 2501.13956](https://arxiv.org/html/2501.13956)
18. Gutiérrez et al., *HippoRAG* (NeurIPS 2024) — [arXiv 2405.14831](https://ar5iv.labs.arxiv.org/html/2405.14831v3)
19. Xu et al., *A-MEM: Agentic Memory for LLM Agents* (NeurIPS 2025) — [NeurIPS](https://neurips.cc/virtual/2025/poster/119020)
20. Park et al., *Generative Agents* (2023) — [arXiv 2304.03442](https://arxiv.org/pdf/2304.03442v2)
21. Shinn et al., *Reflexion* (NeurIPS 2023) — [arXiv 2303.11366](https://www.arxiv.org/pdf/2303.11366v4)
22. Case-based reasoning per agenti LLM — [arXiv 2504.06943](https://arxiv.org/html/2504.06943v2); Amazon, runbook con supporto agentico — [amazon.science](https://cdn.amazon.science/78/ae/133af2444c9f98d4dd40d025751f/scipub-approval152129-40856700-humanintheloop-runbook-improvement-with-agentic-support-automation.pdf); Microsoft, *Exploring LLM-based Agents for Root Cause Analysis* — [microsoft.com](https://www.microsoft.com/en-us/research/publication/exploring-llm-based-agents-for-root-cause-analysis/)
23. Claude Code, `CLAUDE.md` e memoria automatica — [engineerscodex](https://www.engineerscodex.com/claude-code-auto-memory), [memoryplugin](https://blog.memoryplugin.com/claude-code-memory/)
24. Wang et al., *Agent Workflow Memory* (ICML 2025) — [arXiv 2409.07429](https://arxiv.org/pdf/2409.07429)
25. Han et al., *LEGOMem* (AAMAS 2026) — [arXiv 2510.04851](https://arxiv.org/pdf/2510.04851)
26. *From Trajectories to Workflows* (REALM 2026) — [aclanthology](https://aclanthology.org/2026.realm-1.78/)
27. Anthropic, *Memory tool* — [platform.claude.com](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)
28. Dong et al., *MINJA* — [arXiv 2503.03704](https://arxiv.org/html/2503.03704v2); *Memory Poisoning Attack and Defense on Memory Based LLM-Agents* — [arXiv 2601.05504](https://arxiv.org/html/2601.05504); AgentPoison (NeurIPS 2024), Chen et al.
