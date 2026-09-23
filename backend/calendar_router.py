"""Endpoint REST FastAPI per la gestione del Calendario.

Fornisce:
- Gestione calendari (lista, creazione, aggiornamento, cancellazione).
- Gestione eventi (CRUD, viste per intervallo temporale, ricerca).
- Controllo disponibilità / conflitti.
- Sincronizzazione manuale e automatica con sorgenti esterne (Google Calendar / iCal / CalDAV).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

import calendar_db
import calendar_sync
import config

logger = logging.getLogger("calendar.router")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(x_api_key: Optional[str] = Security(api_key_header)):
    expected_key = config.API_SECRET_KEY.strip()
    if expected_key:
        if not x_api_key or x_api_key != expected_key:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")
    return x_api_key


router = APIRouter(prefix="/v1/calendar", tags=["Calendar"], dependencies=[Depends(verify_api_key)])


# --- Pydantic Models per Richieste / Risposte ---

class CalendarCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field(default="#4f46e5")
    description: Optional[str] = ""
    is_default: bool = False
    is_visible: bool = True
    provider: str = Field(default="local")
    external_feed_url: Optional[str] = None


class CalendarUpdateRequest(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    is_visible: Optional[bool] = None
    provider: Optional[str] = None
    external_feed_url: Optional[str] = None


class EventCreateRequest(BaseModel):
    calendar_id: Optional[str] = None
    summary: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = ""
    location: Optional[str] = ""
    dtstart: str = Field(..., description="ISO 8601 start time")
    dtend: Optional[str] = Field(default=None, description="ISO 8601 end time")
    duration: Optional[str] = Field(default=None, description="Durata naturale (es. '30m', '1h', '45m')")
    all_day: bool = False
    rrule: Optional[str] = None
    category: Optional[str] = "event"
    color: Optional[str] = None
    status: str = "confirmed"


class EventUpdateRequest(BaseModel):
    calendar_id: Optional[str] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    dtstart: Optional[str] = None
    dtend: Optional[str] = None
    duration: Optional[str] = None
    all_day: Optional[bool] = None
    rrule: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None
    status: Optional[str] = None


# --- Endpoints Calendari ---

@router.get("/calendars")
async def list_calendars():
    """Restituisce l'elenco di tutti i calendari configurati."""
    return calendar_db.list_calendars()


@router.post("/calendars", status_code=201)
async def create_calendar(payload: CalendarCreateRequest):
    """Crea un nuovo calendario."""
    res = calendar_db.create_calendar(payload.dict())
    if not res:
        raise HTTPException(status_code=400, detail="Impossibile creare il calendario.")
    return res


@router.put("/calendars/{calendar_id}")
async def update_calendar(calendar_id: str, payload: CalendarUpdateRequest):
    """Aggiorna le impostazioni di un calendario esistente."""
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    res = calendar_db.update_calendar(calendar_id, updates)
    if not res:
        raise HTTPException(status_code=404, detail="Calendario non trovato.")
    return res


@router.delete("/calendars/{calendar_id}")
async def delete_calendar(calendar_id: str):
    """Elimina un calendario e i relativi eventi."""
    success = calendar_db.delete_calendar(calendar_id)
    if not success:
        raise HTTPException(status_code=404, detail="Calendario non trovato.")
    return {"status": "deleted", "calendar_id": calendar_id}


# --- Endpoints Eventi ---

@router.get("/events")
async def list_events(
    calendar_id: Optional[str] = Query(default=None),
    start_date: Optional[str] = Query(default=None, description="Data inizio YYYY-MM-DD o ISO"),
    end_date: Optional[str] = Query(default=None, description="Data fine YYYY-MM-DD o ISO"),
    query: Optional[str] = Query(default=None, description="Filtro testuale su titolo/descrizione/luogo"),
):
    """Restituisce gli eventi filtrati per calendario, periodo o testo."""
    return calendar_db.list_events(
        calendar_id=calendar_id,
        start_date=start_date,
        end_date=end_date,
        query=query,
    )


