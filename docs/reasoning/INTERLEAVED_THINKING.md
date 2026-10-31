# Ragionamento tra i passi dell'agent loop

Ricerca e analisi del 2026-10-30, seguito di [REASONING_RESEARCH.md](REASONING_RESEARCH.md) (sezione 7, punto 6).
La domanda: il ragionamento che il modello produce a un passo dell'agent loop deve arrivare ai passi successivi? Se sì,
come, con i modelli dei preset e con llama.cpp? Il documento riassume cosa raccomandano produttori e ricerca, verifica
cosa fanno davvero i template dei nostri modelli e il server, descrive cosa fa oggi il backend e propone un percorso
misurabile. I risultati dell'implementazione (E8) sono nella sezione 9.

---

## 1. In sintesi

1. **Dentro un turno con tool, tutti i produttori dicono di conservare il pensiero.**
   - Fra questi ci sono Anthropic, OpenAI, Google (Gemma 4), Qwen, MiniMax, Z.ai e DeepSeek.
   - Sui turni precedenti dell'utente i produttori non sono d'accordo: Gemma 4 lo vieta, per Qwen3.6 è facoltativo e
     Qwen3.8 lo fa di default.
2. **L'evidenza quantitativa più forte viene da MiniMax-M2.** Togliere il pensiero dei passi precedenti fa perdere
   23 punti su Tau² (87 → 64) e 12,6 su BrowseComp (44,0 → 31,4), ma solo 2,2 su SWE-bench Verified
   ([MiniMax][minimax]).

   Il guadagno è più alto nelle catene di tool che dipendono dai risultati precedenti, cioè proprio il caso dell'agent
   loop.
3. **I template delle quattro famiglie dei preset conservano già il pensiero dei passi del turno in corso.** Basta che
   il loop sia scritto come sequenza di messaggi: assistente, risultato del tool, assistente. Nessun parametro
   aggiuntivo serve. Gemma 4 vuole in più che il messaggio dell'assistente contenga `tool_calls`. I template letti dai
   GGUF su CT 100 sono nella sezione 3.
4. **Il nostro loop non usa quella forma**, quindi a ogni passo il pensiero precedente si perde.
   - Ogni passo è un nuovo messaggio utente con lo storico dei tool in testo (`Step N: tool(args) -> risultato`).
   - Il pensiero del passo precedente finisce solo nella UI.
   - Nemmeno il campo `reasoning` del JSON di selezione entra nello storico.

   La stessa perdita c'è tra il piano ragionato a livello alto e la sua versione strutturata in plan, che è quella che
   viene eseguita (sezione 5.3).
5. **Il costo è contenuto per i nostri numeri.**
   - Con Qwen3.6 una selezione genera circa 430 token, JSON compreso.
   - Dieci passi di act aggiungono qualche migliaio di token a un contesto di 64K.
   - Con i messaggi il prompt cresce solo in coda, quindi la cache di llama.cpp riparte esattamente dal punto in cui si
     era fermata, anche sui modelli ibridi con strati ricorrenti come Qwen3.6 e Qwen3.8 (sezione 4.3).
6. **Le suite attuali non vedono la differenza.**
   - `tools` misura solo la prima scelta.
   - `planning` misura solo la struttura del piano.

   Prima di cambiare il loop serve una suite su più passi.
7. **Proposta** (sezione 8):
   - correggere subito il passaggio piano → piano strutturato;
   - aggiungere la suite su più passi;
   - provare il loop a messaggi mantenendo l'output JSON attuale, con un interruttore per profilo;
   - decidere sul tool calling nativo solo dopo le misure;
   - non conservare il pensiero tra un turno dell'utente e l'altro.

---

## 2. Cosa raccomandano produttori e ricerca

### 2.1 Termini

- **Interleaved thinking**: il modello ragiona *tra* una chiamata a tool e l'altra, dopo aver visto il risultato, invece
  di ragionare una volta sola all'inizio.
