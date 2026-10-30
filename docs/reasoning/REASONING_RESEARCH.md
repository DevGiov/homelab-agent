# Ragionamento dei modelli: come funziona, come lo gestiscono i motori di inferenza, llama.cpp e i modelli dei preset

Ricerca del 2026-10-29, base per la fase E7 della [roadmap](../status/04-ROADMAP.md) ("budget di ragionamento per modello").
Copre il funzionamento del ragionamento nei modelli, il modo in cui lo espongono le API e i motori di inferenza, il
comportamento esatto di llama.cpp nella build che gira su CT 100 e, modello per modello, le famiglie presenti nei preset
adatte a un agente. In fondo: cosa fa oggi il backend e cosa ne segue per E7.

---

## 1. In sintesi

1. **Il ragionamento è testo normale**, generato prima della risposta dentro marcatori speciali (`<think>…</think>`,
   `<|channel>thought…<channel|>`): costa latenza, contesto e KV cache come qualunque altro token. Il motore di
   inferenza lo separa dalla risposta (`reasoning_content`) solo se riconosce i marcatori del modello.
2. **Tre tipi di modelli nei preset:** sempre ragionanti (LFM2.5-24B-A2B), ibridi con interruttore (Qwen3.6,
   Qwen3.8, Gemma 4), senza ragionamento (Phi-4, Phi-4-mini). Ognuno si accende, si spegne e si dosa in modo diverso.
3. **Due modi di dosare il ragionamento:**
   - *livello di sforzo* (soft): un'istruzione nel template che il modello segue, per esempio `reasoning_effort` di
     Qwen3.8 (`low`, `medium`, `xhigh`). Non garantisce una lunghezza.
   - *budget* (rigido): il campionatore di llama.cpp conta i token di ragionamento e, a budget esaurito, forza il tag di
     chiusura. Garantisce il limite ma tronca il pensiero a metà.
4. **Più ragionamento non vuol dire agente migliore.** Negli agenti i modelli che ragionano a lungo tendono a fidarsi delle
   proprie simulazioni invece di agire e osservare l'ambiente, e il successo cala ([Cuadron et al., 2025][overthinking]);
   il ragionamento esplicito può peggiorare il rispetto delle istruzioni ([Li et al., 2025][when-thinking-fails]). Serve
   quanto basta per la fase: poco per scegliere un tool, di più per pianificare.
5. **Nel backend di oggi ci sono tre difetti concreti** (dettagli nella sezione 6): il riconoscimento dei modelli che
   ragionano per parole chiave nel nome sbaglia Gemma 4, LFM2.5 e Phi-4; plan "senza limite" in realtà ragiona al
   massimo 512 token (il default del preset); la temperatura è fissa e molto più bassa di quella raccomandata per i
   modelli in modalità ragionamento.
6. **Per E7** serve un profilo di ragionamento per modello (tipo, interruttore, livelli, campionamento consigliato,
   gestione della cronologia) e un budget per *fase* del turno invece che per modalità, sempre inviato in modo esplicito.

---

## 2. Come funziona il ragionamento nei modelli

### 2.1 Token di ragionamento e addestramento

Un modello che ragiona genera prima una catena di pensiero e poi la risposta. Per il modello sono token come gli altri:
cambiano solo i marcatori che li racchiudono e l'addestramento che li ha resi utili. DeepSeek-R1 ha mostrato che
l'apprendimento per rinforzo con ricompense verificabili (risposte controllabili in matematica e codice) fa emergere
catene lunghe con verifiche e ripensamenti ([DeepSeek-AI, 2025][r1]). Le famiglie più recenti (Qwen3.x, Gemma 4,
LFM2.5) aggiungono traiettorie con chiamate a tool nell'addestramento, per usare il ragionamento anche negli agenti.

Il ragionamento è una forma di *test-time compute*: si scambia tempo di generazione con accuratezza. s1 lo ha reso
esplicito con il *budget forcing*: troncare il pensiero quando supera un limite, oppure allungarlo aggiungendo "Wait"
quando il modello vorrebbe chiudere. Allungare portava AIME24 dal 50% al 57% senza riaddestrare ([Muennighoff et al.,
2025][s1]). Il guadagno vale per problemi che si risolvono ragionando; su compiti che dipendono dalla conoscenza
l'estensione non aiuta ([arXiv 2509.06861][tts-knowledge]).

