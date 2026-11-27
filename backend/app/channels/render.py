"""Dalla risposta Markdown ai pezzi di un messaggio di canale.

- `split_markdown`: divide alla lunghezza massima sui confini di paragrafo, poi di riga, mai dentro un blocco di codice:
  un blocco troppo lungo si divide per righe, chiudendo il blocco in fondo a ogni pezzo e riaprendolo nel successivo;
- `strip_markdown`: la versione per i canali di solo testo, senza i segni del Markdown;
- `to_telegram_html`: l'HTML ristretto di Telegram (tutto il testo con l'escape, codice in `<pre>`, tabelle in monospazio);
- `render_chunks`: l'insieme, secondo le capacità del canale;
- `literal`: un testo fisso del hub (avvisi, comandi) nel formato del canale.
"""
import html
import re
from typing import List, Optional, Tuple

from app.channels.base import Capabilities

_FENCE_OPEN = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)(?:\s+#+)?\s*$")
_RULE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
_QUOTE = re.compile(r"^\s*>+ ?")
_BULLET = re.compile(r"^(\s*)[*+]\s+")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]*)[^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)[^)]*\)")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_ITALIC_STAR = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])")
_ITALIC_UNDERSCORE = re.compile(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])")
_INLINE_CODE = re.compile(r"(`+)(.+?)\1")


def _plain_inline(text: str) -> str:
    def link(m: "re.Match[str]") -> str:
        label, url = m.group(1), m.group(2)
        return url if label == url else f"{label} ({url})"

    text = _IMAGE.sub(lambda m: f"{m.group(1)} ({m.group(2)})".strip() if m.group(1) else m.group(2), text)
    text = _LINK.sub(link, text)
    text = _BOLD.sub(r"\2", text)
    text = _STRIKE.sub(r"\1", text)
    text = _ITALIC_STAR.sub(r"\1", text)
    return _ITALIC_UNDERSCORE.sub(r"\1", text)


def _plain_line(line: str) -> Optional[str]:
    """Una riga senza i segni del Markdown; None se la riga è solo decorazione (linea orizzontale, separatore di tabella)."""
    if _RULE.match(line) or _TABLE_SEPARATOR.match(line):
        return None
    heading = _HEADING.match(line)
    if heading:
        line = heading.group(1)
    else:
        line = _BULLET.sub(r"\1- ", _QUOTE.sub("", line))
    return _plain_spans(line)


def _plain_spans(text: str) -> str:
    # Il codice in linea resta com'è: dentro i backtick `*` e `_` non sono segni
    parts = _INLINE_CODE.split(text)
    out = []
    for i in range(0, len(parts), 3):
        out.append(_plain_inline(parts[i]))
        if i + 2 < len(parts):
            out.append(parts[i + 2])
    return "".join(out)