- **Conservare il pensiero** (*preserved thinking*): il pensiero dei passi precedenti resta nel contesto dei passi
  successivi. Senza, ogni passo ragiona da capo, e del ragionamento precedente vede solo l'azione e il risultato.

I due concetti vanno insieme: l'interleaved thinking rende di più se il modello vede anche cosa aveva pensato prima.

### 2.2 Produttori

| Chi | Dentro un turno con tool | Tra turni dell'utente | Fonte |
| :--- | :--- | :--- | :--- |
| Anthropic | i blocchi `thinking` vanno rimandati integri insieme ai risultati dei tool; ricostruirli dà errore | Opus 4.5 e i modelli dal 4.6 in poi li tengono (fatturati come input); i precedenti li tolgono | [extended thinking][anthropic-ext], [tool workflows][anthropic-tools] |
| OpenAI | rimandare i *reasoning items* tra le chiamate a funzione "aumenta l'intelligenza, riduce i token e migliora il riuso della cache"; esiste una versione cifrata per l'uso senza stato | idem con l'API Responses | [cookbook][openai-items], [annuncio][openai-responses] |
| Google, Gemma 4 | "i pensieri **non** vanno rimossi tra le chiamate a funzione" | vanno tolti: la cronologia contiene solo le risposte finali | [Gemma thinking][gemma-thinking] |
| Qwen3.6 | conservato dal template (ultima domanda dell'utente in poi) | facoltativo con `preserve_thinking`; addestrato a usarlo, consigliato per gli agenti | [Qwen3.6][qwen36] |
| Qwen3.8 | conservato | `preserve_thinking` attivo di default: "coerenza delle decisioni, meno ragionamento ripetuto, KV cache usata meglio" | [Qwen3.8][qwen38] |
| MiniMax-M2 | essenziale: il pensiero è lo stato che il modello porta da un passo all'altro | conservato | [MiniMax][minimax] |
| Z.ai, GLM | interleaved thinking di default; il pensiero va rimandato insieme ai risultati dei tool | *preserved thinking* con `clear_thinking: false`, consigliato per coding e agenti | [Z.ai][zai] |
| DeepSeek V3.2 | con `tools` nella richiesta, `reasoning_content` va rimandato, altrimenti la richiesta fallisce | senza `tools` viene ignorato | [DeepSeek][deepseek] |

Nessun produttore consiglia di togliere il pensiero *dentro* una catena di tool. Le differenze riguardano solo i turni
precedenti dell'utente.

### 2.3 Ricerca

- **Ablazione MiniMax-M2** ([MiniMax][minimax]):

  | Benchmark | Pensiero conservato | Pensiero tolto | Differenza |
  | :--- | :--- | :--- | :--- |
  | Tau² (tool) | 87 | 64 | +23 |
  | BrowseComp (web) | 44,0 | 31,4 | +12,6 |
  | GAIA | 75,7 | 67,9 | +7,8 |
  | xBench | 72,0 | 66,0 | +6,0 |
  | SWE-bench Verified | 69,4 | 67,2 | +2,2 |

  Senza il pensiero precedente lo stato "deriva": il modello perde ipotesi, vincoli e conclusioni intermedie, corregge
  meno i propri errori e pianifica peggio. Il guadagno cresce con la lunghezza delle catene di tool e con la loro
  dipendenza dai risultati. È anche un dato del produttore, su un modello addestrato per questo uso.
- **Il pensiero come stato di lavoro** ([Wang et al., 2026][iclr-compress]):
  - togliere il ragionamento passato a un agente cambia le azioni successive e quindi tutta la traiettoria;
  - il ragionamento diventa sostituibile solo quando lo stato utile è già fuori, in file, risultati di tool o feedback
    dell'ambiente.

  Il loro metodo comprime i blocchi di ragionamento meno informativi senza toccare azioni e risultati. Su 260 compiti
  la ricompensa passa da 0,699 a 0,718, con il 25,5% di token in ingresso in meno.

  Comprimere bene non peggiora; togliere tutto sì.
- **Effetto sulle valutazioni** ([Liu et al., 2026][liu-toolcalling]): il modo in cui la cronologia di interazioni e
  ragionamento viene riportata avanti è una delle scelte di implementazione non documentate che cambiano i risultati di
  tool calling, soprattutto in più turni.
- **Rischi** (già in [REASONING_RESEARCH.md](REASONING_RESEARCH.md), sezione 2.5):
  - l'overthinking negli agenti abbassa il successo;
  - il pensiero conservato allunga il contesto;
  - con contesti molto lunghi la comunità segnala anelli di ragionamento con Qwen3.6, oltre i 100K token
    ([discussione][reddit-preserve]).

  Per noi questi rischi pesano poco: un turno di act resta sotto i 10K token.

---

## 3. I template dei modelli dei preset

Letti dai metadati dei GGUF su CT 100 (`tokenizer.chat_template`; nessun preset usa un template esterno). In tutte le
famiglie il pensiero di un messaggio dell'assistente compare nel prompt solo se il messaggio viene **dopo l'ultima
domanda dell'utente**: i risultati dei tool non contano come domanda.

| Famiglia (file del preset) | Condizione per includere il pensiero | Turni precedenti | Note |
| :--- | :--- | :--- | :--- |
| Qwen3.6 (`Qwen3.6-35B-A3B-UD-Q4_K_M`) | `preserve_thinking is true` **oppure** dopo l'ultima domanda | esclusi di default | i messaggi `tool` diventano `user` con `<tool_response>…</tool_response>`, e il template non li conta come domanda |
| Qwen3.8 (`GSQ-RCO-IQ3_S-mtp`, `AD-IQ4_XS-IQ3_S`: template identico) | `preserve_thinking` non definito **o** vero, **oppure** dopo l'ultima domanda | **inclusi** di default | stesso trattamento dei tool di Qwen3.6 |
| Gemma 4 (`gemma-4-26B-A4B-it`) | dopo l'ultimo messaggio `user` **e** il messaggio ha `tool_calls` | esclusi sempre | i messaggi `tool` vengono resi dentro il turno del modello che ha fatto le `tool_calls`: senza `tool_calls` né il pensiero né i risultati hanno la forma attesa |
| LFM2.5 (`LFM2.5-24B-A2B`) | `preserve_thinking` (default falso) **oppure** dopo l'ultimo messaggio `user` | esclusi di default | legge `thinking`, `reasoning` o `reasoning_content` |

Conseguenza pratica: per conservare il pensiero dentro il turno **non serve alcun parametro**. Basta che il loop mandi
i passi come messaggi (assistente con `reasoning_content`, poi `tool`). `preserve_thinking` serve solo per i turni
precedenti dell'utente.

---

## 4. llama.cpp

Sorgenti del fork in esecuzione (`/root/llama-cpp-turboquant`, `407f3237b` del 2026-09-06), uguali su questi punti
alla copia upstream in `references/llama.cpp`.

### 4.1 Pensiero nei messaggi in ingresso

- Per un messaggio dell'assistente, llama.cpp legge `reasoning_content` e lo passa al template.
  - Per i template che usano un altro nome, lo copia in `thinking` (`common/chat.cpp`).
  - Accetta anche un messaggio `tool` senza `tool_call_id` e un messaggio dell'assistente con il solo `content`.
- Il pensiero rimandato **non** consuma il budget di ragionamento: il budget conta solo i token generati nella richiesta.

### 4.2 Conservare i turni precedenti

- `--reasoning-preserve` sul server, oppure `chat_template_kwargs: {"preserve_reasoning": true}` per richiesta,
  impostano in un colpo solo le variabili usate dai vari template (`common/jinja/caps.cpp`):
  - `preserve_thinking`;
  - `clear_thinking` (negata);
  - `truncate_history_thinking` (negata);
  - `drop_thinking` (negata).
- All'avvio il server verifica se il template sa conservare il pensiero (`supports_preserve_reasoning`) e lo scrive nel
  log.
- Nei preset non è impostato: vale il default di ogni template.

### 4.3 Riuso della cache con i modelli ibridi

Qwen3.6 e Qwen3.8 hanno strati ricorrenti (Gated DeltaNet). Il loro stato non si può riavvolgere a un token qualunque:
se il nuovo prompt diverge da quello in cache, il server deve ripartire da un **checkpoint** salvato prima del punto di
divergenza.

- I checkpoint si creano durante l'elaborazione del prompt (`tools/server/server-context.cpp`):
  - all'inizio dei messaggi dell'utente;
  - vicino alla fine del prompt (ultimo micro-batch);
  - comunque a non meno di 8192 token dal precedente;
  - al massimo 32 per slot.
- **Oggi**, a ogni passo il prompt diverge alla fine dello storico, dentro l'unico messaggio utente.
  - I token generati al passo precedente (pensiero e JSON) vengono scartati.
  - Il server riparte dal checkpoint vicino alla fine del prompt precedente e rielabora fino a un micro-batch
    (512 token) più la nuova riga di storico.
- **Con i messaggi**, il prompt del passo successivo estende esattamente quello in cache, compresi i token appena
  generati. Si elabora solo il risultato del tool, senza checkpoint né rielaborazione.

La differenza in prefill è piccola: qualche centinaio di token a passo, rapidi su V100. Il vantaggio dichiarato da Qwen
sulla KV cache vale soprattutto *tra* i turni: se il pensiero viene tolto da un turno già in cache, il prompt successivo
diverge da quel punto.

---

## 5. Cosa fa oggi il backend

### 5.1 Agent loop (`app/agent/agent_loop.py`)

- **Un passo è una sola richiesta con due messaggi.**
  - Il messaggio di sistema contiene regole e catalogo ed è stabile.
  - Il messaggio utente contiene, in ordine: contesto del turno, memoria, richiesta, e lo storico dei passi in testo
    (`tool_selection_prompt`).
  - Lo storico è `Step N: tool(args) -> risultato`, con i risultati accorciati a `AGENT_OBSERVATION_LIMIT` (4000
    caratteri).
- **L'output è un `ToolSelection` in JSON**, vincolato dalla grammatica dello schema:
  - `tool_needed`, `tool_name`, `arguments`;
  - `parallel_calls`;
  - `confidence`;
  - `reasoning`;
  - `final_answer`.
- **Il pensiero nativo** (`reasoning_content`) finisce in `ToolSelection.raw_thinking` e da lì in `self.reasonings`:
  serve alla UI e alla traccia, **non torna al modello**. Lo stesso vale per il campo `reasoning` del JSON.
- **La sintesi finale** (`_final_answer`, `_synthesize_after_loop`) è una chiamata separata.
  - Riceve la richiesta e i risultati interi dei tool.
  - Non riceve né i pensieri né le motivazioni dei passi.
  - La separazione dei risultati interi da quelli accorciati è voluta: un elenco lungo non deve far crescere ogni prompt
    di selezione.

Effetto: a ogni passo il modello ricostruisce da capo perché ha fatto le chiamate precedenti e cosa stava cercando,
partendo solo da nomi, argomenti e risultati dei tool. L'anti-loop, che blocca una chiamata ripetuta e passa alla
sintesi, in parte compensa proprio questa perdita.

### 5.2 Turni precedenti

La conversazione precedente entra come testo nella memoria composta (`retrieve_memory_node`: riassunto e turni
recenti), non come messaggi. Il pensiero dei turni precedenti non c'è. È coerente con i default di Gemma 4, Qwen3.6 e
LFM2.5, ma non con quello di Qwen3.8.

### 5.3 Plan (`app/agent/nodes/plan.py`)

- `plan_graph_node` chiede il piano in testo al livello `high` (8192 token di ragionamento).
- `generate_plan_structure` produce il piano strutturato, quello che `execute_plan` esegue. Lo fa con una chiamata
  separata e senza ragionamento, ricevendo solo la richiesta e il prompt utente: **né il piano testuale né il suo
  ragionamento**.

Il piano che l'utente legge e quello che viene eseguito sono quindi generati in modo indipendente. Il ragionamento ad
alto budget non arriva alla parte eseguita: è la stessa perdita del loop, in un punto in cui costa di più.

### 5.4 Dopo un'approvazione (`app/api/routes/approvals.py`)

- Una richiesta di approvazione chiude il turno.
- Alla risoluzione il backend esegue il tool e scrive una sintesi a partire da richiesta e risultato.
- Il loop non riprende: pensiero e storico dei passi prima dell'approvazione non servono più.

Per conservarli bisognerebbe salvare la catena di messaggi con la richiesta di approvazione e riprendere il loop. È un
cambiamento a parte, fuori da questa proposta.

### 5.5 Quanto pesa il pensiero

- **Per passo:**
  - con Qwen3.6 al livello `medium` della selezione, la suite `tools` genera in media circa 430 token per selezione,
    JSON compreso (7375 token su 17 casi);
  - il tetto è 2048 token di pensiero.
- **Per turno, nel caso peggiore:** act (10 passi) aggiungerebbe circa 4K token tipici e 20K al massimo; plan
  (15 passi) circa 6K tipici. Il contesto di Qwen3.6 nei preset è 64K.

---

## 6. Opzioni

### A. Lasciare com'è

- **Pro:** nessun lavoro; prompt di selezione più corti.
- **Contro:** contraddice tutti i produttori, ripete il ragionamento a ogni passo e perde ipotesi e vincoli.

### B. Riportare la motivazione del JSON nello storico

Aggiungere il campo `reasoning` di `ToolSelection` a ogni riga dello storico.

- **Pro:**
  - una riga di codice;
  - vale anche per i modelli senza ragionamento (Phi-4) e per le fasi con ragionamento spento.
- **Contro:**
  - è una motivazione breve, scritta *per* lo schema, non lo stato di lavoro del modello;
  - non è la forma su cui i modelli sono addestrati.

Utile come base, ma l'opzione C la include già, perché il JSON intero entra nella cronologia.

### C. Loop a messaggi, output JSON invariato

Ogni passo aggiunge alla richiesta successiva due messaggi:
- un messaggio dell'assistente con il pensiero del passo e il JSON di selezione;
- un messaggio `tool` con il risultato accorciato.

La selezione resta vincolata dallo stesso schema e dalla stessa grammatica.

```text
system     regole + catalogo                               (stabile)
user       contesto del turno, memoria, richiesta          (stabile nel turno)
assistant  reasoning_content = pensiero del passo 1
           content = {"tool_needed": true, "tool_name": …, "reasoning": …}
tool       risultato accorciato del passo 1
assistant  reasoning_content = pensiero del passo 2, content = JSON del passo 2
tool       risultato accorciato del passo 2
→ generazione del passo 3 con json_schema = ToolSelection
```

- **Pro:**
  - Qwen3.6, Qwen3.8 e LFM2.5 conservano il pensiero senza parametri;
  - il prompt cresce solo in coda;
  - non cambiano lo schema di selezione, la grammatica, la validazione degli argomenti, l'anti-loop, le chiamate
    parallele e la sintesi separata sui risultati interi;
  - il cambiamento resta in `AgentLoop` e in `call_llm` (accettare una lista di messaggi).
- **Contro:**
  - **Gemma 4** conserva il pensiero e rende i risultati nella forma attesa solo se il messaggio dell'assistente ha
    `tool_calls`.
    - Si può sintetizzare `tool_calls` dal JSON, ma la cronologia mostrerebbe chiamate in formato nativo mentre si chiede
      un JSON.
    - In alternativa, per Gemma 4 l'interruttore resta spento.
  - Le note del loop (validazione fallita, ripetizione bloccata) vanno rese come messaggi `tool` o come note nel
    risultato.
  - Il percorso con `final_answer` resta: se lo storico era accorciato si passa comunque dalla sintesi sui risultati
    interi, come oggi.

### D. Tool calling nativo

- Il catalogo va in `tools`.
- Il modello emette `tool_calls` nel formato su cui è addestrato:
  - XML `qwen3_coder` per Qwen;
  - il formato proprio di Gemma 4;
  - il formato proprio di LFM2.5.
- llama.cpp li analizza con il parser del modello e una grammatica *lazy*.
- La risposta finale è il `content` senza chiamate, in streaming diretto.

- **Pro:**
  - è la forma in cui i produttori addestrano e misurano l'interleaved thinking;
  - conserva il pensiero per tutte e quattro le famiglie;
  - le chiamate parallele sono native;
  - niente JSON da validare né prompt dello schema;
  - la risposta finale non richiede una chiamata in più.
- **Contro:**
  - è il cambiamento più grande:
    - spariscono `ToolSelection`, `confidence`, `parallel_calls` e `final_answer`;
    - cambiano il catalogo nel prompt, le suite `tools`, la UI della selezione e i test;
  - dipende dalla qualità dei parser di llama.cpp per ogni famiglia, e la grammatica vincolata dello schema è stata
    introdotta proprio per i problemi di LFM2.5 (ISS-26);
  - la sintesi sui risultati interi va ripensata, perché nel formato nativo il modello vede i risultati nella cronologia.

### E. Conservare anche i turni precedenti

- Vale solo se la conversazione passa al modello come messaggi; oggi entra come testo nella memoria.
- È contro le indicazioni di Gemma 4.
- I turni vecchi sono già riassunti dalla memoria (E3–E6).

Non consigliato ora.

---

## 7. Cosa misurare

Le suite attuali non misurano l'effetto (sezione 1, punto 6). Serve una suite **`multistep`** che esegua l'agent loop
completo su catene di tool dipendenti, con i tool di sola lettura del catalogo. Esempi di catena:
- trovare il container con più memoria e leggerne i servizi;
- cercare un errore nei log di un servizio e controllare lo stato del container che lo ospita;
- confrontare due container e riferire la differenza.

| Metrica | Da dove |
| :--- | :--- |
| successo del compito (catena completa e risposta corretta) | giudizio sulla traccia e sulla risposta, come in `recall` |
| passi usati, chiamate ripetute bloccate dall'anti-loop, argomenti non validi | `execution_trace` |
| token di pensiero e di risposta per passo | `metrics` del provider |
| token elaborati nel prompt e presi dalla cache per passo | `timings.prompt_n` e `timings.cache_n` di llama.cpp, già nei log del provider |
| latenza totale del turno | runner delle valutazioni |

Confronto: C contro A con Qwen3.6, 2–3 ripetizioni per caso. Gli altri modelli si misurano solo con il tuo via
libera per caricarli.

---

## 8. Proposta

1. **Piano testuale nel piano strutturato** (indipendente, piccolo). `generate_plan_structure` riceve il piano scritto
   da `plan_graph_node` e lo traduce in passi, invece di ripianificare da zero. Così il piano eseguito è quello che
   l'utente ha letto, e il ragionamento al livello `high` arriva alla parte eseguita, attraverso il suo risultato. Si
   misura con `planning`.
2. **Suite `multistep`** (sezione 7), con la base attuale (opzione A) su Qwen3.6.
3. **Opzione C dietro un interruttore nel profilo di ragionamento**: `interleaved` in `Profile`, attivo per Qwen3.6,
   Qwen3.8 e LFM2.5 e spento per Gemma 4 finché non si decide sulle `tool_calls` sintetiche.
   - Si misura con `multistep`.
   - Si verifica che `tools` e `planning` restino al 100%.
   - Se C non migliora successo o passi, si torna ad A con il dato in mano.
4. **Opzione D da decidere dopo le misure**, possibilmente insieme alla revisione di ProxmoxMcp (ISS-27). Tool composti
   riducono il numero di passi, e quindi quanto conta conservare il pensiero tra un passo e l'altro.
5. **Niente pensiero tra turni dell'utente** (opzione E) finché la conversazione entra come memoria testuale.

---

## 9. Risultati (E8, 2026-10-30)

Implementazione: punti 1–3 della proposta.
- `generate_plan_structure` riceve il piano steso, e la stesura vede il catalogo.
- Suite `multistep`: 10 casi, agent loop completo con i risultati dei tool simulati.
- `interleaved` nel profilo, acceso per Qwen3.6, Qwen3.8, Qwen3 e LFM2.5.
- `AGENT_INTERLEAVED_THINKING` e `--interleaved on|off` per i confronti.

### 9.1 `multistep` con Qwen3.6-35B, 10 casi × 3 esecuzioni

| Run | Pensiero spento | Pensiero acceso | Note |
| :--- | :--- | :--- | :--- |
| 1 | 57% (17/30) | 53% (16/30) | prima versione dei casi |
| 2 | 77% (23/30) | 60% (18/30) | regola anti-ripetizione che citava solo lo storico in testo |
| **3** | **63% (19/30)** | **70% (21/30)** | regola corretta: confronto pulito |

Il run 2 ha mostrato un difetto del prompt di sistema. La regola 7 vietava di ripetere un'azione il cui risultato fosse
nella sezione "History of actions executed in this turn". Nel loop a messaggi quella sezione non c'è, quindi il modello
non applicava la regola. Ora la regola copre anche i risultati che arrivano come messaggi.

Misure del run 3, medie per esecuzione:

| | Pensiero spento | Pensiero acceso |
| :--- | :--- | :--- |
| successo | 63% | 70% |
| tempo mediano | 77 s | 65 s |
| token generati | 2522 | 1573 (−38%) |
| passi | 2,3 | 3,23 |
| chiamate | 2,6 | 3,43 |
| chiamate non di sola lettura (`exec_lxc_command`, `exec_host_command`, `python_interpreter`) | 0,37 | 0,8 |

### 9.2 Lettura

- **Qualità:** la differenza è dentro la varianza tra un run e l'altro. Con il pensiero spento la stessa
  configurazione ha dato 57%, 77% e 63%. Non c'è un peggioramento, ma nemmeno un guadagno dimostrato su 30 esecuzioni.
- **Costo:** con il pensiero conservato il modello ragiona meno a ogni passo, perché non ricostruisce da capo il
  perché delle chiamate precedenti. Genera il 38% di token in meno ed è più rapido, anche facendo più passi. È il
  vantaggio dichiarato da Qwen ("meno ragionamento ripetuto").
- **Comportamento:** il modello approfondisce di più. Per esempio controlla lo spazio su disco dopo aver letto un
  errore "No space left", e usa più spesso tool che eseguono comandi. Nell'uso reale ognuna di queste chiamate chiede
  un'approvazione nella UI.
- **Casi che migliorano:** quelli in cui il modello deve ricordare cosa sta cercando:
  - il confronto tra gli snapshot di due container (8/9 contro 4/9 nei tre run);
  - lo swap di nextcloud (8/9 contro 6/9).
- **Casi che restano difficili in entrambe le varianti:**
  - risposte dall'elenco degli eventi senza aprirne il dettaglio;
  - date da convertire da un timestamp Unix;
  - il DNS da collegare al container tramite le prenotazioni IP;
  - le chiamate inventate scritte in `final_answer` ([ISS-28](../status/02-ISSUES.md#iss-28)).

### 9.3 Decisione

Il pensiero tra i passi resta **acceso** per i profili interleaved. A parità di successo costa meno token e meno
tempo, ed è la configurazione raccomandata dai produttori. Il controllo da tenere d'occhio è l'aumento delle chiamate
che eseguono comandi.

Restano da misurare:
- Qwen3.8 e Gemma 4: per Gemma 4 l'interleaved resta spento, perché richiederebbe `tool_calls` native;
- il tool calling nativo (opzione D), con la revisione di ProxmoxMcp.

### 9.4 LFM2.5-24B-A2B (2026-10-31)

Preset `LFM2.5-24B-A2B-Fast` con cache `q8_0`. Prima della misura su CT 100 la cache turbo faceva girare la flash
attention sulla CPU: vedi [llama.cpp su CT 100](../../../../docs/services/llama-cpp/README.md#5-cache-kv-turboquant-head-dim-non-multipla-di-128).
`multistep` con 20 casi × 2 esecuzioni:

| | Pensiero spento | Pensiero acceso |
| :--- | :--- | :--- |
| successo | 42% (17/40) | 35% (14/40) |
| chiamate | 4,15 | 5,85 |
| chiamate che eseguono comandi | 0,38 | 0,93 |
| argomenti non validi | 0,75 | 1,07 |
| token generati | 6065 | 4154 |

- Con il pensiero conservato LFM2.5 si allunga: più chiamate, più comandi e più argomenti sbagliati.
- I casi superati calano. La differenza è di tre esecuzioni, ma tutte le misure vanno nella stessa direzione.
- **`interleaved` è spento per LFM2.5.** Il profilo segue la misura e non il template, che il pensiero lo conserverebbe.
- Con la cache corretta, `tools` è all'82% (3,4 s per caso) e `planning` al 100% (39 s per caso).

`planning` con la stesura del piano tradotta resta al 100% (4/4), e `tools` al 100% (17/17, 6,5 s). La durata di
`planning` sale a 252 s per caso perché ora misura anche la stesura con 8192 token di ragionamento, come avviene in
plan.

---

## Fonti

1. [MiniMax: Why is interleaved thinking important for M2][minimax]
2. [Anthropic: Extended thinking][anthropic-ext]
3. [Anthropic: Thinking in tool and multi-turn workflows][anthropic-tools]
4. [OpenAI Cookbook: Better performance from reasoning models using the Responses API][openai-items]
5. [OpenAI: New tools and features in the Responses API][openai-responses]
6. [Google: Thinking mode in Gemma][gemma-thinking]
7. [Qwen3.6-35B-A3B, scheda del modello][qwen36]
8. [Qwen3.8-27B, scheda del modello][qwen38]
9. [Z.ai: Thinking mode (interleaved, preserved, turn-level)][zai]
10. [DeepSeek API: Thinking mode][deepseek]
11. [Wang et al., When Can Agents Forget Their Reasoning? (arXiv 2609.29875)][iclr-compress]
12. [Liu et al., On Effectiveness and Efficiency of Agentic Tool-calling and RL Training (arXiv 2606.00135)][liu-toolcalling]
13. [r/LocalLLaMA: Qwen3.6 `preserve_thinking` con llama.cpp][reddit-preserve]
14. Template dei GGUF su CT 100 (`tokenizer.chat_template` di Qwen3.6-35B-A3B, Qwen3.8-27B GSQ e AD, Gemma 4 26B-A4B,
    LFM2.5-24B-A2B)
15. Sorgenti di llama.cpp: fork `TheTom/llama-cpp-turboquant` `407f3237b` su CT 100 e `references/llama.cpp`
    (`common/chat.cpp`, `common/jinja/caps.cpp`, `common/arg.cpp`, `tools/server/server-context.cpp`)

[minimax]: https://www.minimax.io/news/why-is-interleaved-thinking-important-for-m2
[anthropic-ext]: https://platform.claude.com/docs/en/build-with-claude/extended-thinking
[anthropic-tools]: https://platform.claude.com/docs/en/build-with-claude/thinking-tool-workflows
[openai-items]: https://cookbook.openai.com/examples/responses_api/reasoning_items
[openai-responses]: https://openai.com/index/new-tools-and-features-in-the-responses-api
[gemma-thinking]: https://ai.google.dev/gemma/docs/capabilities/thinking
[qwen36]: https://huggingface.co/Qwen/Qwen3.6-35B-A3B
[qwen38]: https://huggingface.co/Qwen/Qwen3.8-27B
[zai]: https://docs.z.ai/guides/capabilities/thinking-mode
[deepseek]: https://api-docs.deepseek.com/guides/thinking_mode
[iclr-compress]: https://arxiv.org/abs/2609.29875
[liu-toolcalling]: https://arxiv.org/abs/2606.00135
[reddit-preserve]: https://reddit.sentinel-team.org/posts/1sne4gh/snapshots/2026-04-17T23%3A20%3A42.645991Z
