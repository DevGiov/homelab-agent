"""Fatti della memoria a lungo termine e entità che citano.

I fatti sono i record `kind='fact'` della memoria vettoriale (testo, embedding, thread di origine). Ogni fatto
è collegato alle entità che nomina (persone, servizi, host, …); due entità sono in relazione quando compaiono
negli stessi fatti. Un'entità esiste solo finché almeno un fatto la cita: le orfane si eliminano a ogni modifica.
"""
import json
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.memory import vector_store

logger = logging.getLogger("facts")

ENTITY_TYPES = ("person", "organization", "place", "project", "software", "infrastructure", "other")
# Somiglianza coseno oltre la quale un nuovo fatto è considerato già presente
DUPLICATE_SCORE = 0.95

SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    key TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL DEFAULT 'other',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS memory_fact_entities (
    fact_id INTEGER NOT NULL,
    entity_id INTEGER NOT NULL,
    PRIMARY KEY (fact_id, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_fact_entities_entity ON memory_fact_entities(entity_id);
"""


class EntityConflictError(ValueError):
    """Rinomina verso il nome di un'altra entità: va unita, non rinominata."""

    def __init__(self, existing_id: int, name: str):
        super().__init__(f"Esiste già l'entità '{name}' (#{existing_id}): uniscile invece di rinominare.")
        self.existing_id = existing_id


def entity_key(name: str) -> str:
    """Chiave di confronto: minuscole, spazi compattati, senza punteggiatura ai bordi."""
    return re.sub(r"\s+", " ", name).strip(" \t.,;:!?\"'()[]").lower()


def init_facts_db() -> None:
    conn = vector_store._get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


# --- Lettura ---


def _entities_of(conn, fact_ids: Iterable[int]) -> Dict[int, List[Dict[str, Any]]]:
    ids = list(fact_ids)
    by_fact: Dict[int, List[Dict[str, Any]]] = {i: [] for i in ids}
    if not ids:
        return by_fact
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT fe.fact_id, e.id, e.name, e.type FROM memory_fact_entities fe JOIN memory_entities e ON e.id = fe.entity_id "
        f"WHERE fe.fact_id IN ({placeholders}) ORDER BY e.name COLLATE NOCASE",
        ids,
    ).fetchall()
    for fact_id, entity_id, name, etype in rows:
        by_fact[fact_id].append({"id": entity_id, "name": name, "type": etype})
    return by_fact


def _fact_rows(conn, rows: List[tuple], scores: Optional[Dict[int, float]] = None) -> List[Dict[str, Any]]:
    entities = _entities_of(conn, (r[0] for r in rows))
    facts = []
    for fact_id, thread_id, content, metadata_json, created_at in rows:
        metadata = json.loads(metadata_json) if metadata_json else {}
        fact = {
            "id": fact_id,
            "content": content,
            "thread_id": thread_id,
            "source": metadata.get("source", "manual"),
            # CURRENT_TIMESTAMP di SQLite è UTC senza fuso: ISO 8601 esplicito per i client
            "created_at": f"{str(created_at).replace(' ', 'T')}+00:00" if created_at else None,
            "entities": entities[fact_id],
        }
        if scores is not None:
            fact["score"] = round(scores[fact_id], 3)
        facts.append(fact)
    return facts


_FACT_COLUMNS = "m.id, m.thread_id, m.content, m.metadata_json, m.created_at"


def _filters(thread_id: Optional[str], entity_id: Optional[int]) -> Tuple[str, List[Any]]:
    sql, params = " WHERE m.kind = 'fact'", []
    if thread_id:
        sql += " AND m.thread_id = ?"
        params.append(thread_id)
    if entity_id is not None:
        sql += " AND m.id IN (SELECT fact_id FROM memory_fact_entities WHERE entity_id = ?)"
        params.append(entity_id)
    return sql, params


def list_facts(
    *, thread_id: Optional[str] = None, entity_id: Optional[int] = None, limit: int = 50, offset: int = 0
) -> Tuple[List[Dict[str, Any]], int]:
    """Fatti dal più recente, con il totale per la paginazione."""
    where, params = _filters(thread_id, entity_id)
    conn = vector_store._get_conn()
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM vec_memory m{where}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT {_FACT_COLUMNS} FROM vec_memory m{where} ORDER BY m.id DESC LIMIT ? OFFSET ?", [*params, limit, offset]
        ).fetchall()
        return _fact_rows(conn, rows), total
    finally:
        conn.close()


