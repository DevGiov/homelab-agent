"""Ricerca per parole (FTS5) sulla memoria e sui messaggi, e ricerca ibrida parole + significato sulla memoria.

Gli indici FTS5 sono tabelle autonome mantenute da trigger sulle tabelle di origine, così ogni scrittura (anche
`INSERT OR REPLACE` dei messaggi, che non fa scattare i trigger di cancellazione) resta allineata:
- `memory_fts`: testo dei record di `vec_memory` (fatti, episodi, documenti), con rowid = id del record;
- `message_fts`: testo della versione attiva dei messaggi di `thread_messages`, esclusi gli errori.

La ricerca ibrida fonde le due classifiche con la Reciprocal Rank Fusion: un record trovato da entrambe sale in cima,
e una parola esatta (un nome, un ID di container) recupera ciò che l'embedding multilingue piccolo non avvicina.
"""
import json
import re
import sqlite3
from typing import Dict, List, Optional, Tuple

from app.memory import vector_store

RRF_K = 60  # costante della Reciprocal Rank Fusion
PREFIX_LEN = 6  # le parole più lunghe si cercano per prefisso (installato, installazione → instal*)

STOPWORDS = frozenset("""
a ad al alla alle allo agli ai anche ancora avere abbiamo avete avevo aveva ho hai ha hanno che chi ci cio come con
cosa cui da dal dalla dalle dai degli dei del della delle dello di dove e ed era essere fa fra gli i il in io la le lei
li lo loro lui ma me mi mia mie miei mio ne nei nel nella nelle nello noi non nostro o per perche piu poi qual quale
quali quando quanto quella quelle quelli quello questa queste questi questo se sei si sia siamo sono su sua sue sui
sul sulla suo suoi te ti tra tu tua tue tuo tuoi un una uno vi voi gia solo sempre mai adesso ora uso usato solito
detto dire fatto avevamo abbiamo stato stata
the an and are as at be by did do does for from had has have how i in is it its my of on or our that this to was
we were what when where which who why with you your
""".split())

MEMORY_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content, kind UNINDEXED, tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS memory_fts_insert AFTER INSERT ON vec_memory BEGIN
    INSERT INTO memory_fts (rowid, content, kind) VALUES (NEW.id, NEW.content, NEW.kind);
END;
CREATE TRIGGER IF NOT EXISTS memory_fts_update AFTER UPDATE OF content, kind ON vec_memory BEGIN
    DELETE FROM memory_fts WHERE rowid = OLD.id;
    INSERT INTO memory_fts (rowid, content, kind) VALUES (NEW.id, NEW.content, NEW.kind);
END;
CREATE TRIGGER IF NOT EXISTS memory_fts_delete AFTER DELETE ON vec_memory BEGIN
    DELETE FROM memory_fts WHERE rowid = OLD.id;
END;
"""

_ACTIVE = "COALESCE(json_extract(NEW.versions_json, '$[' || NEW.version_index || '].content'), NEW.content)"
MESSAGE_SCHEMA = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
    content, thread_id UNINDEXED, message_id UNINDEXED, sender UNINDEXED, created_at UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS message_fts_insert AFTER INSERT ON thread_messages BEGIN
    DELETE FROM message_fts WHERE thread_id = NEW.thread_id AND message_id = NEW.message_id;
    INSERT INTO message_fts (content, thread_id, message_id, sender, created_at)
    SELECT {_ACTIVE}, NEW.thread_id, NEW.message_id, NEW.sender, NEW.created_at WHERE NEW.is_error = 0;
END;
CREATE TRIGGER IF NOT EXISTS message_fts_update AFTER UPDATE OF content, versions_json, version_index, created_at ON thread_messages BEGIN
    DELETE FROM message_fts WHERE thread_id = OLD.thread_id AND message_id = OLD.message_id;
    INSERT INTO message_fts (content, thread_id, message_id, sender, created_at)
    SELECT {_ACTIVE}, NEW.thread_id, NEW.message_id, NEW.sender, NEW.created_at WHERE NEW.is_error = 0;
END;
CREATE TRIGGER IF NOT EXISTS message_fts_delete AFTER DELETE ON thread_messages BEGIN
    DELETE FROM message_fts WHERE thread_id = OLD.thread_id AND message_id = OLD.message_id;
END;
"""


def _exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone() is not None


def init_search_indexes() -> None:
    """Indici FTS di memoria e messaggi (dopo gli schemi di `vec_memory` e `thread_messages`)."""
    conn = vector_store._get_conn()
    try:
        init_memory_fts(conn)
        init_message_fts(conn)
        conn.commit()
    finally:
        conn.close()


def init_memory_fts(conn: sqlite3.Connection) -> None:
    """Indice della memoria; alla creazione indicizza i record esistenti."""
    fresh = not _exists(conn, "memory_fts")
    conn.executescript(MEMORY_SCHEMA)
    if fresh:
        conn.execute("INSERT INTO memory_fts (rowid, content, kind) SELECT id, content, kind FROM vec_memory")