### 2.2 Tipi di modelli

| Tipo | Comportamento | Nei preset |
| :--- | :--- | :--- |
| Sempre ragionante | il template apre ogni risposta con il tag di pensiero; non esiste una modalità senza | LFM2.5-24B-A2B |
| Ibrido | il ragionamento si accende e si spegne dal template (`enable_thinking`), per richiesta | Qwen3.6-35B-A3B (acceso di default), Qwen3.8-27B (acceso di default), Gemma 4 (spento di default) |
| Senza ragionamento | risponde subito; un'eventuale "catena di pensiero" esiste solo se la chiede il prompt | Phi-4, Phi-4-mini |

### 2.3 Come si controlla

- **Interruttore nel template.** Il template Jinja del modello legge una variabile (`enable_thinking`) e cambia il
  prompt: per spegnere, Qwen inserisce un blocco di pensiero vuoto, Gemma 4 toglie il token `<|think|>` dal system
  prompt (o, nei modelli 12B/26B/31B, inserisce un canale di pensiero vuoto) ([Qwen3.6][qwen36], [Google][gemma-thinking]).
- **Livelli di sforzo.** Il template aggiunge un'istruzione diversa per livello. In Qwen3.8 `xhigh` chiede di pensare
  con cura, `medium` non aggiunge nulla, `low` chiede un pensiero breve ([soster/qwen38-thinking-levels][qwen38-levels]).
  È un controllo morbido: il modello di solito obbedisce, ma la lunghezza non è garantita. Lo stesso schema è usato da
  gpt-oss ("Reasoning: low/medium/high" nel system prompt) e dalle API commerciali (`reasoning_effort` di OpenAI).
