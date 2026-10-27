"""Knowledge base documenti: chunking + embedding + ricerca (Fase 2.3).

Supporta file .md, .txt e .pdf (con pypdf se disponibile).
I documenti vengono chunkati, indicizzati nel vector store (kind='kb')
e resi ricercabili semanticamente.
"""
import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core import config
from app.memory import vector_store

logger = logging.getLogger("knowledge_base")

KB_DIR = Path(config.CHECKPOINT_DB_PATH).parent / "knowledge_base"

CHUNK_SIZE = 800       # caratteri per chunk
CHUNK_OVERLAP = 150    # sovrapposizione tra chunk


def _ensure_dir():
    KB_DIR.mkdir(parents=True, exist_ok=True)


def _chunk_text(text: str) -> List[str]:
    """Chunking per paragrafi con overlap."""
    # Normalizza spazi ma preserva i paragrafi
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # Se aggiungere il paragrafo supera la dimensione, chiudi il chunk corrente
        while len(current) + len(para) + 2 > CHUNK_SIZE:
            if current:
                chunks.append(current.strip())
                # Overlap: prendi la coda del chunk corrente
                current = current[-CHUNK_OVERLAP:] if len(current) > CHUNK_OVERLAP else ""
            else:
                # Paragrafo singolo più grande del chunk: taglia duro
                chunks.append(para[:CHUNK_SIZE].strip())
                para = para[CHUNK_SIZE - CHUNK_OVERLAP:]
                if not para.strip():
                    break
                continue
        current += ("\n\n" + para if current else para)

    if current.strip():
        chunks.append(current.strip())
    # Mantieni anche i chunk corti se sono l'unico contenuto del documento
    if not chunks and text.strip():
        return [text.strip()]
    return [c for c in chunks if len(c) > 30] or ([text.strip()] if text.strip() else [])


def _extract_pdf(path: Path) -> str:
    """Estrae testo da PDF usando pypdf se disponibile."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        raise RuntimeError("pypdf non installato: impossibile leggere PDF") from None
    except Exception as e:
        raise RuntimeError(f"Errore lettura PDF: {e}") from e


def ingest_document(
    filename: str,
    content_bytes: Optional[bytes] = None,
    text_content: Optional[str] = None,
    *,
    source: str = "upload",
) -> Dict[str, Any]:
    """Ingesta un documento nella KB. Ritorna stats {doc_id, chunks}."""
    _ensure_dir()
    safe_name = Path(filename).name
    suffix = Path(safe_name).suffix.lower()

    # Estrai testo
    if suffix == ".pdf":
        if not content_bytes:
            raise ValueError("Contenuto PDF mancante")
        tmp = KB_DIR / safe_name
        tmp.write_bytes(content_bytes)
        text = _extract_pdf(tmp)
    elif suffix in (".md", ".txt"):
        text = text_content if text_content is not None else (content_bytes or b"").decode("utf-8", errors="replace")
    else:
        raise ValueError(f"Formato non supportato: '{suffix}'. Usa .md, .txt o .pdf")

    if not text.strip():
        raise ValueError("Documento vuoto")

    # Salva copia testuale
    doc_path = KB_DIR / f"{safe_name}.md" if suffix != ".md" else KB_DIR / safe_name
    doc_path.write_text(text, encoding="utf-8")

    # Chunking + indicizzazione
    chunks = _chunk_text(text)
    doc_id = hashlib.md5(safe_name.encode()).hexdigest()[:10]
    indexed = 0
    for i, chunk in enumerate(chunks):
        row = vector_store.add_memory(
            chunk,
            kind="kb",
            metadata={
                "doc_id": doc_id,
                "filename": safe_name,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "source": source,
            },
        )
        if row:
            indexed += 1

    logger.info(f"Ingesta '{safe_name}': {indexed}/{len(chunks)} chunk indicizzati (doc_id={doc_id})")
    return {"doc_id": doc_id, "filename": safe_name, "chunks_total": len(chunks), "chunks_indexed": indexed}


def search_knowledge(query: str, k: int = 5) -> List[Dict[str, Any]]:
    """Ricerca semantica nella KB."""
    hits = vector_store.search_memory(query, k=k, kind="kb")
    # Aggrega per documento mantenendo l'ordine di rilevanza
    results = []
    seen_docs: Dict[str, int] = {}
    for h in hits:
        meta = h.get("metadata", {})
        fname = meta.get("filename", "?")
        if fname in seen_docs:
            results[seen_docs[fname]]["chunks"].append({
                "content": h["content"],
                "score": h["score"],
                "chunk_index": meta.get("chunk_index"),
            })
        else:
            seen_docs[fname] = len(results)
            results.append({
                "filename": fname,
                "doc_id": meta.get("doc_id"),
                "chunks": [{
                    "content": h["content"],
                    "score": h["score"],
                    "chunk_index": meta.get("chunk_index"),
                }],
            })
    return results


def list_documents() -> List[Dict[str, Any]]:
    """Elenca i documenti presenti nella KB."""
    import json as _json
    import sqlite3
    try:
        conn = sqlite3.connect(config.CHECKPOINT_DB_PATH)
        rows = conn.execute(
            "SELECT metadata_json, COUNT(*) FROM vec_memory WHERE kind='kb' GROUP BY metadata_json"
        ).fetchall()
        conn.close()
        docs: Dict[str, Dict[str, Any]] = {}
        for meta_json, count in rows:
            try:
                meta = _json.loads(meta_json)
            except Exception:
                continue
            fname = meta.get("filename")
            if fname and fname not in docs:
                docs[fname] = {
                    "filename": fname,
                    "doc_id": meta.get("doc_id"),
                    "source": meta.get("source"),
                    "chunks": count,
                }
            elif fname:
                docs[fname]["chunks"] += count
        return list(docs.values())
    except Exception as e:
        logger.warning(f"list_documents fallito: {e}")
        return []


def delete_document(filename: str) -> int:
    """Elimina tutti i chunk di un documento dalla KB."""
    import json as _json
    import sqlite3
    try:
        conn = sqlite3.connect(config.CHECKPOINT_DB_PATH)
        # Necessario per DELETE sulla virtual table vec_memory_idx
        conn.enable_load_extension(True)
        import sqlite_vec
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        rows = conn.execute("SELECT id, metadata_json FROM vec_memory WHERE kind='kb'").fetchall()
        deleted = 0
        for rid, meta_json in rows:
            try:
                meta = _json.loads(meta_json or "{}")
            except Exception:
                continue
            if meta.get("filename") == filename:
                conn.execute("DELETE FROM vec_memory_idx WHERE rowid = ?", (rid,))
                conn.execute("DELETE FROM vec_memory WHERE id = ?", (rid,))
                deleted += 1
        conn.commit()
        conn.close()
        # Rimuovi anche il file salvato
        for ext in ("", ".md", ".txt"):
            p = KB_DIR / f"{filename}{ext}"
            if p.exists():
                p.unlink()
        logger.info(f"Eliminati {deleted} chunk di '{filename}'")
        return deleted
    except Exception as e:
        logger.warning(f"delete_document fallito: {e}")
        return 0
