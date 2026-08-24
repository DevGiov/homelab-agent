"""Vector store locale con sqlite-vec + embeddings fastembed (Fase 2.1).

Memoria semantica persistente per fatti salienti, summary e documenti KB.
Tutto locale: nessuna dipendenza da servizi esterni per il retrieval.
"""
import json
import logging
import sqlite3
import threading
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger("vector_store")

EMBED_DIM = 384  # paraphrase-multilingual-MiniLM-L12-v2

_embedder = None
_embedder_lock = threading.Lock()


def _get_embedder():
    """Lazy-load del modello di embedding (fastembed ONNX, locale)."""
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                try:
                    from fastembed import TextEmbedding
                    _embedder = TextEmbedding(
                        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
                    )
                    logger.info("Modello embedding caricato: paraphrase-multilingual-MiniLM-L12-v2")
                except Exception as e:
                    logger.error(f"Impossibile caricare fastembed: {e}")
                    raise
    return _embedder


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Genera embeddings per una lista di testi."""
    model = _get_embedder()
    return [e.tolist() for e in model.embed(texts)]


def embed_query(text: str) -> List[float]:
    """Genera l'embedding per una query."""
    return embed_texts([text])[0]


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.CHECKPOINT_DB_PATH, check_same_thread=False)
    conn.enable_load_extension(True)
    import sqlite_vec
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def init_vector_db():
    """Crea le tabelle vettoriali se non esistono."""
    try:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vec_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL DEFAULT 'fact',
                thread_id TEXT,
                content TEXT NOT NULL,
                metadata_json TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_memory_idx USING vec0(
                    embedding float[{EMBED_DIM}] distance_metric=cosine
                )
            """)
        except Exception as e:
            logger.warning(f"Creazione tabella vec0: {e}")
        conn.commit()
        conn.close()
        logger.info("Vector store inizializzato")
    except Exception as e:
        logger.error(f"Errore init vector store: {e}")


init_vector_db()


def add_memory(
    content: str,
    *,
    kind: str = "fact",
    thread_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Aggiunge un documento alla memoria vettoriale. Ritorna l'id o None."""
    if not content or not content.strip():
        return None
    try:
        embedding = embed_query(content.strip())
        conn = _get_conn()
        cur = conn.execute(
            "INSERT INTO vec_memory (kind, thread_id, content, metadata_json) VALUES (?, ?, ?, ?)",
            (kind, thread_id, content.strip(), json.dumps(metadata or {}, ensure_ascii=False)),
        )
        row_id = cur.lastrowid
        conn.execute(
            "INSERT INTO vec_memory_idx (rowid, embedding) VALUES (?, ?)",
            (row_id, json.dumps(embedding)),
        )
        conn.commit()
        conn.close()
        return row_id
    except Exception as e:
        logger.warning(f"add_memory fallito: {e}")
        return None


def search_memory(
    query: str,
    *,
    k: int = 5,
    kind: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Ricerca semantica per similarità coseno (sqlite-vec distance = 1 - cosine)."""
    try:
        q_emb = embed_query(query)
        conn = _get_conn()
        sql = """
            SELECT m.id, m.kind, m.thread_id, m.content, m.metadata_json, v.distance
            FROM vec_memory_idx v
            JOIN vec_memory m ON m.id = v.rowid
            WHERE v.embedding MATCH ?
              AND k = ?
        """
        params: List[Any] = [json.dumps(q_emb), k]
        if kind or thread_id:
            # Filtro post-distance (sqlite-vec non supporta filtri diretti con MATCH)
            sql = """
                SELECT * FROM (
                    SELECT m.id, m.kind, m.thread_id, m.content, m.metadata_json, v.distance
                    FROM vec_memory_idx v
                    JOIN vec_memory m ON m.id = v.rowid
                    WHERE v.embedding MATCH ? AND k = ?
                ) WHERE 1=1
            """
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if thread_id:
            sql += " AND thread_id = ?"
            params.append(thread_id)
        sql += " ORDER BY distance ASC"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        results = []
        for r in rows:
            results.append({
                "id": r[0],
                "kind": r[1],
                "thread_id": r[2],
                "content": r[3],
                "metadata": json.loads(r[4]) if r[4] else {},
                "distance": r[5],
                "score": 1.0 - r[5],
            })
        return results
    except Exception as e:
        logger.warning(f"search_memory fallito: {e}")
        return []


def delete_thread_memory(thread_id: str) -> int:
    """Elimina tutta la memoria vettoriale di un thread."""
    try:
        conn = _get_conn()
        rows = conn.execute("SELECT id FROM vec_memory WHERE thread_id = ?", (thread_id,)).fetchall()
        ids = [r[0] for r in rows]
        for rid in ids:
            conn.execute("DELETE FROM vec_memory_idx WHERE rowid = ?", (rid,))
        cur = conn.execute("DELETE FROM vec_memory WHERE thread_id = ?", (thread_id,))
        conn.commit()
        conn.close()
        return cur.rowcount
    except Exception as e:
        logger.warning(f"delete_thread_memory fallito: {e}")
        return 0


def count_memory(kind: Optional[str] = None) -> int:
    try:
        conn = _get_conn()
        if kind:
            n = conn.execute("SELECT COUNT(*) FROM vec_memory WHERE kind = ?", (kind,)).fetchone()[0]
        else:
            n = conn.execute("SELECT COUNT(*) FROM vec_memory").fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


def delete_memory(memory_id: int) -> bool:
    """Elimina un singolo record di memoria vettoriale per id."""
    try:
        conn = _get_conn()
        conn.execute("DELETE FROM vec_memory_idx WHERE rowid = ?", (memory_id,))
        cur = conn.execute("DELETE FROM vec_memory WHERE id = ?", (memory_id,))
        conn.commit()
        conn.close()
        return cur.rowcount > 0
    except Exception as e:
        logger.warning(f"delete_memory {memory_id} fallito: {e}")
        return False


def clear_all_memories(kind: Optional[str] = None) -> int:
    """Svuota tutti i record di memoria vettoriale (o per kind)."""
    try:
        conn = _get_conn()
        if kind:
            rows = conn.execute("SELECT id FROM vec_memory WHERE kind = ?", (kind,)).fetchall()
            for r in rows:
                conn.execute("DELETE FROM vec_memory_idx WHERE rowid = ?", (r[0],))
            cur = conn.execute("DELETE FROM vec_memory WHERE kind = ?", (kind,))
        else:
            conn.execute("DELETE FROM vec_memory_idx")
            cur = conn.execute("DELETE FROM vec_memory")
        conn.commit()
        conn.close()
        return cur.rowcount
    except Exception as e:
        logger.warning(f"clear_all_memories fallito: {e}")
        return 0


def list_memories(
    kind: Optional[str] = "fact",
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Restituisce la lista di memorie ordinate per data decrescente."""
    try:
        conn = _get_conn()
        sql = "SELECT id, kind, thread_id, content, metadata_json, created_at FROM vec_memory"
        params: List[Any] = []
        if kind:
            sql += " WHERE kind = ?"
            params.append(kind)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(sql, params).fetchall()
        conn.close()

        items = []
        for r in rows:
            meta = {}
            if r[4]:
                try:
                    meta = json.loads(r[4])
                except Exception:
                    pass
            items.append({
                "id": r[0],
                "kind": r[1],
                "thread_id": r[2],
                "content": r[3],
                "metadata": meta,
                "created_at": str(r[5]) if r[5] else None,
            })
        return items
    except Exception as e:
        logger.warning(f"list_memories fallito: {e}")
        return []