- **Budget di token.** Il motore conta i token dopo il tag di apertura e, al limite, forza il tag di chiusura (ed
  eventualmente una frase di transizione). È un limite rigido, indipendente dal modello purché il motore conosca i tag.
  Il rovescio: il modello risponde partendo da un ragionamento interrotto. Una frase di transizione ("ok, rispondo con
  quello che ho") rende il passaggio meno brusco; vLLM e llama.cpp la supportano.

### 2.4 Il ragionamento nella cronologia

Cosa fare dei pensieri dei turni precedenti è una scelta del modello, non del motore:

- **Toglierli** (comportamento classico): la cronologia contiene solo le risposte. Gemma 4 lo richiede tra un turno e
  l'altro, ma *non* tra le chiamate a tool dello stesso turno ([Google][gemma-thinking]). Qwen3.6 tiene di default solo
  il pensiero dell'ultimo turno dell'utente ([Qwen3.6][qwen36]).
- **Conservarli** (*preserved* o *interleaved thinking*): il pensiero di ogni passo resta nel contesto del successivo.
  Anthropic lo ha introdotto con Claude 4 per i tool; MiniMax-M2 lo considera essenziale per gli agenti, perché senza il
  modello ripete chiamate e perde il piano ([MiniMax][minimax-interleaved]). Qwen3.8 conserva i pensieri di tutta la
  cronologia di default (`preserve_thinking`) e dichiara che migliora la coerenza delle decisioni e il riuso della KV
  cache ([Qwen3.8][qwen38]); in Qwen3.6 si attiva con `preserve_thinking`.

Per riusare i pensieri il client deve rimandarli: con l'API in stile OpenAI si fa mettendo `reasoning_content` nei
messaggi dell'assistente, campo che llama.cpp legge e passa al template (sezione 4.5).

### 2.5 Costi e rischi

- **Overthinking negli agenti.** Su 4.018 traiettorie di SWE-bench Verified, i modelli che ragionano di più tendono a
  paralisi da analisi, azioni avventate e abbandoni prematuri, e il successo cala al crescere del punteggio di
  overthinking ([Cuadron et al., 2025][overthinking]).
- **Istruzioni meno rispettate.** Su più di 20 modelli, la catena di pensiero esplicita abbassa l'accuratezza su IFEval
  e ComplexBench: il modello trascura vincoli semplici o aggiunge contenuto non richiesto. Ragionare solo quando serve
  recupera gran parte della perdita ([Li et al., 2025][when-thinking-fails]).
- **Costo di un livello alto.** Con Qwen3.8-27B a `xhigh`, un compito di generazione ha richiesto 22.276 token di
  ragionamento e 21 minuti, contro 137 s con il ragionamento spento ([Zentor][qwen38-overthinking]). La scheda del
  modello avverte però che negli agenti uno sforzo più basso non riduce sempre il tempo totale del compito ([Qwen3.8][qwen38]).
- **Campionamento.** I modelli in modalità ragionamento sono tarati per temperature alte (Qwen 0,6–1,0, Gemma 1,0). Le
  schede di Qwen3 sconsigliano esplicitamente la decodifica greedy in modalità ragionamento, che porta a ripetizioni
  infinite ([Qwen3-8B][qwen3-card]).

---

## 3. Come lo espongono API e motori di inferenza

| | Accendere / spegnere | Livelli | Budget rigido | Campo della risposta | Pensieri nella cronologia |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **OpenAI API** ([guida][openai-reasoning]) | `reasoning_effort` (`none` dove supportato) | `minimal`/`low`/`medium`/`high` | no | non esposto (riassunti) | elementi di reasoning cifrati da rimandare (Responses API) |
| **Anthropic API** ([guida][anthropic-thinking]) | `thinking: {type: enabled}` | effort sui modelli recenti | `budget_tokens` | blocchi `thinking` | i blocchi vanno rimandati con i tool (interleaved) |
| **llama.cpp** | `chat_template_kwargs.enable_thinking`, `--reasoning on/off` | via template (`chat_template_kwargs.reasoning_effort`) | `reasoning_budget_tokens` per richiesta, `--reasoning-budget` | `reasoning_content` | `reasoning_content` nei messaggi passato al template |
| **vLLM** | `chat_template_kwargs` (chiave dipende dal modello) | via template; per Gemma 4 anche `reasoning_effort` | `thinking_token_budget` per richiesta | `reasoning` (prima `reasoning_content`) | non documentato |
| **SGLang** | `chat_template_kwargs` | via template | — | `reasoning_content` | — |
| **Ollama** | `think: true/false` | `think: "low"/"medium"/"high"` per i modelli che li dichiarano | non documentato | `message.thinking` | — |

Note:
- vLLM e SGLang separano il ragionamento con un *reasoning parser* scelto all'avvio (`--reasoning-parser qwen3` per
  Qwen3.6, `gemma4` per Gemma 4; per LFM2.5 Liquid indica `qwen3-thinking` in SGLang). Il budget di vLLM forza il tag
  di chiusura come quello di llama.cpp e accetta una frase di transizione ([vLLM][vllm-reasoning]).
- In vLLM le chiamate a tool si leggono solo dal contenuto, non dal ragionamento; l'output strutturato si applica dopo
  la fine del ragionamento ([vLLM][vllm-reasoning]).
- In Ollama i livelli valgono solo per i modelli che li dichiarano (`gpt-oss`); un livello sconosciuto ricade sul default
  del modello ([Ollama][ollama-thinking]).

---

## 4. llama.cpp nel dettaglio

### 4.1 Quale llama.cpp gira

Su CT 100 il server è la build **10726** del fork **`TheTom/llama-cpp-turboquant`** (commit `407f3237b`, 2026-09-06),
che aggiunge le KV cache `turbo2`/`turbo3` usate nei preset. Il clone in `references/llama.cpp` segue upstream
(`ggml-org/llama.cpp`, 11.997 commit al 2026-10-29) e non contiene quel commit: per il comportamento esatto del server
i sorgenti di riferimento sono quelli in `/root/llama-cpp-turboquant` su CT 100. Il codice del ragionamento descritto
qui è stato letto lì.

### 4.2 Opzioni del server