@router.get("/events/upcoming")
async def get_upcoming_events(days: int = Query(default=7, ge=1, le=90)):
    """Restituisce gli eventi in arrivo per i prossimi N giorni."""
    events = calendar_db.get_upcoming_events(days=days)
    return {"days": days, "count": len(events), "events": events}


@router.get("/events/{event_id}")
async def get_event(event_id: str):
    """Dettagli di un singolo evento."""
    ev = calendar_db.get_event_by_id(event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Evento non trovato.")
    return ev


@router.post("/events", status_code=201)
async def create_event(payload: EventCreateRequest):
    """Crea manualmente un evento."""
    # Deduplicazione automatica prima della creazione
    dup = calendar_db.find_duplicate_event(payload.summary, payload.dtstart, payload.calendar_id)
    if dup:
        return {
            "status": "already_exists",
            "duplicate": True,
            "event": dup,
            "message": "Esiste già un evento identico per questa data e ora.",
        }

    # Risoluzione automatica di calendar_id di default se non fornito
    cal_id = payload.calendar_id
    if not cal_id:
        cals = calendar_db.list_calendars()
        cal_id = cals[0]["id"] if cals else "cal_personal"

    dtstart = payload.dtstart
    dtend = payload.dtend
    if not dtend and payload.duration:
        dtend = calendar_db._calculate_dtend(dtstart, payload.duration)

    event_dict = {
        "calendar_id": cal_id,
        "summary": payload.summary,
        "description": payload.description or "",
        "location": payload.location or "",
        "dtstart": dtstart,
        "dtend": dtend,
        "all_day": payload.all_day,
        "rrule": payload.rrule,
        "category": payload.category or "event",
        "color": payload.color,
        "status": payload.status,
        "source_type": "manual",
    }
    created = calendar_db.create_event(event_dict)
    return {"status": "created", "duplicate": False, "event": created}


@router.put("/events/{event_id}")
async def update_event(event_id: str, payload: EventUpdateRequest):
    """Aggiorna un evento esistente."""
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    if "duration" in updates and "dtstart" in updates and "dtend" not in updates:
        updates["dtend"] = calendar_db._calculate_dtend(updates["dtstart"], updates["duration"])
    updates.pop("duration", None)

    updated = calendar_db.update_event(event_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Evento non trovato.")
    return {"status": "updated", "event": updated}


@router.delete("/events/{event_id}")
async def delete_event(event_id: str):
    """Elimina un evento dal calendario."""
    success = calendar_db.delete_event(event_id)
    if not success:
        raise HTTPException(status_code=404, detail="Evento non trovato.")
    return {"status": "deleted", "event_id": event_id}


# --- Endpoint Disponibilità / Sincronizzazione ---

@router.get("/availability")
async def check_availability(
    start_time: str = Query(..., description="Data/ora inizio ISO"),
    end_time: Optional[str] = Query(default=None, description="Data/ora fine ISO"),
    duration: Optional[str] = Query(default=None, description="Durata (es. '1h', '30m')"),
    calendar_id: Optional[str] = Query(default=None),
):
    """Verifica se lo slot specificato è libero o occupato da conflitti."""
    if not end_time and duration:
        end_time = calendar_db._calculate_dtend(start_time, duration)
    elif not end_time:
        end_time = calendar_db._calculate_dtend(start_time, "1h")

    conflicts = calendar_db.check_conflict(start_time, end_time, calendar_id)
    return {
        "start_time": start_time,
        "end_time": end_time,
        "available": len(conflicts) == 0,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }


@router.post("/sync")
async def sync_calendars():
    """Attiva la sincronizzazione per tutti i calendari esterni collegati."""
    res = calendar_sync.sync_all_external_calendars()
    return {"status": "completed", "result": res}
