"""Modulo di sincronizzazione per calendari esterni (Google Calendar, CalDAV, iCal/WebCal).

Supporta:
1. iCal / WebCal feed URL (es. link iCal segreto di Google Calendar, iCloud, Nextcloud).
2. Sincronizzazione incrementale bidirezionale/unidirezionale nel DB locale SQLite.
3. Parsing standard RFC 5545 iCalendar (VEVENT, DTSTART, DTEND, SUMMARY, DESCRIPTION, LOCATION).
4. Integrazione con service_integrations del backend.
"""

import json
import logging
import re
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import calendar_db

logger = logging.getLogger("calendar.sync")


def parse_ical_text(ical_content: str) -> List[Dict[str, Any]]:
    """Effettua il parsing di uno stream iCalendar (.ics) e restituisce una lista di eventi normalizzati."""
    events = []
    lines = ical_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    
    # Gestione delle righe 'unfolding' (righe che iniziano con spazio o tab)
    unfolded_lines: List[str] = []
    for line in lines:
        if line.startswith(" ") or line.startswith("\t"):
            if unfolded_lines:
                unfolded_lines[-1] += line[1:]
        else:
            unfolded_lines.append(line)

    current_event: Optional[Dict[str, Any]] = None
    in_vevent = False

    def clean_val(v: str) -> str:
        return v.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()

    for line in unfolded_lines:
        line_str = line.strip()
        if not line_str:
            continue
        if line_str == "BEGIN:VEVENT":
            in_vevent = True
            current_event = {}
            continue
        elif line_str == "END:VEVENT":
            if in_vevent and current_event:
                # Validazione minima
                if "summary" in current_event and "dtstart" in current_event:
                    events.append(current_event)
            in_vevent = False
            current_event = None
            continue

        if not in_vevent or current_event is None:
            continue

        parts = line.split(":", 1)
        if len(parts) < 2:
            continue

        key_part, val = parts[0], parts[1]
        key_name = key_part.split(";")[0].upper()
        clean_v = clean_val(val)

        if key_name == "UID":
            current_event["uid"] = clean_v
            current_event["external_uid"] = clean_v
        elif key_name == "SUMMARY":
            current_event["summary"] = clean_v
        elif key_name == "DESCRIPTION":
            current_event["description"] = clean_v
        elif key_name == "LOCATION":
            current_event["location"] = clean_v
        elif key_name == "DTSTART":
            current_event["dtstart"] = _parse_ical_datetime(clean_v)
            if "VALUE=DATE" in key_part:
                current_event["all_day"] = True
        elif key_name == "DTEND":
            current_event["dtend"] = _parse_ical_datetime(clean_v)
        elif key_name == "STATUS":
            current_event["status"] = clean_v.lower()
        elif key_name == "CATEGORIES":
            current_event["category"] = clean_v

    return events


def _parse_ical_datetime(dt_str: str) -> str:
    """Converte date iCal (es. 20260925T110000Z o 20260925) nel formato ISO 8601 YYYY-MM-DDTHH:MM:SS."""
    clean = dt_str.replace("Z", "").strip()
    if "T" in clean:
        # Formato YYYYMMDDTHHMMSS
        try:
            dt = datetime.strptime(clean, "%Y%m%dT%H%M%S")
            return dt.isoformat()
        except Exception:
            return dt_str
    else:
        # Formato solo data YYYYMMDD
        try:
            dt = datetime.strptime(clean, "%Y%m%d")
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return dt_str


def fetch_and_sync_ical_feed(feed_url: str, calendar_id: str, max_events: int = 500) -> Dict[str, Any]:
    """Scarica un feed iCal (HTTP/HTTPS/webcal) ed esegue il merge degli eventi nel calendario locale."""
    if feed_url.startswith("webcal://"):
        feed_url = "https://" + feed_url[9:]

    headers = {"User-Agent": "Homelab-Agent-Calendar/1.0"}
    req = urllib.request.Request(feed_url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.error(f"Errore durante il download del feed iCal ({feed_url}): {e}")
        return {"success": False, "error": str(e), "synced_count": 0}

    parsed_events = parse_ical_text(content)
    synced_count = 0
    updated_count = 0

    for ev in parsed_events[:max_events]:
        uid = ev.get("uid") or f"ext_{hash(ev.get('summary', '') + ev.get('dtstart', ''))}"
        dtstart = ev.get("dtstart")
        if not dtstart:
            continue

        existing = calendar_db.get_event_by_id(uid)
        dtend = ev.get("dtend")
        all_day = ev.get("all_day", False)

        event_data = {
            "uid": uid,
            "calendar_id": calendar_id,
            "summary": ev.get("summary", "Evento Sincronizzato"),
            "description": ev.get("description", ""),
            "location": ev.get("location", ""),
            "dtstart": dtstart,
            "dtend": dtend,
            "all_day": all_day,
            "category": ev.get("category", "sync"),
            "source_type": "sync",
            "source_id": feed_url,
        }

        if existing:
            calendar_db.update_event(uid, event_data)
            updated_count += 1
        else:
            calendar_db.create_event(event_data)
            synced_count += 1

    logger.info(f"Sincronizzazione iCal completata per '{calendar_id}': {synced_count} creati, {updated_count} aggiornati.")
    return {
        "success": True,
        "synced_count": synced_count,
        "updated_count": updated_count,
        "total_parsed": len(parsed_events),
    }


def sync_all_external_calendars() -> Dict[str, Any]:
    """Ispeziona le integrazioni attive di tipo 'google_calendar' o 'caldav' ed esegue il sync per ciascuna."""
    from integrations.manager import get_integration_manager
    mgr = get_integration_manager()
    integrations = mgr.list_integrations(decrypt=True)

    results = []
    for item in integrations:
        stype = item.get("service_type")
        if stype in ("google_calendar", "caldav", "webcal"):
            cfg = item.get("config", {})
            feed_url = cfg.get("ical_feed_url") or cfg.get("feed_url") or cfg.get("url")
            cal_id = cfg.get("target_calendar_id") or "cal_personal"
            if feed_url:
                res = fetch_and_sync_ical_feed(feed_url, calendar_id=cal_id)
                results.append({"integration_id": item.get("id"), "result": res})

    return {"total_synced": len(results), "details": results}