| Opzione | Effetto |
| :--- | :--- |
| `--jinja` | usa il template Jinja del modello: necessario perché `enable_thinking` e gli altri kwargs abbiano effetto |
| `--reasoning on\|off\|auto` | accende o spegne il ragionamento per default (`auto`: lo decide il template). Sostituisce `enable_thinking` in `--chat-template-kwargs`, che ora è deprecato |
| `--reasoning-format none\|deepseek\|deepseek-legacy` | `deepseek` mette i pensieri in `message.reasoning_content`; `none` li lascia nel testo |
| `--reasoning-budget N` | budget di default: `-1` illimitato, `0` chiusura immediata, `N` token |
| `--reasoning-budget-message` | frase inserita prima del tag di chiusura quando il budget finisce |
| `--reasoning-preserve` | imposta `preserve_reasoning` per i template che lo supportano |
| `--chat-template-kwargs` | variabili di default per il template (per esempio `{"enable_thinking": false}`) |
| `--skip-chat-parsing` | nessuna separazione: ragionamento e tool call finiscono nel contenuto |

### 4.3 Parametri per richiesta (`/v1/chat/completions`)

| Campo | Effetto |
| :--- | :--- |
| `chat_template_kwargs` | variabili del template per questa richiesta: `enable_thinking` (booleano; una stringa dà errore), `preserve_thinking`, `reasoning_effort` (per i template che lo leggono, come Qwen3.8) |
| `reasoning_effort` (top-level) | nel fork in uso gestisce solo `"none"` (spegne il ragionamento); gli altri valori vengono ignorati. Le build upstream più recenti accettano anche `reasoning_effort` e `reasoning: {effort}` ([soster][qwen38-levels]) |
| `reasoning_budget_tokens` (o `thinking_budget_tokens`) | budget di questa richiesta; `-1` o assente = **default del server** (`--reasoning-budget` del preset) |
| `reasoning_budget_message` | frase di transizione per questa richiesta |
| `reasoning_control` | arma il controllo dal vivo: `POST /v1/chat/completions/control` con l'azione `reasoning_end` chiude il ragionamento della generazione in corso |
| `reasoning_format` | formato di separazione per questa richiesta |

### 4.4 Come funziona il budget

Il budget è un campionatore (`common/reasoning-budget.cpp`) con una macchina a stati:

1. **IDLE**: attende il tag di apertura del modello.
2. **COUNTING**: conta i token; se il modello chiude da solo il ragionamento, passa a DONE.
3. **WAITING_UTF8**: budget esaurito, lascia completare un carattere UTF-8 a metà.
4. **FORCING**: forza, token per token, la frase di transizione e il tag di chiusura (tutti gli altri logit a −∞).
5. **DONE**: nessun intervento fino alla fine.

Dettagli che contano:
- Il budget si applica **solo se il template dichiara i tag di fine pensiero**; altrimenti viene ignorato in silenzio.
- Il prompt di generazione passa dal campionatore: se il template apre già `<think>` (come Qwen), il conteggio parte
  dal primo token generato.
- Con `0` il tag di chiusura viene forzato subito: per un modello sempre ragionante come LFM2.5 significa rispondere
  senza il ragionamento per cui è addestrato.
- Il campionatore del budget viene creato anche quando c'è una grammatica *lazy* (tool call, output strutturato), per
  sapere quando il ragionamento è finito e la grammatica deve partire.

### 4.5 Risposta e cronologia

- Con `--reasoning-format deepseek` il pensiero arriva in `message.reasoning_content` (in streaming in
  `delta.reasoning_content`) e il contenuto ne è privo.
- Nei messaggi dell'assistente inviati nella richiesta, llama.cpp legge `reasoning_content` e lo passa al template
  (come `thinking` dove il template lo chiama così): è il modo di conservare i pensieri tra un passo e l'altro, se il
  template li usa (`preserve_thinking`).

### 4.6 Preset attuali (`/root/models-preset.ini`)

- **Globale `[*]`:** `reasoning-budget = 512`, `reasoning-format = deepseek`.
- `[Gemma-4-26B-Vision-Q3]`: `reasoning = off`, `reasoning-format = none`.
- `[Gemma-4-E4B-3dPrint-*]`: `chat-template-kwargs = {"enable_thinking": false}` (forma deprecata).
- `[Andy-4]`, `[Andy-4.2]`: `reasoning-budget = 256`.
- Nessun preset imposta il campionamento consigliato per il ragionamento, salvo `temp`/`repeat-penalty` su alcune
  varianti (Qwen3.8-Obliterated a temperatura 0, Gemma 4 26B con `repeat-penalty 1.15`, Andy-4.2 con i valori Qwen).
  Il backend comunque invia `temperature` in ogni richiesta, che prevale sul preset.

