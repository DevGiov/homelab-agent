"""Memoria procedurale: come si fanno le cose in questo homelab.

Due tipi di procedura:
- `tool_note`: istruzione sull'uso di un tool (es. "su CT 125 i servizi si riavviano con docker compose, non systemctl"),
  aggiunta alla sua descrizione nel catalogo che act e plan vedono;
- `plan_template`: sequenza di passi che ha funzionato per un tipo di richiesta, nella memoria dei turni act e plan
  quando la richiesta le somiglia.

Una procedura cambia il comportamento dell'agente in ogni turno futuro, quindi entra in uso solo dopo l'approvazione
dell'utente: quelle proposte dall'agente (tool `propose_procedure`) o ricavate da un'esecuzione restano `proposed`
finché l'utente non le approva nella vista Memoria; quelle scritte dall'utente nascono approvate. Le rifiutate restano
come `rejected`, così la stessa proposta non torna. Le approvate sono anche record `kind='procedure'` della memoria
vettoriale (testo = titolo e contenuto), per la ricerca ibrida dei piani modello.
"""
import logging
import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from app.memory import hybrid_search, thread_store, vector_store

logger = logging.getLogger("procedures")

Kind = Literal["tool_note", "plan_template"]
Status = Literal["proposed", "approved", "rejected"]
KINDS = ("tool_note", "plan_template")
MAX_TITLE_CHARS = 160
MAX_CONTENT_CHARS = 2000
DUPLICATE_SCORE = 0.9  # somiglianza oltre la quale una proposta ripete una procedura esistente
RELEVANT_SCORE = 0.45  # somiglianza minima tra richiesta e piano modello
KEYWORD_RELEVANT_SCORE = 0.3

_COLUMNS = "id, kind, title, content, tool_name, status, source, thread_id, memory_id, created_at, updated_at"


def init_procedures_db() -> None:
    conn = thread_store._get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS procedures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL CHECK (kind IN ('tool_note', 'plan_template')),
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_name TEXT,
                status TEXT NOT NULL CHECK (status IN ('proposed', 'approved', 'rejected')),
                source TEXT NOT NULL,
                thread_id TEXT,
                memory_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _iso(value: Any) -> Optional[str]:
    return f"{str(value).replace(' ', 'T')}+00:00" if value else None


def _row(r: tuple) -> Dict[str, Any]:
    keys = [c.strip() for c in _COLUMNS.split(",")]
    item = dict(zip(keys, r, strict=True))
    item["created_at"], item["updated_at"] = _iso(item["created_at"]), _iso(item["updated_at"])
    del item["memory_id"]
    return item


def _clean(title: str, content: str, tool_name: Optional[str]) -> Tuple[str, str, Optional[str]]:
    title, content = " ".join(title.split())[:MAX_TITLE_CHARS], content.strip()[:MAX_CONTENT_CHARS]
    if not title or not content:
        raise ValueError("Titolo e contenuto sono obbligatori.")
    return title, content, (tool_name or "").strip() or None


def _memory_text(title: str, content: str) -> str:
    return f"{title}\n{content}"


def get_procedure(procedure_id: int) -> Optional[Dict[str, Any]]:
    conn = thread_store._get_conn()
    try:
        row = conn.execute(f"SELECT {_COLUMNS} FROM procedures WHERE id = ?", (procedure_id,)).fetchone()
    finally:
        conn.close()
    return _row(row) if row else None