def _closes(line: str, marker: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= len(marker) and stripped == stripped[0] * len(stripped) and stripped[0] == marker[0]


def strip_markdown(text: str) -> str:
    """Il testo senza i segni del Markdown: titoli, grassetto, corsivo, codice, link e citazioni. Il contenuto dei blocchi
    di codice resta com'è, senza i recinti."""
    out: List[str] = []
    marker: Optional[str] = None
    for line in text.splitlines():
        if marker is None:
            opened = _FENCE_OPEN.match(line)
            if opened:
                marker = opened.group(2)
                continue
            plain = _plain_line(line)
            if plain is not None:
                out.append(plain)
        elif _closes(line, marker):
            marker = None
        else:
            out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


# --- Divisione -------------------------------------------------------------------------------------

Block = Tuple[str, str, List[str]]  # (tipo "text" | "code", riga di apertura del recinto, righe)


def _blocks(text: str) -> List[Block]:
    """Paragrafi (separati da righe vuote) e blocchi di codice (un solo blocco, righe vuote comprese)."""
    blocks: List[Block] = []
    paragraph: List[str] = []
    code: Optional[List[str]] = None
    opening, marker = "", ""

    def flush_paragraph():
        if paragraph:
            blocks.append(("text", "", list(paragraph)))
            paragraph.clear()

    for line in text.splitlines():
        if code is None:
            opened = _FENCE_OPEN.match(line)
            if opened:
                flush_paragraph()
                code, opening, marker = [], line.rstrip(), opened.group(2)
            elif line.strip():
                paragraph.append(line.rstrip())
            else:
                flush_paragraph()
        elif _closes(line, marker):
            blocks.append(("code", opening, code))
            code = None
        else:
            code.append(line.rstrip())
    flush_paragraph()
    if code is not None:  # recinto non chiuso (risposta troncata): lo si chiude
        blocks.append(("code", opening, code))
    return blocks


def _hard_split(line: str, limit: int) -> List[str]:
    """Una riga più lunga del limite: si taglia all'ultimo spazio entro il limite, altrimenti al limite."""
    pieces = []
    while len(line) > limit:
        cut = line.rfind(" ", 1, limit + 1)
        if cut <= 0:
            pieces.append(line[:limit])
            line = line[limit:]
        else:
            pieces.append(line[:cut].rstrip())
            line = line[cut + 1:]
    if line or not pieces:  # una riga vuota (dentro un blocco di codice) resta
        pieces.append(line)
    return pieces


def _pack_lines(lines: List[str], limit: int) -> List[str]:
    """Righe unite con a capo in pezzi lunghi al massimo `limit`."""
    pieces: List[str] = []
    current = ""
    for line in lines:
        for part in _hard_split(line, limit):
            if current and len(current) + 1 + len(part) <= limit:
                current += "\n" + part
            else:
                if current:
                    pieces.append(current)
                current = part
    if current:
        pieces.append(current)
    return pieces


def _fit(block: Block, limit: int) -> List[str]:
    kind, opening, lines = block
    if kind == "text":
        whole = "\n".join(lines)
        return [whole] if len(whole) <= limit else _pack_lines(lines, limit)
    fence = _FENCE_OPEN.match(opening).group(2)  # il recinto di chiusura è quello di apertura senza il resto della riga
    whole = "\n".join([opening, *lines, fence])
    if len(whole) <= limit:
        return [whole]
    budget = limit - len(opening) - len(fence) - 2
    if budget < 1:
        # Nemmeno una riga di codice entra con i recinti: si manda come testo
        return _pack_lines([opening, *lines, fence], limit)
    return [f"{opening}\n{body}\n{fence}" for body in _pack_lines(lines, budget)] or [f"{opening}\n{fence}"]


def split_markdown(text: str, max_len: int) -> List[str]:
    """Pezzi di al massimo `max_len` caratteri, sui confini di paragrafo o di riga. Mai dentro un blocco di codice: se un
    blocco non entra, si divide per righe e ogni pezzo ha il suo recinto di apertura e di chiusura."""
    if max_len < 1:
        raise ValueError("max_len deve essere almeno 1")
    chunks: List[str] = []
    current = ""
    for block in _blocks(text):
        for piece in _fit(block, max_len):
            if current and len(current) + 2 + len(piece) <= max_len:
                current += "\n\n" + piece
            else:
                if current:
                    chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


# --- HTML di Telegram -------------------------------------------------------------------------------
# Telegram accetta solo alcuni tag (b, i, s, a, code, pre, blockquote...) e rifiuta il messaggio se un tag non è chiuso o
# se `<`, `>` e `&` non hanno l'escape. Qui ogni carattere del testo passa da `html.escape`; i tag li scrive solo questo
# codice e ogni riga si controlla: una riga con i tag non bilanciati si manda come testo semplice con l'escape.

_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_LIST_ITEM = re.compile(r"^(\s*)[-*+]\s+")
_LINK_OR_IMAGE = re.compile(r"!?\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
_SAFE_URL = re.compile(r"^(?:https?://|tg://|mailto:)", re.IGNORECASE)
_LANGUAGE = re.compile(r"^[\w+#.-]{1,30}$")
_TAG = re.compile(r"<[^>]*>")
_OUR_TAG = re.compile(r"<(/?)(b|i|s|a|code|pre|blockquote)\b[^>]*>")
_SLOT = re.compile("\x00(\\d+)\x00")
RULE_TEXT = "\u2500" * 10


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _balanced(fragment: str) -> bool:
    stack: List[str] = []
    for closing, name in _OUR_TAG.findall(fragment):
        if not closing:
            stack.append(name)
        elif not stack or stack.pop() != name:
            return False
    return not stack


def _emphasis(escaped: str) -> str:
    """Grassetto, barrato e corsivo su un testo che ha già l'escape (i segni `*`, `_`, `~` l'escape non li tocca)."""
    escaped = _BOLD.sub(r"<b>\2</b>", escaped)
    escaped = _STRIKE.sub(r"<s>\1</s>", escaped)
    escaped = _ITALIC_STAR.sub(r"<i>\1</i>", escaped)
    return _ITALIC_UNDERSCORE.sub(r"<i>\1</i>", escaped)


def _html_inline(text: str) -> str:
    """Codice in linea e link diventano segnaposto (così grassetto e corsivo non entrano negli URL né nel codice), poi
    escape ed enfasi sul resto, infine i segnaposto tornano al loro posto."""
    slots: List[str] = []

    def keep(fragment: str) -> str:
        slots.append(fragment)
        return f"\x00{len(slots) - 1}\x00"

    def link(m: "re.Match[str]") -> str:
        label, url = m.group(1), m.group(2)
        if not _SAFE_URL.match(url):  # javascript:, percorsi relativi...: niente link, solo il testo
            return keep(_emphasis(_esc(f"{label} ({url})" if label else url)))
        return keep(f'<a href="{html.escape(url, quote=True)}">{_emphasis(_esc(label)) if label else _esc(url)}</a>')

    text = text.replace("\x00", "")
    text = _INLINE_CODE.sub(lambda m: keep(f"<code>{_esc(m.group(2))}</code>"), text)
    text = _LINK_OR_IMAGE.sub(link, text)
    text = _emphasis(_esc(text))
    for _ in range(3):  # un segnaposto può stare dentro un altro (codice nell'etichetta di un link)
        if "\x00" not in text:
            break
        text = _SLOT.sub(lambda m: slots[int(m.group(1))], text)
    return text


def _html_line(line: str) -> str:
    if _RULE.match(line):
        return RULE_TEXT
    heading = _HEADING.match(line)
    if heading:
        rendered = f"<b>{_html_inline(heading.group(1))}</b>"
    else:
        item = _LIST_ITEM.match(line)
        rendered = f"{item.group(1)}\u2022 {_html_inline(line[item.end():])}" if item else _html_inline(line)
    if _balanced(rendered):
        return rendered
    plain = _plain_line(line)
    return _esc(plain or "")


def _html_table(lines: List[str]) -> str:
    """Una tabella Markdown in un blocco monospazio, con le colonne allineate."""
    rows: List[List[str]] = []
    header = False
    for line in lines:
        if _TABLE_SEPARATOR.match(line):
            header = header or len(rows) == 1
            continue
        rows.append([_plain_spans(cell.strip()) for cell in line.strip().strip("|").split("|")])
    if not rows:
        return ""
    columns = max(len(r) for r in rows)
    rows = [r + [""] * (columns - len(r)) for r in rows]
    widths = [max(len(r[i]) for r in rows) for i in range(columns)]
    out = [" | ".join(cell.ljust(widths[i]) for i, cell in enumerate(r)).rstrip() for r in rows]
    if header:
        out.insert(1, "-+-".join("-" * w for w in widths))
    return f"<pre>{_esc(chr(10).join(out))}</pre>"


def _html_code(opening: str, lines: List[str]) -> str:
    language = (_FENCE_OPEN.match(opening).group(3).strip().split() or [""])[0]
    body = _esc("\n".join(lines))
    if language and _LANGUAGE.match(language):
        return f'<pre><code class="language-{_esc(language)}">{body}</code></pre>'
    return f"<pre>{body}</pre>"


def to_telegram_html(text: str) -> str:
    """Markdown in HTML di Telegram. Blocchi di codice in `<pre>` (con la lingua, se c'è), tabelle in monospazio,
    citazioni in `<blockquote>`, titoli in grassetto, elenchi con il pallino; tutto il testo con l'escape."""
    out: List[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        opened = _FENCE_OPEN.match(line)
        if opened:
            marker, code = opened.group(2), []
            i += 1
            while i < len(lines) and not _closes(lines[i], marker):
                code.append(lines[i])
                i += 1
            out.append(_html_code(line, code))
            i += 1
            continue
        if _TABLE_ROW.match(line) and i + 1 < len(lines) and _TABLE_ROW.match(lines[i + 1]):
            start = i
            while i < len(lines) and _TABLE_ROW.match(lines[i]):
                i += 1
            out.append(_html_table(lines[start:i]))
            continue
        if _QUOTE.match(line):
            quoted = []
            while i < len(lines) and _QUOTE.match(lines[i]):
                quoted.append(_html_line(_QUOTE.sub("", lines[i])))
                i += 1
            out.append(f"<blockquote>{chr(10).join(quoted)}</blockquote>")
            continue
        out.append(_html_line(line))
        i += 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def html_to_text(fragment: str) -> str:
    """Il testo che Telegram mostra per un pezzo di HTML: senza tag e con le entità risolte."""
    return html.unescape(_TAG.sub("", fragment))


def _visible_length(fragment: str) -> int:
    """La lunghezza che Telegram conta (dopo i tag, in unità UTF-16: un'emoji ne vale due)."""
    return len(html_to_text(fragment).encode("utf-16-le")) // 2


def _html_pieces(markdown: str, limit: int, budget: int) -> List[str]:
    """Pezzi HTML il cui testo visibile sta in `limit`. L'HTML può essere più lungo del Markdown (colonne allineate,
    caratteri fuori dal piano base): un pezzo che sfora si ridivide con metà budget."""
    pieces: List[str] = []
    for part in split_markdown(markdown, budget):
        rendered = to_telegram_html(part)
        if _visible_length(rendered) <= limit or budget == 1:
            if html_to_text(rendered).strip():  # Telegram rifiuta un messaggio vuoto
                pieces.append(rendered)
        else:
            pieces.extend(_html_pieces(part, limit, max(1, budget // 2)))
    return pieces


def literal(text: str, capabilities: Capabilities) -> str:
    """Un testo fisso (un avviso del hub, la risposta a un comando) nel formato del canale: per l'HTML, con l'escape."""
    return _esc(text) if capabilities.text_format == "html" else text


def render_chunks(text: str, capabilities: Capabilities) -> List[str]:
    """La risposta in pezzi nel formato del canale. Vuota se non c'è testo."""
    limit = capabilities.max_message_length
    if capabilities.text_format == "html":
        return _html_pieces(text, limit, limit)
    if capabilities.text_format == "plain":
        text = strip_markdown(text)
    return split_markdown(text, limit)