---

## 5. Modelli dei preset

### 5.1 Esclusi

| Preset | Motivo |
| :--- | :--- |
| `Emma-5` | modello italiano molto piccolo (F16 da 1,2 GB, contesto 8K), non adatto a un agente con tool |
| `Gemma-4-E4B-3dPrint-v1-Q4/Q8`, `v1b-Q8` | fine-tuning per l'analisi dei difetti di stampa FDM, con prompt e schema di output propri |
| `Andy-4`, `Andy-4.2` | fine-tuning per il bot Minecraft (Andy-4.2 è Qwen3.5 9B), con il loro budget di 256 token |

### 5.2 Qwen3.6-35B-A3B (`Qwen3.6-35B`, `Qwen3.6-35B-HugeCtx`)

- **Architettura:** MoE da 35B con 3B attivi, 40 strati ibridi (3 Gated DeltaNet per ogni Gated Attention), encoder
  visivo, MTP; 262K token nativi ([Qwen3.6][qwen36]).
- **Ragionamento:** ibrido, **acceso di default**. Si spegne con `chat_template_kwargs: {"enable_thinking": false}`.
  `/think` e `/nothink` non sono supportati. Nessun livello di sforzo documentato: per dosarlo resta il budget.
- **Cronologia:** di default tiene solo il pensiero dell'ultimo turno; `preserve_thinking: true` li conserva tutti,
  consigliato per gli agenti (meno ragionamento ripetuto, KV cache riusata meglio).
- **Campionamento consigliato:**

  | Modalità | temperature | top_p | top_k | min_p | presence_penalty |
  | :--- | :--- | :--- | :--- | :--- | :--- |
  | Ragionamento, generale | 1,0 | 0,95 | 20 | 0 | 1,5 |
  | Ragionamento, codice preciso | 0,6 | 0,95 | 20 | 0 | 0 |
  | Senza ragionamento | 0,7 | 0,80 | 20 | 0 | 1,5 |

- **Lunghezza:** la scheda indica 32.768 token di output per la maggior parte delle richieste.
- **Agente:** il modello più usato e con i risultati migliori nelle nostre suite (`tools` 100%, `recall` 100%,
  `planning` 75–100%). Tool calling forte; in vLLM il parser è `qwen3_coder`.

### 5.3 Qwen3.8-27B (tutte le varianti `Qwen3.8-27B-*`)

- **Architettura:** denso da 27B, 64 strati ibridi (3 Gated DeltaNet per ogni Gated Attention), encoder visivo, MTP;
  262K token nativi ([Qwen3.8][qwen38]). I preset con `spec-type = draft-mtp` usano la testa MTP per la decodifica
  speculativa (circa +70% di velocità secondo [Zentor][qwen38-overthinking]).
- **Ragionamento:** ibrido, **acceso di default**, con **livelli** `reasoning_effort` = `xhigh` (default), `medium`,
  `low`, da passare in `chat_template_kwargs`. Valori diversi fanno fallire il template (quello originale rifiuta anche
  `high`). Il default `xhigh` produce ragionamenti molto lunghi: la comunità indica `low` come base e `medium` per
  compiti in più passi ([Zentor][qwen38-overthinking]).
- **Cronologia:** `preserve_thinking` **attivo di default**.
- **Campionamento consigliato:** ragionamento temperature 1,0, top_p 0,95, top_k 20, presence_penalty 0; senza
  ragionamento 0,7 / 0,80 / 20 / presence_penalty 1,5.
- **Lunghezza:** fino a 262.144 token di ragionamento e 131.072 di risposta, dove il motore permette limiti separati.
- **Varianti nei preset:** `Fast`, `HugeCtx` e `Unsloth-IQ4` usano quantizzazioni standard; `Atomic` e `GSQ` sono
  quantizzazioni di terze parti più compresse (GSQ con testa MTP); `Obliterated` è una versione modificata per
  rimuovere i rifiuti, non documentata dal produttore, che non aggiunge nulla di utile a un agente con approvazioni:
  va valutata con le suite prima di usarla. I preset `Obliterated` hanno `temp = 0.0`, in conflitto con la
  raccomandazione per il ragionamento.