def list_procedures(*, status: Optional[str] = None, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """Proposte prima, poi approvate e rifiutate; dentro ogni stato dalla più recente."""
    sql, params = f"SELECT {_COLUMNS} FROM procedures WHERE 1=1", []
    if status:
        sql += " AND status = ?"
        params.append(status)
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY CASE status WHEN 'proposed' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, id DESC"
    conn = thread_store._get_conn()
    try:
        return [_row(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def counts() -> Dict[str, int]:
    conn = thread_store._get_conn()
    try:
        rows = dict(conn.execute("SELECT status, COUNT(*) FROM procedures GROUP BY status").fetchall())
    finally:
        conn.close()
    return {status: rows.get(status, 0) for status in ("proposed", "approved", "rejected")}


def _duplicate_of(kind: str, title: str, content: str, tool_name: Optional[str]) -> Optional[int]:
    """Procedura esistente (in qualunque stato) dello stesso tipo e tool che dice la stessa cosa."""
    existing = [p for p in list_procedures(kind=kind) if p["tool_name"] == tool_name]
    if not existing:
        return None
    normalized = re.sub(r"\W+", " ", content.lower()).strip()
    for p in existing:
        if re.sub(r"\W+", " ", p["content"].lower()).strip() == normalized:
            return p["id"]
    embeddings = vector_store.embed_texts([_memory_text(title, content)] + [_memory_text(p["title"], p["content"]) for p in existing])
    new, others = embeddings[0], embeddings[1:]
    for p, other in zip(existing, others, strict=True):
        dot = sum(a * b for a, b in zip(new, other, strict=True))
        norm = (sum(a * a for a in new) * sum(b * b for b in other)) ** 0.5
        if norm and dot / norm >= DUPLICATE_SCORE:
            return p["id"]
    return None


def _insert(kind: str, title: str, content: str, tool_name: Optional[str], status: str, source: str, thread_id: Optional[str]) -> int:
    conn = thread_store._get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO procedures (kind, title, content, tool_name, status, source, thread_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, title, content, tool_name, status, source, thread_id),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def propose(kind: str, title: str, content: str, *, tool_name: Optional[str] = None, source: str = "agent",
            thread_id: Optional[str] = None) -> Tuple[int, bool]:
    """Nuova proposta in attesa di approvazione; (id, False) se ripete una procedura esistente."""
    if kind not in KINDS:
        raise ValueError(f"Tipo di procedura non valido: {kind}")
    title, content, tool_name = _clean(title, content, tool_name)
    if kind == "tool_note" and not tool_name:
        raise ValueError("Una nota su un tool deve indicare il tool.")
    duplicate = _duplicate_of(kind, title, content, tool_name)
    if duplicate:
        return duplicate, False
    procedure_id = _insert(kind, title, content, tool_name, "proposed", source, thread_id)
    logger.info(f"Procedura proposta #{procedure_id} ({kind}, fonte {source}): {title}")
    return procedure_id, True


def create(kind: str, title: str, content: str, *, tool_name: Optional[str] = None) -> Dict[str, Any]:
    """Procedura scritta dall'utente: approvata subito."""
    if kind not in KINDS:
        raise ValueError(f"Tipo di procedura non valido: {kind}")
    title, content, tool_name = _clean(title, content, tool_name)
    if kind == "tool_note" and not tool_name:
        raise ValueError("Una nota su un tool deve indicare il tool.")
    procedure_id = _insert(kind, title, content, tool_name, "proposed", "user", None)
    return approve(procedure_id)


def _set_memory(procedure_id: int, memory_id: Optional[int]) -> None:
    conn = thread_store._get_conn()
    try:
        conn.execute("UPDATE procedures SET memory_id = ? WHERE id = ?", (memory_id, procedure_id))
        conn.commit()
    finally:
        conn.close()


def _memory_id(procedure_id: int) -> Optional[int]:
    conn = thread_store._get_conn()
    try:
        row = conn.execute("SELECT memory_id FROM procedures WHERE id = ?", (procedure_id,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def _set_status(procedure_id: int, status: str) -> None:
    conn = thread_store._get_conn()
    try:
        conn.execute("UPDATE procedures SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, procedure_id))
        conn.commit()
    finally:
        conn.close()


def approve(procedure_id: int) -> Optional[Dict[str, Any]]:
    procedure = get_procedure(procedure_id)
    if procedure is None:
        return None
    if _memory_id(procedure_id) is None:
        memory_id = vector_store.add_memory(_memory_text(procedure["title"], procedure["content"]), kind="procedure",
                                            thread_id=procedure["thread_id"], metadata={"procedure_id": procedure_id})
        _set_memory(procedure_id, memory_id)
    _set_status(procedure_id, "approved")
    return get_procedure(procedure_id)


def _forget(procedure_id: int) -> None:
    memory_id = _memory_id(procedure_id)
    if memory_id is not None:
        vector_store.delete_memory(memory_id)
        _set_memory(procedure_id, None)


def reject(procedure_id: int) -> Optional[Dict[str, Any]]:
    if get_procedure(procedure_id) is None:
        return None
    _forget(procedure_id)
    _set_status(procedure_id, "rejected")
    return get_procedure(procedure_id)


def update(procedure_id: int, title: str, content: str, tool_name: Optional[str]) -> Optional[Dict[str, Any]]:
    procedure = get_procedure(procedure_id)
    if procedure is None:
        return None
    title, content, tool_name = _clean(title, content, tool_name)
    if procedure["kind"] == "tool_note" and not tool_name:
        raise ValueError("Una nota su un tool deve indicare il tool.")
    conn = thread_store._get_conn()
    try:
        conn.execute("UPDATE procedures SET title = ?, content = ?, tool_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                     (title, content, tool_name, procedure_id))
        conn.commit()
    finally:
        conn.close()
    memory_id = _memory_id(procedure_id)
    if memory_id is not None:
        vector_store.update_memory_content(memory_id, _memory_text(title, content))
    return get_procedure(procedure_id)


def delete(procedure_id: int) -> bool:
    if get_procedure(procedure_id) is None:
        return False
    _forget(procedure_id)
    conn = thread_store._get_conn()
    try:
        conn.execute("DELETE FROM procedures WHERE id = ?", (procedure_id,))
        conn.commit()
    finally:
        conn.close()
    return True


# --- Uso nei turni ---


def approved_tool_notes() -> Dict[str, List[str]]:
    """Note approvate per nome del tool, per il catalogo di act e plan."""
    notes: Dict[str, List[str]] = {}
    for p in list_procedures(status="approved", kind="tool_note"):
        notes.setdefault(p["tool_name"], []).append(p["content"])
    return notes


def relevant_templates(task: str, k: int) -> List[Dict[str, Any]]:
    """Piani modello approvati più pertinenti alla richiesta."""
    hits = hybrid_search.hybrid_search(task, kind="procedure", k=k * 2, min_score=RELEVANT_SCORE, keyword_min_score=KEYWORD_RELEVANT_SCORE)
    if not hits:
        return []
    by_memory = {}
    conn = thread_store._get_conn()
    try:
        ids = [i for i, _ in hits]
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM procedures WHERE status = 'approved' AND kind = 'plan_template' "
            f"AND memory_id IN ({','.join('?' * len(ids))})", ids
        ).fetchall()
        for r in rows:
            by_memory[r[8]] = _row(r)
    finally:
        conn.close()
    return [by_memory[i] for i, _ in hits if i in by_memory][:k]
