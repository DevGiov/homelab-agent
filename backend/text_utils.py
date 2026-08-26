import re

# Regex to match <think> or <thought> blocks (including attributes like <think time="0.4">)
# It uses DOTALL to match across newlines, and it handles both closed and unclosed tags.
_THINK_OPEN_TAG_RE = re.compile(r'<(?:think|thought|thinking)(?:\s+[^>]*)?>',  flags=re.IGNORECASE)
_THINK_CLOSE_TAG_RE = re.compile(r'</(?:think|thought|thinking)>', flags=re.IGNORECASE)

# Catch-all for a complete block (non-greedy)
_THINK_BLOCK_RE = re.compile(r'<(?:think|thought|thinking)[^>]*>.*?</(?:think|thought|thinking)>', flags=re.IGNORECASE | re.DOTALL)

# Catch-all for unclosed block at the start or anywhere
_THINK_UNCLOSED_RE = re.compile(r'<(?:think|thought|thinking)[^>]*>.*', flags=re.IGNORECASE | re.DOTALL)

def strip_thinking(text: str) -> str:
    """
    Rimuove in modo robusto i blocchi di reasoning (es. <think>...</think>)
    generati dai modelli LLM. 
    Questa operazione previene la rottura del parser JSON se il modello
    decide di pensare ad alta voce prima di restituire l'output strutturato.
    """
    if not text:
        return ""

    # 1. Rimuovi i blocchi correttamente chiusi
    out = _THINK_BLOCK_RE.sub("", text)

    # 2. Se c'è un tag di apertura ma non di chiusura (es. modello interrotto o streaming in blocco)
    # Togliamo tutto ciò che va dal tag di apertura in poi (pericoloso se l'output utile è dopo,
    # ma di solito il JSON è *dopo* il blocco di think. Se il think non è chiuso, il JSON non c'è).
    # Per sicurezza, togliamo solo il tag se il JSON è dopo.
    # Invece di usare _THINK_UNCLOSED_RE, facciamo un replace sui tag orfani:
    out = _THINK_OPEN_TAG_RE.sub("", out)
    out = _THINK_CLOSE_TAG_RE.sub("", out)

    return out.strip()


# --- Reasoning Artifacts Sanitization ---

# Pattern che segnalano l'inizio di un blocco di ragionamento plaintext
_REASONING_HEADER_RE = re.compile(
    r"^(?:"
    r"Here'?s (?:a |my )?thinking process"
    r"|Let me (?:think|analyze|reason|work through)"
    r"|I (?:need to|should|will) (?:think|analyze|reason|consider)"
    r"|Thinking process"
    r"|My reasoning"
    r"|Chain of thought"
    r")",
    re.IGNORECASE
)

# Pattern che segnalano righe interne di ragionamento
_REASONING_LINE_RE = re.compile(
    r"^(?:"
    r"(?:Analyze|Extract|Structure|Draft|Cross-Check|Verify|Check|Review|Identify|Evaluate) .{0,60}:"
    r"|✅\s*(?:Self-Correction|Output|Proceeds|Ready|Done|Verified|Note)"
    r"|(?:Self-Correction|Verification|Note) (?:during|:|/)"
    r"|\[(?:Output|Done|Proceeds|Ready|Output Generation)\]"
    r"|Output (?:generation|matches)"
    r"|Proceeds\.\s*$"
    r"|Draft (?:Construction|Generation|Refinement)"
    r"|Mental (?:Refinement|Draft)"
    r")",
    re.IGNORECASE
)


def strip_reasoning_artifacts(text: str) -> str:
    """Rimuove artefatti di ragionamento plaintext (chain-of-thought) dall'output LLM.

    Intercetta pattern comuni che i modelli reasoning (QwQ, DeepSeek-R1, ecc.)
    producono FUORI dai tag <think>, es. "Here's a thinking process:", analisi
    step-by-step in inglese, marcatori ✅ Self-Correction, "Draft Construction", ecc.
    """
    if not text or len(text) < 100:
        return text

    # --- Pattern 1: blocco reasoning in testa ---
    # Se il testo inizia con un header di ragionamento (inglese), cerchiamo
    # la fine del blocco e restituiamo solo il contenuto dopo.
    first_line = text.lstrip()[:300]
    if _REASONING_HEADER_RE.match(first_line):
        # Cerca l'ultimo marcatore di fine reasoning nel testo
        end_markers_re = re.compile(
            r"(?:"
            r"✅\s*(?:Output generation|Proceeds|Ready|Done)"
            r"|\[Output Generation\]"
            r"|Output matches the"
            r"|Proceeds\.\s*(?:\[.*?\])?"
            r"|See response\."
            r").*?$",
            re.IGNORECASE | re.MULTILINE
        )
        last_end = 0
        for m in end_markers_re.finditer(text):
            last_end = m.end()

        if last_end > 0:
            remaining = text[last_end:].strip()
            # Sanity check: il contenuto reale deve essere sostanziale
            if remaining and len(remaining) > 50:
                return remaining

    # --- Pattern 2: strip di righe isolate di ragionamento ---
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and _REASONING_LINE_RE.match(stripped):
            continue
        cleaned_lines.append(line)

    return '\n'.join(cleaned_lines).strip()


def clean_synthesis_content(text: str) -> str:
    """Pipeline di sanitizzazione per il content delle chiamate di synthesis.

    Applica in sequenza:
    1. strip_thinking()   — rimuove tag <think>...</think>
    2. strip_reasoning_artifacts() — rimuove ragionamento plaintext
    """
    if not text:
        return ""
    out = strip_thinking(text)
    out = strip_reasoning_artifacts(out)
    return out.strip()