### 5.4 Gemma 4 (`Gemma-4-12B*`, `Gemma-4-26B-*`, `Gemma-4-E4B`)

- **Architettura:** E4B denso (con PLE) e 128K di contesto; 12B denso; 26B-A4B MoE con 4B attivi; 262K per 12B e
  26B ([Unsloth][unsloth-gemma4]).
- **Ragionamento:** ibrido, **spento di default**. Si accende con il token `<|think|>` all'inizio del system prompt,
  che il template inserisce con `enable_thinking: true`. Output nei canali `<|channel>thought … <channel|>`. Spento,
  12B e 26B emettono comunque un canale di pensiero vuoto. Nessun livello né budget documentati da Google: per dosarlo
  resta il budget di llama.cpp. vLLM accetta anche `reasoning_effort` per Gemma 4 ([vLLM][vllm-reasoning]).
- **Problemi noti in llama.cpp:** con `enable_thinking: false` e budget 0 alcuni utenti vedono ancora ragionamento,
  risolto con `--reasoning off` ([discussione][gemma-disable]); con `json_schema` il ragionamento può comparire anche
  se spento ([issue][gemma-issue]).
- **Cronologia:** togliere i pensieri tra un turno e l'altro, ma conservarli tra le chiamate a tool dello stesso turno.
- **Campionamento consigliato:** temperature 1,0, top_p 0,95, top_k 64 (Google, via [Unsloth][unsloth-gemma4]). Alcuni
  preset aggiungono `repeat-penalty 1.15`, non raccomandato dal produttore.

### 5.5 LFM2.5-24B-A2B (`LFM2.5-24B-A2B-*`)

- **Architettura:** MoE da 24B con circa 2B attivi, 40 strati (30 convoluzioni brevi con gate e 10 di attenzione GQA);
  131K token ([Liquid][lfm25]).
- **Ragionamento:** **sempre acceso**: il template apre ogni risposta con `<think>` e non esiste una modalità senza.
  `enable_thinking: false` non ha effetto; l'unico modo di accorciarlo è il budget di llama.cpp, e a budget 0 il
  modello risponde senza il ragionamento per cui è addestrato.
- **Campionamento consigliato:** temperature 0,1, top_k 50, repetition_penalty 1,05. Gli esempi ufficiali usano
  4.096 token di output e chiedono di lasciare spazio al ragionamento.
- **Agente:** addestrato con chiamate a tool e traiettorie multi-turno; in SGLang `--tool-call-parser lfm2`. Nelle
  nostre suite ha dato risultati inferiori a Qwen3.6, e il prompt processing rallenta molto con il contesto (ISS-26).

### 5.6 Phi-4 (14B) e Phi-4-mini (3,8B) (`Phi-4-15B-*`, `Phi-4-mini-*`)

- **Ragionamento:** nessuno. Sono modelli instruct; il ragionamento esplicito è in modelli separati (Phi-4-reasoning)
  che non sono nei preset. `enable_thinking` e il budget non hanno effetto (il template non ha tag di pensiero).
- **Agente:** Phi-4-mini supporta il function calling con i tool in JSON nel system prompt ([Phi-4-Mini][phi4-mini]);
  Phi-4 14B è orientato a matematica e ragionamento in testo. Utili come modelli veloci senza ragionamento.

### 5.7 Riepilogo

| Famiglia | Tipo | Spegnere | Livelli | Cronologia di default | Temperatura consigliata (ragionamento) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Qwen3.6-35B-A3B | ibrido, acceso | `enable_thinking: false` | no | solo ultimo turno | 1,0 (0,6 codice) |
| Qwen3.8-27B | ibrido, acceso | `enable_thinking: false` | `low`/`medium`/`xhigh` | tutti i pensieri | 1,0 |
| Gemma 4 | ibrido, spento | default | no | togliere (tranne tra tool dello stesso turno) | 1,0 |
| LFM2.5-24B-A2B | sempre | no (solo budget) | no | — | 0,1 |
| Phi-4, Phi-4-mini | nessuno | — | — | — | — |