def init_message_fts(conn: sqlite3.Connection) -> None:
    """Indice dei messaggi; alla creazione indicizza i messaggi esistenti."""
    fresh = not _exists(conn, "message_fts")
    conn.executescript(MESSAGE_SCHEMA)
    if fresh:
        conn.execute(f"""
            INSERT INTO message_fts (content, thread_id, message_id, sender, created_at)
            SELECT {_ACTIVE.replace('NEW.', '')}, thread_id, message_id, sender, created_at
            FROM thread_messages WHERE is_error = 0
        """)


def fts_query(text: str) -> str:
    """Query FTS5 in OR dalle parole significative: indirizzi come frase, parole lunghe per prefisso."""
    terms: List[str] = []
    for token in re.findall(r"\w+(?:\.\w+)+|\w+", text.lower()):
        if "." in token:
            term = '"' + " ".join(token.split(".")) + '"'
        elif token.isdigit():
            term = f'"{token}"'
        elif len(token) < 3 or token in STOPWORDS:
            continue
        elif len(token) > PREFIX_LEN:
            term = f"{token[:PREFIX_LEN]}*"
        else:
            term = f'"{token}"'
        if term not in terms:
            terms.append(term)
    return " OR ".join(terms)


def keyword_search_memory(query: str, *, kind: str, k: int, thread_id: Optional[str] = None) -> List[int]:
    """Id dei record validi di `kind` che contengono le parole della query, dal più pertinente (BM25)."""
    match = fts_query(query)
    if not match:
        return []
    sql = ("SELECT f.rowid FROM memory_fts f JOIN vec_memory m ON m.id = f.rowid "
           "WHERE memory_fts MATCH ? AND f.kind = ? AND m.invalid_at IS NULL")
    params: list = [match, kind]
    if thread_id:
        sql += " AND m.thread_id = ?"
        params.append(thread_id)
    sql += " ORDER BY bm25(memory_fts) LIMIT ?"
    params.append(k)
    conn = vector_store._get_conn()
    try:
        return [r[0] for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _cosine_scores(ids: List[int], query: str) -> Dict[int, float]:
    if not ids:
        return {}
    embedding = json.dumps(vector_store.embed_query(query))
    conn = vector_store._get_conn()
    try:
        rows = conn.execute(
            f"SELECT rowid, vec_distance_cosine(embedding, ?) FROM vec_memory_idx WHERE rowid IN ({','.join('?' * len(ids))})",
            [embedding, *ids],
        ).fetchall()
    finally:
        conn.close()
    return {rowid: 1.0 - distance for rowid, distance in rows}


def hybrid_search(
    query: str,
    *,
    kind: str,
    k: int,
    thread_id: Optional[str] = None,
    min_score: float,
    keyword_min_score: float,
) -> List[Tuple[int, float]]:
    """(id, somiglianza coseno) fusi per rango: dalla ricerca vettoriale i record con almeno `min_score`, da quella
    per parole quelli con almeno `keyword_min_score` (soglia più bassa: la parola in comune è già un indizio)."""
    vector_hits = vector_store.search_memory(query, k=k, kind=kind, thread_id=thread_id)
    scores = {h["id"]: h["score"] for h in vector_hits}
    vector_ranked = [h["id"] for h in vector_hits if h["score"] >= min_score]
    keyword_ids = keyword_search_memory(query, kind=kind, k=k, thread_id=thread_id)
    scores.update(_cosine_scores([i for i in keyword_ids if i not in scores], query))
    keyword_ranked = [i for i in keyword_ids if scores.get(i, 0.0) >= keyword_min_score]

    fused: Dict[int, float] = {}
    for ranking in (vector_ranked, keyword_ranked):
        for rank, item in enumerate(ranking):
            fused[item] = fused.get(item, 0.0) + 1.0 / (RRF_K + rank + 1)
    ordered = sorted(fused, key=lambda i: (-fused[i], -scores[i]))
    return [(i, scores[i]) for i in ordered[:k]]


def search_messages(query: str, *, k: int = 8, thread_id: Optional[str] = None) -> List[Dict[str, str]]:
    """Messaggi che contengono le parole della query, dal più pertinente, con un estratto e il titolo del thread."""
    match = fts_query(query)
    if not match:
        return []
    sql = """
        SELECT f.thread_id, t.title, f.message_id, f.sender, f.created_at, snippet(message_fts, 0, '«', '»', '…', 32)
        FROM message_fts f LEFT JOIN thread_metadata t ON t.thread_id = f.thread_id
        WHERE message_fts MATCH ?
    """
    params: list = [match]
    if thread_id:
        sql += " AND f.thread_id = ?"
        params.append(thread_id)
    sql += " ORDER BY bm25(message_fts) LIMIT ?"
    params.append(k)
    conn = vector_store._get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [
        {"thread_id": t, "thread_title": title or t, "message_id": m, "role": "user" if sender == "user" else "assistant",
         "date": str(created or "")[:16], "excerpt": excerpt}
        for t, title, m, sender, created, excerpt in rows
    ]