def search_facts(query: str, *, k: int = 20, thread_id: Optional[str] = None, entity_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Fatti più simili alla query (punteggio coseno), con gli stessi filtri dell'elenco."""
    hits = vector_store.search_memory(query, k=k, kind="fact", thread_id=thread_id)
    if not hits:
        return []
    scores = {h["id"]: h["score"] for h in hits}
    where, params = _filters(None, entity_id)
    placeholders = ",".join("?" * len(scores))
    conn = vector_store._get_conn()
    try:
        rows = conn.execute(
            f"SELECT {_FACT_COLUMNS} FROM vec_memory m{where} AND m.id IN ({placeholders})", [*params, *scores]
        ).fetchall()
        facts = _fact_rows(conn, rows, scores)
    finally:
        conn.close()
    return sorted(facts, key=lambda f: -f["score"])


def get_fact(fact_id: int) -> Optional[Dict[str, Any]]:
    conn = vector_store._get_conn()
    try:
        rows = conn.execute(f"SELECT {_FACT_COLUMNS} FROM vec_memory m WHERE m.kind = 'fact' AND m.id = ?", (fact_id,)).fetchall()
        return _fact_rows(conn, rows)[0] if rows else None
    finally:
        conn.close()


# Fatti mai analizzati per le entità: senza collegamenti e senza il segno `entities_checked` nei metadati
_UNTAGGED = (
    "m.kind = 'fact' AND m.id NOT IN (SELECT fact_id FROM memory_fact_entities) "
    "AND COALESCE(json_extract(m.metadata_json, '$.entities_checked'), 0) = 0"
)


def facts_without_entities(limit: int) -> List[Dict[str, Any]]:
    conn = vector_store._get_conn()
    try:
        rows = conn.execute(f"SELECT {_FACT_COLUMNS} FROM vec_memory m WHERE {_UNTAGGED} ORDER BY m.id LIMIT ?", (limit,)).fetchall()
        return _fact_rows(conn, rows)
    finally:
        conn.close()


def list_entities(*, query: Optional[str] = None, entity_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Entità con il numero di fatti che le citano, le più citate per prime."""
    sql = (
        "SELECT e.id, e.name, e.type, COUNT(fe.fact_id) AS fact_count FROM memory_entities e "
        "JOIN memory_fact_entities fe ON fe.entity_id = e.id WHERE 1=1"
    )
    params: List[Any] = []
    if query:
        sql += " AND e.key LIKE ?"
        params.append(f"%{entity_key(query)}%")
    if entity_type:
        sql += " AND e.type = ?"
        params.append(entity_type)
    sql += " GROUP BY e.id ORDER BY fact_count DESC, e.name COLLATE NOCASE"
    conn = vector_store._get_conn()
    try:
        return [{"id": r[0], "name": r[1], "type": r[2], "fact_count": r[3]} for r in conn.execute(sql, params)]
    finally:
        conn.close()


def get_entity(entity_id: int) -> Optional[Dict[str, Any]]:
    """Entità con le entità in relazione: quelle citate negli stessi fatti, per numero di fatti in comune."""
    conn = vector_store._get_conn()
    try:
        row = conn.execute(
            "SELECT e.id, e.name, e.type, (SELECT COUNT(*) FROM memory_fact_entities WHERE entity_id = e.id) "
            "FROM memory_entities e WHERE e.id = ?",
            (entity_id,),
        ).fetchone()
        if not row:
            return None
        related = conn.execute(
            "SELECT e.id, e.name, e.type, COUNT(*) AS shared FROM memory_fact_entities a "
            "JOIN memory_fact_entities b ON b.fact_id = a.fact_id AND b.entity_id != a.entity_id "
            "JOIN memory_entities e ON e.id = b.entity_id WHERE a.entity_id = ? "
            "GROUP BY e.id ORDER BY shared DESC, e.name COLLATE NOCASE",
            (entity_id,),
        ).fetchall()
        return {
            "id": row[0],
            "name": row[1],
            "type": row[2],
            "fact_count": row[3],
            "related": [{"id": r[0], "name": r[1], "type": r[2], "shared": r[3]} for r in related],
        }
    finally:
        conn.close()


def stats() -> Dict[str, int]:
    conn = vector_store._get_conn()
    try:
        facts, threads = conn.execute("SELECT COUNT(*), COUNT(DISTINCT thread_id) FROM vec_memory WHERE kind = 'fact'").fetchone()
        entities = conn.execute("SELECT COUNT(DISTINCT entity_id) FROM memory_fact_entities").fetchone()[0]
        untagged = conn.execute(f"SELECT COUNT(*) FROM vec_memory m WHERE {_UNTAGGED}").fetchone()[0]
        return {"facts": facts, "threads": threads, "entities": entities, "facts_without_entities": untagged}
    finally:
        conn.close()


# --- Scrittura ---


def _upsert_entity(conn, name: str, entity_type: str) -> Optional[int]:
    key = entity_key(name)
    if not key:
        return None
    entity_type = entity_type if entity_type in ENTITY_TYPES else "other"
    row = conn.execute("SELECT id, type FROM memory_entities WHERE key = ?", (key,)).fetchone()
    if row:
        # Un tipo specifico prevale su 'other' assegnato in precedenza
        if row[1] == "other" and entity_type != "other":
            conn.execute("UPDATE memory_entities SET type = ? WHERE id = ?", (entity_type, row[0]))
        return row[0]
    return conn.execute(
        "INSERT INTO memory_entities (name, key, type) VALUES (?, ?, ?)", (re.sub(r"\s+", " ", name).strip(), key, entity_type)
    ).lastrowid


def _link(conn, fact_id: int, entities: Iterable[Dict[str, str]]) -> None:
    for entity in entities:
        entity_id = _upsert_entity(conn, entity["name"], entity.get("type", "other"))
        if entity_id is not None:
            conn.execute("INSERT OR IGNORE INTO memory_fact_entities (fact_id, entity_id) VALUES (?, ?)", (fact_id, entity_id))


def _drop_orphans(conn) -> None:
    conn.execute("DELETE FROM memory_entities WHERE id NOT IN (SELECT entity_id FROM memory_fact_entities)")


def find_duplicate(content: str) -> Optional[int]:
    hits = vector_store.search_memory(content, k=1, kind="fact")
    return hits[0]["id"] if hits and hits[0]["score"] >= DUPLICATE_SCORE else None


def add_fact(
    content: str,
    *,
    thread_id: Optional[str] = None,
    entities: Iterable[Dict[str, str]] = (),
    source: str = "manual",
    entities_checked: bool = False,
) -> Tuple[Optional[int], bool]:
    """Salva un fatto con le sue entità. Restituisce (id, creato): un quasi-duplicato non viene riscritto ma
    riceve le entità nuove, e l'id è quello del fatto esistente. `entities_checked` segna che le entità sono già
    state cercate (dall'estrazione), così il fatto non torna tra quelli da analizzare anche se non ne ha."""
    content = content.strip()
    if not content:
        return None, False
    duplicate = find_duplicate(content)
    fact_id = duplicate or vector_store.add_memory(content, kind="fact", thread_id=thread_id, metadata={"source": source})
    if fact_id is None:
        return None, False
    if entities_checked:
        tag_fact(fact_id, entities)
    else:
        conn = vector_store._get_conn()
        try:
            _link(conn, fact_id, entities)
            conn.commit()
        finally:
            conn.close()
    return fact_id, duplicate is None


def update_fact(fact_id: int, content: str, entities: Iterable[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    """Nuovo testo (ricalcolando l'embedding solo se cambia) e nuove entità del fatto."""
    current = get_fact(fact_id)
    if current is None:
        return None
    if content.strip() != current["content"]:
        vector_store.update_memory_content(fact_id, content)
    conn = vector_store._get_conn()
    try:
        conn.execute("DELETE FROM memory_fact_entities WHERE fact_id = ?", (fact_id,))
        conn.commit()
    finally:
        conn.close()
    # Le entità scelte a mano valgono come analisi: il fatto non torna tra quelli da etichettare
    tag_fact(fact_id, entities)
    conn = vector_store._get_conn()
    try:
        _drop_orphans(conn)
        conn.commit()
    finally:
        conn.close()
    return get_fact(fact_id)


def tag_fact(fact_id: int, entities: Iterable[Dict[str, str]]) -> None:
    """Aggiunge entità a un fatto senza toccare quelle che ha già, e lo segna come analizzato (anche senza entità)."""
    conn = vector_store._get_conn()
    try:
        _link(conn, fact_id, entities)
        conn.execute(
            "UPDATE vec_memory SET metadata_json = json_set(COALESCE(metadata_json, '{}'), '$.entities_checked', 1) WHERE id = ?",
            (fact_id,),
        )
        conn.commit()
    finally:
        conn.close()


def delete_fact(fact_id: int) -> bool:
    if get_fact(fact_id) is None:
        return False
    vector_store.delete_memory(fact_id)
    conn = vector_store._get_conn()
    try:
        conn.execute("DELETE FROM memory_fact_entities WHERE fact_id = ?", (fact_id,))
        _drop_orphans(conn)
        conn.commit()
    finally:
        conn.close()
    return True


def clear_facts() -> int:
    deleted = vector_store.clear_all_memories(kind="fact")
    conn = vector_store._get_conn()
    try:
        conn.execute("DELETE FROM memory_fact_entities")
        conn.execute("DELETE FROM memory_entities")
        conn.commit()
    finally:
        conn.close()
    return deleted


def update_entity(entity_id: int, name: str, entity_type: str) -> Optional[Dict[str, Any]]:
    key = entity_key(name)
    conn = vector_store._get_conn()
    try:
        if not conn.execute("SELECT 1 FROM memory_entities WHERE id = ?", (entity_id,)).fetchone():
            return None
        clash = conn.execute("SELECT id, name FROM memory_entities WHERE key = ? AND id != ?", (key, entity_id)).fetchone()
        if clash:
            raise EntityConflictError(clash[0], clash[1])
        conn.execute(
            "UPDATE memory_entities SET name = ?, key = ?, type = ? WHERE id = ?",
            (re.sub(r"\s+", " ", name).strip(), key, entity_type if entity_type in ENTITY_TYPES else "other", entity_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_entity(entity_id)


def merge_entities(source_id: int, target_id: int) -> Optional[Dict[str, Any]]:
    """Sposta i fatti di `source_id` su `target_id` ed elimina `source_id`."""
    if source_id == target_id:
        return get_entity(target_id)
    conn = vector_store._get_conn()
    try:
        found = conn.execute("SELECT COUNT(*) FROM memory_entities WHERE id IN (?, ?)", (source_id, target_id)).fetchone()[0]
        if found != 2:
            return None
        conn.execute(
            "INSERT OR IGNORE INTO memory_fact_entities (fact_id, entity_id) SELECT fact_id, ? FROM memory_fact_entities WHERE entity_id = ?",
            (target_id, source_id),
        )
        conn.execute("DELETE FROM memory_fact_entities WHERE entity_id = ?", (source_id,))
        conn.execute("DELETE FROM memory_entities WHERE id = ?", (source_id,))
        conn.commit()
    finally:
        conn.close()
    return get_entity(target_id)


def delete_entity(entity_id: int) -> bool:
    """Toglie l'entità da tutti i fatti; i fatti restano."""
    conn = vector_store._get_conn()
    try:
        conn.execute("DELETE FROM memory_fact_entities WHERE entity_id = ?", (entity_id,))
        deleted = conn.execute("DELETE FROM memory_entities WHERE id = ?", (entity_id,)).rowcount
        conn.commit()
        return deleted > 0
    finally:
        conn.close()