---

## 6. Cosa fa oggi il backend

Codice: `app/llm/providers.py` (`_supports_reasoning`, `_build_payload`), `app/agent/llm_calls.py`,
`app/agent/mode_policy.py`.

| Comportamento | Conseguenza |
| :--- | :--- |
| Il ragionamento si attiva solo se il nome del modello contiene `qwen`, `deepseek`, `r1`, `o1`, `o3`, `mistral`, `think` o `reason` | Gemma 4 (ibrido) non ragiona mai, nemmeno in plan; LFM2.5 riceve `enable_thinking: false`, che ignora, e ragiona fino al budget del preset; Phi-4 è gestito bene per caso |
| Budget per modalità: chat 0, ask 2048, act 8192, plan −1 | con −1 il backend non invia `reasoning_budget_tokens` e il server applica il default del preset: **plan ragiona al massimo 512 token**, meno di ask e act |
| Budget 0 invia `reasoning_budget_tokens: 0` | con LFM2.5 forza la chiusura immediata del pensiero di un modello che ragiona sempre: qualità da misurare |
| Temperatura fissa per chiamata (0,0 output strutturato, 0,2 plan, 0,3 default) | molto più bassa del raccomandato per il ragionamento (Qwen 0,6–1,0, Gemma 1,0); rischio di ripetizioni, già visto con LFM2.5 (ISS-26) |
| Ogni passo dell'agent loop è un nuovo messaggio utente con lo storico dei tool in testo | il ragionamento della selezione di un tool non arriva al passo successivo: niente interleaved thinking, il modello rifà il ragionamento a ogni passo |
| Con il ragionamento attivo, il system prompt riceve un'istruzione a non includere il pensiero nella risposta | coerente con `reasoning_format = deepseek`; non serve con i modelli che separano bene il pensiero |
| Nessun uso di `reasoning_effort`, `preserve_thinking` o `reasoning_budget_message` | Qwen3.8 gira sempre a `xhigh`, i pensieri troncati finiscono senza frase di transizione |

---

## 7. Cosa ne segue per E7

Proposte da validare con le suite (`tools`, `planning`, `rollback`, `recall`), misurando anche la latenza.

1. **Profilo di ragionamento per modello**, al posto delle parole chiave nel nome: tipo (sempre, ibrido, nessuno),
   chiave per accendere e spegnere, livelli supportati, campionamento consigliato per modalità con e senza ragionamento,
   gestione della cronologia. Indicizzato per famiglia del preset (alias del router), con un default prudente per i
   modelli sconosciuti; i campi verificabili dal server (template con supporto al ragionamento) vanno controllati
   all'avvio invece che presunti.
2. **Budget per fase del turno**, non per modalità: routing, consolidamento della memoria e riassunti senza
   ragionamento; selezione dei tool con un budget piccolo; sintesi breve o senza; generazione del piano con il budget
   più alto. Il budget va **sempre inviato in modo esplicito** (mai −1, che significa "default del preset"), con una
   `reasoning_budget_message` per i troncamenti.
3. **Livello prima del troncamento** dove esiste: per Qwen3.8 `reasoning_effort` `low` o `medium` per fase, con il
   budget come rete di sicurezza.
4. **Campionamento dal profilo**: temperatura, top_p, top_k e presence_penalty raccomandati per il modello e per lo
   stato del ragionamento; l'output strutturato con grammatica può restare a temperatura più bassa, da misurare.
5. **Modelli sempre ragionanti**: non forzare budget 0; usare un budget piccolo ma non nullo.
6. **Pensieri tra i passi dell'agent loop** (da valutare a parte, cambio più profondo): rimandare il ragionamento del
   passo precedente come messaggio dell'assistente con `reasoning_content`, con `preserve_thinking` per Qwen, per
   ottenere l'interleaved thinking raccomandato per gli agenti. Approfondito in
   [INTERLEAVED_THINKING.md](INTERLEAVED_THINKING.md): dentro il turno i template lo conservano senza
   `preserve_thinking`, e i messaggi riusano la cache meglio del prompt a messaggio unico.
