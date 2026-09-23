"""Gestione archiviazione locale SQLite per Calendari ed Eventi.

Fornisce:
- Modello local-first per calendari ed eventi con supporto a ricorrenze, timezone e metadati.
- Isolamento del database (/data/calendar.db) con WAL mode e busy timeout a 30s.
- Deduplicazione automatica per prevenire eventi duplicati da email o agent loop.
- Tracciamento tombstone per la sincronizzazione bidirezionale remota (CalDAV / Google).
- Algoritmo deterministico per il calcolo di slot liberi e verifica conflitti.
- Supporto completo per durate naturali (es. '30m', '1h', '1h30m') e calcolo deterministico dtend.
"""

import json
import logging
import re
import sqlite3
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import config

logger = logging.getLogger("calendar.db")


def get_db_path() -> str:
    path = getattr(config, "CALENDAR_DB_PATH", "/data/calendar.db")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    target_path = db_path or get_db_path()
    conn = sqlite3.connect(target_path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL;")
    cursor.execute("PRAGMA synchronous = NORMAL;")
    cursor.execute("PRAGMA busy_timeout = 30000;")
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.close()
    return conn


def init_calendar_db(db_path: Optional[str] = None):
    """Inizializza le tabelle del database di calendario e crea i calendari predefiniti."""
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()

        # 1. Tabella Calendari
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS calendars (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                color TEXT NOT NULL DEFAULT '#3b82f6',
                source TEXT NOT NULL DEFAULT 'local',
                sync_url TEXT,
                account_id TEXT,
                is_visible INTEGER NOT NULL DEFAULT 1,
                is_read_only INTEGER NOT NULL DEFAULT 0,
                last_synced_at TEXT,
                sync_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        # 2. Tabella Eventi (Schema nativo completo)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                uid TEXT PRIMARY KEY,
                calendar_id TEXT NOT NULL REFERENCES calendars(id) ON DELETE CASCADE,
                summary TEXT NOT NULL,
                description TEXT DEFAULT '',
                location TEXT DEFAULT '',
                dtstart TEXT NOT NULL,
                dtend TEXT NOT NULL,
                all_day INTEGER NOT NULL DEFAULT 0,
                is_utc INTEGER NOT NULL DEFAULT 1,
                rrule TEXT DEFAULT '',
                recurrence_exdates TEXT DEFAULT '[]',
                category TEXT DEFAULT 'general',
                importance TEXT DEFAULT 'normal',
                status TEXT DEFAULT 'confirmed',
                color TEXT DEFAULT NULL,
                reminder_minutes INTEGER DEFAULT NULL,
                remote_href TEXT,
                remote_etag TEXT,
                sync_pending TEXT DEFAULT NULL,
                source_type TEXT DEFAULT 'manual',
                source_id TEXT DEFAULT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        # 3. Tabella Tombstones (Cancellazioni da propagare ai server remoti)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS calendar_tombstones (
                uid TEXT PRIMARY KEY,
                calendar_id TEXT NOT NULL,
                remote_href TEXT,
                deleted_at TEXT NOT NULL,
                sync_attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            );
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cal_events_dt ON calendar_events(dtstart, dtend);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cal_events_cal ON calendar_events(calendar_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cal_events_cat ON calendar_events(category);")

        conn.commit()

        # Seed di calendari iniziali se la tabella è vuota
        cursor.execute("SELECT COUNT(*) FROM calendars;")
        count = cursor.fetchone()[0]
        if count == 0:
            now_iso = datetime.now(timezone.utc).isoformat()
            cursor.execute("""
                INSERT INTO calendars (id, name, color, source, is_visible, is_read_only, created_at, updated_at)
                VALUES (?, ?, ?, 'local', 1, 0, ?, ?);
            """, ("cal_default_personal", "Personale", "#3b82f6", now_iso, now_iso))
            cursor.execute("""
                INSERT INTO calendars (id, name, color, source, is_visible, is_read_only, created_at, updated_at)
                VALUES (?, ?, ?, 'local', 1, 0, ?, ?);
            """, ("cal_default_homelab", "Homelab", "#8b5cf6", now_iso, now_iso))
            conn.commit()
            logger.info("Inizializzati calendari di default: 'Personale' e 'Homelab'")

        conn.close()
    except Exception as e:
        logger.error(f"Errore inizializzazione calendar.db: {e}")
        raise


# --- Utility Temporali e Durata ---

def _parse_natural_duration(duration_str: str) -> Optional[int]:
    """Converte durate naturali come '30m', '1h', '1h30m', '90min' in minuti interi."""
    if not duration_str or not isinstance(duration_str, str):
        return None
    d = duration_str.strip().lower()

    match_hm = re.match(r"^(\d+)\s*h(?:ours?|ore)?\s*(\d+)?\s*(?:m|min|minuti)?$", d)
    if match_hm:
        hours = int(match_hm.group(1))
        minutes = int(match_hm.group(2) or 0)
        return hours * 60 + minutes

    match_h = re.match(r"^(\d+)\s*h(?:ours?|ore)?$", d)
    if match_h:
        return int(match_h.group(1)) * 60

    match_m = re.match(r"^(\d+)\s*(?:m|min|minuti|minutes?)$", d)
    if match_m:
        return int(match_m.group(1))

    if d.isdigit():
        return int(d)

    return None


def _calculate_dtend(dtstart: str, duration: str) -> str:
    """Calcola la data/ora di fine aggiungendo una durata naturale a dtstart."""
    minutes = _parse_natural_duration(duration) or 60
    try:
        clean_s = dtstart.replace("Z", "").split("+")[0]
        s_dt = datetime.fromisoformat(clean_s)
        e_dt = s_dt + timedelta(minutes=minutes)
        return e_dt.isoformat()
    except Exception:
        return dtstart


# --- CRUD Calendars ---

def list_calendars(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Elenca tutti i calendari registrati con conteggio eventi."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.*, (SELECT COUNT(*) FROM calendar_events e WHERE e.calendar_id = c.id) as event_count
            FROM calendars c
            ORDER BY c.created_at ASC;
        """)
        rows = cursor.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["is_visible"] = bool(d["is_visible"])
            d["is_read_only"] = bool(d["is_read_only"])
            result.append(d)
        return result
    finally:
        conn.close()


def get_calendar(calendar_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Recupera un singolo calendario per ID."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM calendars WHERE id = ?;", (calendar_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["is_visible"] = bool(d["is_visible"])
        d["is_read_only"] = bool(d["is_read_only"])
        return d
    finally:
        conn.close()


def save_calendar(data: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """Crea o aggiorna un calendario (upsert pulito)."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        cal_id = data.get("id") or f"cal_{uuid.uuid4().hex[:10]}"

        existing = get_calendar(cal_id, db_path=db_path)
        if existing:
            cursor.execute("""
                UPDATE calendars
                SET name = ?, color = ?, source = ?, sync_url = ?, account_id = ?,
                    is_visible = ?, is_read_only = ?, last_synced_at = ?, sync_error = ?, updated_at = ?
                WHERE id = ?;
            """, (
                data.get("name", existing["name"]),
                data.get("color", existing["color"]),
                data.get("source", data.get("provider", existing["source"])),
                data.get("sync_url", data.get("external_feed_url", existing.get("sync_url"))),
                data.get("account_id", existing.get("account_id")),
                1 if data.get("is_visible", existing["is_visible"]) else 0,
                1 if data.get("is_read_only", existing["is_read_only"]) else 0,
                data.get("last_synced_at", existing.get("last_synced_at")),
                data.get("sync_error", existing.get("sync_error")),
                now_iso,
                cal_id,
            ))
        else:
            cursor.execute("""
                INSERT INTO calendars (id, name, color, source, sync_url, account_id, is_visible, is_read_only, last_synced_at, sync_error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                cal_id,
                data.get("name", "Nuovo Calendario"),
                data.get("color", "#3b82f6"),
                data.get("source", data.get("provider", "local")),
                data.get("sync_url", data.get("external_feed_url")),
                data.get("account_id"),
                1 if data.get("is_visible", True) else 0,
                1 if data.get("is_read_only", False) else 0,
                data.get("last_synced_at"),
                data.get("sync_error"),
                now_iso,
                now_iso,
            ))
        conn.commit()
        return get_calendar(cal_id, db_path=db_path)  # type: ignore
    finally:
        conn.close()


def create_calendar(data: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """Crea un nuovo calendario."""
    return save_calendar(data, db_path=db_path)


def update_calendar(calendar_id: str, updates: Dict[str, Any], db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Aggiorna le proprietà di un calendario esistente."""
    existing = get_calendar(calendar_id, db_path=db_path)
    if not existing:
        return None
    merged = {**existing, **updates, "id": calendar_id}
    return save_calendar(merged, db_path=db_path)


def delete_calendar(calendar_id: str, db_path: Optional[str] = None) -> bool:
    """Elimina un calendario e tutti i suoi eventi associati."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM calendars WHERE id = ?;", (calendar_id,))
        affected = cursor.rowcount > 0
        conn.commit()
        return affected
    finally:
        conn.close()


# --- CRUD Events ---

def _format_event_row(d: Dict[str, Any]) -> Dict[str, Any]:
    """Uniforma i tipi di dato per una riga evento (booleani, json, alias id/uid)."""
    d["id"] = d.get("uid")
    d["all_day"] = bool(d.get("all_day"))
    d["is_utc"] = bool(d.get("is_utc"))
    try:
        d["recurrence_exdates"] = json.loads(d.get("recurrence_exdates") or "[]")
    except Exception:
        d["recurrence_exdates"] = []
    return d


def list_events(
    start_dt: Optional[str] = None,
    end_dt: Optional[str] = None,
    calendar_ids: Optional[List[str]] = None,
    category: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 500,
    db_path: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    calendar_id: Optional[str] = None,
    start_after: Optional[str] = None,
    start_before: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Recupera gli eventi filtrati per data, calendario, categoria o testo."""
    effective_start = start_dt or start_date or start_after
    effective_end = end_dt or end_date or start_before

    # Normalizzazione calendar_ids
    target_cals = list(calendar_ids) if calendar_ids else []
    if calendar_id and calendar_id not in target_cals:
        target_cals.append(calendar_id)

    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        clauses = []
        params = []

        if effective_start:
            clauses.append("dtend >= ?")
            params.append(effective_start)
        if effective_end:
            clauses.append("dtstart <= ?")
            params.append(effective_end)
        if target_cals:
            placeholders = ",".join("?" for _ in target_cals)
            clauses.append(f"e.calendar_id IN ({placeholders})")
            params.extend(target_cals)
        if category:
            clauses.append("e.category = ?")
            params.append(category)
        if query:
            clauses.append("(e.summary LIKE ? OR e.description LIKE ? OR e.location LIKE ?)")
            like_q = f"%{query}%"
            params.extend([like_q, like_q, like_q])

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""
            SELECT e.*, c.name as calendar_name, c.color as calendar_color, c.source as calendar_source
            FROM calendar_events e
            JOIN calendars c ON e.calendar_id = c.id
            {where_sql}
            ORDER BY e.dtstart ASC
            LIMIT ?;
        """
        params.append(limit)
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return [_format_event_row(dict(r)) for r in rows]
    finally:
        conn.close()


def get_event(uid: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Recupera un singolo evento per UID."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT e.*, c.name as calendar_name, c.color as calendar_color, c.source as calendar_source
            FROM calendar_events e
            JOIN calendars c ON e.calendar_id = c.id
            WHERE e.uid = ?;
        """, (uid,))
        row = cursor.fetchone()
        if not row:
            return None
        return _format_event_row(dict(row))
    finally:
        conn.close()


get_event_by_id = get_event


def get_upcoming_events(days: int = 7, calendar_id: Optional[str] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Restituisce gli eventi imminenti a partire da adesso per i successivi N giorni."""
    now_iso = datetime.now().isoformat()
    future_iso = (datetime.now() + timedelta(days=days)).isoformat()
    return list_events(start_dt=now_iso, end_dt=future_iso, calendar_id=calendar_id, db_path=db_path)


def find_existing_event(
    summary: str,
    dtstart: str,
    calendar_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Trova un evento esistente con lo stesso titolo (case-insensitive) e orario per deduplicazione."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        clean_sum = (summary or "").strip().lower()
        start_prefix = dtstart[:16] if len(dtstart) >= 16 else dtstart

        if calendar_id:
            cursor.execute("""
                SELECT uid, summary, dtstart, dtend, calendar_id
                FROM calendar_events
                WHERE calendar_id = ? AND LOWER(TRIM(summary)) = ? AND dtstart LIKE ?
                LIMIT 1;
            """, (calendar_id, clean_sum, f"{start_prefix}%"))
        else:
            cursor.execute("""
                SELECT uid, summary, dtstart, dtend, calendar_id
                FROM calendar_events
                WHERE LOWER(TRIM(summary)) = ? AND dtstart LIKE ?
                LIMIT 1;
            """, (clean_sum, f"{start_prefix}%"))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["id"] = d.get("uid")
        return d
    finally:
        conn.close()


find_duplicate_event = find_existing_event


def save_event(event_dict: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """Crea o aggiorna un evento nel database SQLite."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        uid = event_dict.get("uid") or event_dict.get("id") or f"ev_{uuid.uuid4().hex}"

        cal_id = event_dict.get("calendar_id")
        if not cal_id:
            cursor.execute("SELECT id FROM calendars WHERE is_read_only = 0 ORDER BY created_at ASC LIMIT 1;")
            row = cursor.fetchone()
            cal_id = row[0] if row else "cal_default_personal"

        # Verifica se il calendario esiste
        cursor.execute("SELECT source FROM calendars WHERE id = ?;", (cal_id,))
        cal_row = cursor.fetchone()
        cal_source = cal_row[0] if cal_row else "local"

        # Gestione sync_pending se calendario remoto
        existing = get_event(uid, db_path=db_path)
        pending_flag = event_dict.get("sync_pending")
        if cal_source in ("caldav", "google") and not pending_flag:
            pending_flag = "update" if existing else "create"

        exdates_json = json.dumps(event_dict.get("recurrence_exdates", [])) if isinstance(event_dict.get("recurrence_exdates"), list) else "[]"

        # Calcolo dtend deterministico se duration è fornita
        dtstart = event_dict.get("dtstart") or event_dict.get("start_time") or now_iso
        dtend = event_dict.get("dtend") or event_dict.get("end_time")
        if not dtend and event_dict.get("duration"):
            dtend = _calculate_dtend(dtstart, event_dict["duration"])
        elif not dtend:
            dtend = _calculate_dtend(dtstart, "1h")

        if existing:
            cursor.execute("""
                UPDATE calendar_events
                SET calendar_id = ?, summary = ?, description = ?, location = ?,
                    dtstart = ?, dtend = ?, all_day = ?, is_utc = ?, rrule = ?,
                    recurrence_exdates = ?, category = ?, importance = ?, status = ?,
                    color = ?, reminder_minutes = ?, sync_pending = COALESCE(?, sync_pending),
                    source_type = COALESCE(?, source_type), source_id = COALESCE(?, source_id),
                    updated_at = ?
                WHERE uid = ?;
            """, (
                cal_id,
                event_dict.get("summary", existing["summary"]),
                event_dict.get("description", existing["description"]),
                event_dict.get("location", existing["location"]),
                dtstart,
                dtend,
                1 if event_dict.get("all_day", existing["all_day"]) else 0,
                1 if event_dict.get("is_utc", existing["is_utc"]) else 0,
                event_dict.get("rrule", existing["rrule"]),
                exdates_json,
                event_dict.get("category", existing["category"]),
                event_dict.get("importance", existing["importance"]),
                event_dict.get("status", existing["status"]),
                event_dict.get("color", existing.get("color")),
                event_dict.get("reminder_minutes", existing.get("reminder_minutes")),
                pending_flag,
                event_dict.get("source_type"),
                event_dict.get("source_id"),
                now_iso,
                uid,
            ))
        else:
            cursor.execute("""
                INSERT INTO calendar_events (
                    uid, calendar_id, summary, description, location, dtstart, dtend,
                    all_day, is_utc, rrule, recurrence_exdates, category, importance,
                    status, color, reminder_minutes, remote_href, remote_etag, sync_pending,
                    source_type, source_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                uid,
                cal_id,
                event_dict.get("summary", "Senza Titolo"),
                event_dict.get("description", ""),
                event_dict.get("location", ""),
                dtstart,
                dtend,
                1 if event_dict.get("all_day") else 0,
                1 if event_dict.get("is_utc", True) else 0,
                event_dict.get("rrule", ""),
                exdates_json,
                event_dict.get("category", "general"),
                event_dict.get("importance", "normal"),
                event_dict.get("status", "confirmed"),
                event_dict.get("color"),
                event_dict.get("reminder_minutes"),
                event_dict.get("remote_href"),
                event_dict.get("remote_etag"),
                pending_flag,
                event_dict.get("source_type", "manual"),
                event_dict.get("source_id"),
                now_iso,
                now_iso,
            ))

        conn.commit()
        return get_event(uid, db_path=db_path)  # type: ignore
    finally:
        conn.close()


def create_event(event_dict_or_summary: Union[Dict[str, Any], str] = None, **kwargs) -> Dict[str, Any]:
    """Crea un nuovo evento, accettando o un dizionario o parametri chiave-valore."""
    if isinstance(event_dict_or_summary, dict):
        merged = {**event_dict_or_summary, **kwargs}
    elif isinstance(event_dict_or_summary, str):
        merged = {"summary": event_dict_or_summary, **kwargs}
    else:
        merged = dict(kwargs)

    # Supporto alias per start_time -> dtstart
    if "start_time" in merged and "dtstart" not in merged:
        merged["dtstart"] = merged.pop("start_time")
    if "end_time" in merged and "dtend" not in merged:
        merged["dtend"] = merged.pop("end_time")

    return save_event(merged)


def update_event(uid: str, updates: Optional[Dict[str, Any]] = None, **kwargs) -> Optional[Dict[str, Any]]:
    """Aggiorna un evento esistente."""
    existing = get_event(uid)
    if not existing:
        return None
    merged_updates = dict(updates or {})
    merged_updates.update(kwargs)

    if "start_time" in merged_updates and "dtstart" not in merged_updates:
        merged_updates["dtstart"] = merged_updates.pop("start_time")
    if "end_time" in merged_updates and "dtend" not in merged_updates:
        merged_updates["dtend"] = merged_updates.pop("end_time")

    merged = {**existing, **merged_updates, "uid": uid}
    return save_event(merged)


def delete_event(uid: str, db_path: Optional[str] = None) -> bool:
    """Elimina un evento. Se appartiene a un calendario remoto, memorizza un tombstone."""
    conn = get_db_connection(db_path)
    try:
        ev = get_event(uid, db_path=db_path)
        if not ev:
            return False

        cursor = conn.cursor()
        if ev.get("calendar_source") in ("caldav", "google") and ev.get("remote_href"):
            now_iso = datetime.now(timezone.utc).isoformat()
            cursor.execute("""
                INSERT OR REPLACE INTO calendar_tombstones (uid, calendar_id, remote_href, deleted_at)
                VALUES (?, ?, ?, ?);
            """, (uid, ev["calendar_id"], ev["remote_href"], now_iso))

        cursor.execute("DELETE FROM calendar_events WHERE uid = ?;", (uid,))
        affected = cursor.rowcount > 0
        conn.commit()
        return affected
    finally:
        conn.close()


# --- Conflitti & Ricerca Slot Liberi (Availability) ---

def check_conflict(
    start_time: str,
    end_time: str,
    calendar_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Restituisce la lista di eventi che si sovrappongono all'intervallo temporale specificato."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        clauses = ["status != 'cancelled'", "dtstart < ?", "dtend > ?"]
        params = [end_time, start_time]

        if calendar_id:
            clauses.append("calendar_id = ?")
            params.append(calendar_id)

        sql = f"""
            SELECT e.*, c.name as calendar_name, c.color as calendar_color
            FROM calendar_events e
            JOIN calendars c ON e.calendar_id = c.id
            WHERE {' AND '.join(clauses)}
            ORDER BY e.dtstart ASC;
        """
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return [_format_event_row(dict(r)) for r in rows]
    finally:
        conn.close()


def find_free_slots(
    target_date: str,
    duration_minutes: int = 30,
    start_hour: int = 9,
    end_hour: int = 18,
    calendar_ids: Optional[List[str]] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Calcola in modo deterministico gli slot liberi per una data specificata (formato YYYY-MM-DD)."""
    try:
        target_d = date.fromisoformat(target_date.split("T")[0])
    except Exception:
        target_d = date.today()

    day_start = datetime.combine(target_d, time(start_hour, 0))
    day_end = datetime.combine(target_d, time(end_hour, 0))

    day_str_start = day_start.isoformat()
    day_str_end = day_end.isoformat()
    events = list_events(
        start_dt=day_str_start,
        end_dt=day_str_end,
        calendar_ids=calendar_ids,
        db_path=db_path,
    )

    busy_intervals: List[Tuple[datetime, datetime]] = []
    for ev in events:
        if ev.get("status") == "cancelled":
            continue
        try:
            s_raw = ev["dtstart"].replace("Z", "").split("+")[0]
            e_raw = ev["dtend"].replace("Z", "").split("+")[0]
            s = datetime.fromisoformat(s_raw)
            e = datetime.fromisoformat(e_raw)
            s = max(day_start, s)
            e = min(day_end, e)
            if e > s:
                busy_intervals.append((s, e))
        except Exception as ex:
            logger.warning(f"Errore parsing orari evento {ev.get('uid')}: {ex}")

    busy_intervals.sort(key=lambda x: x[0])
    merged_busy: List[Tuple[datetime, datetime]] = []
    for b_start, b_end in busy_intervals:
        if not merged_busy:
            merged_busy.append((b_start, b_end))
        else:
            last_start, last_end = merged_busy[-1]
            if b_start <= last_end:
                merged_busy[-1] = (last_start, max(last_end, b_end))
            else:
                merged_busy.append((b_start, b_end))

    free_slots: List[Dict[str, Any]] = []
    curr = day_start
    slot_delta = timedelta(minutes=duration_minutes)

    for b_start, b_end in merged_busy:
        if b_start > curr:
            gap = b_start - curr
            if gap >= slot_delta:
                free_slots.append({
                    "start": curr.strftime("%H:%M"),
                    "end": b_start.strftime("%H:%M"),
                    "start_iso": curr.isoformat(),
                    "end_iso": b_start.isoformat(),
                    "duration_minutes": int(gap.total_seconds() / 60),
                })
        curr = max(curr, b_end)

    if day_end > curr:
        gap = day_end - curr
        if gap >= slot_delta:
            free_slots.append({
                "start": curr.strftime("%H:%M"),
                "end": day_end.strftime("%H:%M"),
                "start_iso": curr.isoformat(),
                "end_iso": day_end.isoformat(),
                "duration_minutes": int(gap.total_seconds() / 60),
            })

    return free_slots


# Inizializza automaticamente lo schema al caricamento
try:
    init_calendar_db()
except Exception:
    pass
