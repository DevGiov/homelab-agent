"""Dalla risposta Markdown ai pezzi di un messaggio di canale.

- `split_markdown`: divide alla lunghezza massima sui confini di paragrafo, poi di riga, mai dentro un blocco di codice:
  un blocco troppo lungo si divide per righe, chiudendo il blocco in fondo a ogni pezzo e riaprendolo nel successivo;
- `strip_markdown`: la versione per i canali di solo testo, senza i segni del Markdown;
- `render_chunks`: l'insieme, secondo le capacità del canale. L'HTML (Telegram) non c'è ancora: arriva con il canale.
"""
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
    # Il codice in linea resta com'è: dentro i backtick `*` e `_` non sono segni
    parts = _INLINE_CODE.split(line)
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


def render_chunks(text: str, capabilities: Capabilities) -> List[str]:
    """La risposta in pezzi nel formato del canale. Vuota se non c'è testo."""
    if capabilities.text_format == "html":
        raise NotImplementedError("Il rendering HTML arriva con il canale che lo usa (Telegram, fase C1)")
    if capabilities.text_format == "plain":
        text = strip_markdown(text)
    return split_markdown(text, capabilities.max_message_length)