7. **Matrice di misura**: per ogni modello candidato (Qwen3.6-35B, Qwen3.8-27B in una variante, Gemma-4-26B,
   LFM2.5) le suite con 2–3 configurazioni di budget o livello, per scegliere i valori del profilo con i dati.

---

## Fonti

1. [Qwen3.6-35B-A3B, scheda del modello][qwen36]
2. [Qwen3.8-27B, scheda del modello][qwen38]
3. [soster/qwen38-thinking-levels: livelli di ragionamento di Qwen3.8 con llama.cpp][qwen38-levels]
4. [Zentor: Qwen 3.8 27B overthinking][qwen38-overthinking]
5. [Google: Thinking mode in Gemma][gemma-thinking]
6. [Unsloth: Gemma 4, come eseguirlo in locale][unsloth-gemma4]
7. [llama.cpp, discussione #21338: disattivare il ragionamento di Gemma 4][gemma-disable]
8. [llama.cpp, issue #30256: Gemma 4 e json_schema][gemma-issue]
9. [Liquid AI: LFM2.5-24B-A2B][lfm25]
10. [Phi-4-Mini Technical Report][phi4-mini]
11. [Qwen3-8B, scheda del modello (campionamento in modalità ragionamento)][qwen3-card]
12. [vLLM: Reasoning Outputs][vllm-reasoning]
13. [Ollama: Thinking][ollama-thinking]
14. [DeepSeek-AI, DeepSeek-R1 (arXiv 2501.12948)][r1]
15. [Muennighoff et al., s1: Simple test-time scaling (arXiv 2501.19393)][s1]
16. [Test-Time Scaling in Reasoning Models Is Not Effective for Knowledge-Intensive Tasks Yet (arXiv 2509.06861)][tts-knowledge]
17. [Cuadron et al., The Danger of Overthinking (arXiv 2502.08235)][overthinking]
18. [Li et al., When Thinking Fails (arXiv 2505.11423)][when-thinking-fails]
19. [MiniMax: Why is interleaved thinking important for M2][minimax-interleaved]
20. [OpenAI: Reasoning models][openai-reasoning]
21. [Anthropic: Extended thinking][anthropic-thinking]
22. Sorgenti di llama.cpp: fork `TheTom/llama-cpp-turboquant` build 10726 su CT 100 (`common/arg.cpp`,
    `common/reasoning-budget.{h,cpp}`, `common/sampling.cpp`, `common/chat.cpp`, `tools/server/server-common.cpp`,
    `tools/server/server-context.cpp`) e `references/llama.cpp` (upstream)
23. Preset del router: `/root/models-preset.ini` su CT 100

[qwen36]: https://huggingface.co/Qwen/Qwen3.6-35B-A3B
[qwen38]: https://huggingface.co/Qwen/Qwen3.8-27B
[qwen38-levels]: https://github.com/soster/qwen38-thinking-levels
[qwen38-overthinking]: https://zentor.ai/blog/qwen-3-8-27b-overthinking
[gemma-thinking]: https://ai.google.dev/gemma/docs/capabilities/thinking
[unsloth-gemma4]: https://unsloth.ai/docs/models/gemma-4
[gemma-disable]: https://github.com/ggml-org/llama.cpp/discussions/21338
[gemma-issue]: https://github.com/ggml-org/llama.cpp/issues/30256
[lfm25]: https://docs.liquid.ai/lfm/models/lfm25-24b-a2b
[phi4-mini]: https://arxiv.org/pdf/2503.01743
[qwen3-card]: https://huggingface.co/Qwen/Qwen3-8B
[vllm-reasoning]: https://docs.vllm.ai/en/latest/features/reasoning_outputs/
[ollama-thinking]: https://docs.ollama.com/capabilities/thinking
[r1]: https://arxiv.org/abs/2501.12948
[s1]: https://arxiv.org/abs/2501.19393
[tts-knowledge]: https://arxiv.org/abs/2509.06861
[overthinking]: https://arxiv.org/abs/2502.08235
[when-thinking-fails]: https://arxiv.org/abs/2505.11423
[minimax-interleaved]: https://www.minimax.io/news/why-is-interleaved-thinking-important-for-m2
[openai-reasoning]: https://platform.openai.com/docs/guides/reasoning
[anthropic-thinking]: https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking
