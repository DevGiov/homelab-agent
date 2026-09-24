"""Registry per strumenti di gestione Calendario ed Eventi per l'Agent e le Automazioni.

Fornisce:
- calendar_list_calendars: elenca i calendari disponibili
- calendar_list_events: ricerca e visualizza eventi in un intervallo temporale
- calendar_get_event: recupera dettagli di un singolo evento per UID
- calendar_create_event: creazione di eventi con supporto ad alias, durate in linguaggio naturale,
                         batching automatico, deduplicazione intelligente e ancore Markdown cliccabili.
- calendar_update_event: aggiornamento di eventi esistenti
- calendar_delete_event: eliminazione di eventi con tracciamento tombstone
- calendar_check_availability: ricerca deterministica di slot orari liberi
"""

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import calendar_db
from registry.base import BaseToolRegistry

logger = logging.getLogger("registry.calendar")


def _parse_natural_duration(duration_str: str) -> Optional[int]:
    """Converte durate come '30m', '1h', '1h30m', '90min' in minuti interi."""
    if not duration_str or not isinstance(duration_str, str):
        return None
    d = duration_str.strip().lower()

    # Pattern tipo 1h30m o 1h 30min
    match_hm = re.match(r"^(\d+)\s*h(?:ours?|ore)?\s*(\d+)?\s*(?:m|min|minuti)?$", d)
    if match_hm:
        hours = int(match_hm.group(1))
        minutes = int(match_hm.group(2) or 0)
        return hours * 60 + minutes

    # Pattern solo ore: 2h o 2 hours
    match_h = re.match(r"^(\d+)\s*h(?:ours?|ore)?$", d)
    if match_h:
        return int(match_h.group(1)) * 60

    # Pattern solo minuti: 45m o 45min
    match_m = re.match(r"^(\d+)\s*(?:m|min|minuti|minutes?)$", d)
    if match_m:
        return int(match_m.group(1))

    # Pattern numerico puro (assunto minuti)
    if d.isdigit():
        return int(d)

    return None


def _normalize_iso_datetime(dt_str: str, default_date: Optional[date] = None) -> str:
    """Normalizza stringhe di data/ora in formato ISO-8601 YYYY-MM-DDTHH:MM:SS."""
    if not dt_str:
        return datetime.now().strftime("%Y-%m-%dT%H:%M:00")

    s = dt_str.strip()

    # Se è solo un orario HH:MM o HH:MM:SS
    if re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", s):
        ref_d = default_date or date.today()
        parts = s.split(":")
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(parts[2]) if len(parts) > 2 else 0
        return datetime(ref_d.year, ref_d.month, ref_d.day, hh, mm, ss).isoformat()

    # Se contiene ' ' al posto di 'T'
    if " " in s and "T" not in s:
        s = s.replace(" ", "T")

    # Rimuovi millisecondi o suffissi complessi se presenti
    return s


class CalendarRegistry(BaseToolRegistry):
    """Tool Registry per operazioni sul calendario locale e sincronizzato."""

    @property
    def name(self) -> str:
        return "calendar"

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "calendar_list_calendars",
                "description": "Elenca tutti i calendari disponibili nel sistema con ID, nome, colore, sorgente (locale, caldav, google) e conteggio eventi.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "calendar_list_events",
                "description": "Recupera la lista degli eventi dal calendario in un intervallo temporale specificato, con filtri opzionali per categoria o testo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_date": {
                            "type": "string",
                            "description": "Data/ora di inizio intervallo (ISO-8601 es. '2026-09-24' o '2026-09-24T00:00:00'). Se omesso, default a oggi.",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "Data/ora di fine intervallo (ISO-8601 es. '2026-10-01' o '2026-10-01T23:59:59'). Se omesso, default a +7 giorni.",
                        },
                        "calendar_id": {
                            "type": "string",
                            "description": "ID del calendario specifico da cui filtrare gli eventi (opzionale).",
                        },
                        "category": {
                            "type": "string",
                            "description": "Categoria evento (es. 'meeting', 'personal', 'homelab', 'flight', 'reminder').",
                        },
                        "query": {
                            "type": "string",
                            "description": "Termine di ricerca nel titolo, descrizione o luogo dell'evento.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Numero massimo di eventi da restituire (default 100).",
                            "default": 100,
                        },
                    },
                },
            },
            {
                "name": "calendar_get_event",
                "description": "Recupera i dettagli completi di un singolo evento specificando il suo identificatore univoco UID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event_id": {
                            "type": "string",
                            "description": "UID dell'evento da recuperare.",
                        },
                    },
                    "required": ["event_id"],
                },
            },
            {
                "name": "calendar_create_event",
                "description": "Crea uno o più eventi nel calendario con deduplicazione automatica e supporto a durate ed orari. Restituisce link Markdown cliccabile all'evento.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Titolo o riepilogo dell'evento (es. 'Riunione con Mario', 'Manutenzione Homelab Proxmox').",
                        },
                        "start_time": {
                            "type": "string",
                            "description": "Data e ora di inizio (ISO-8601, es. '2026-09-24T15:00:00'). Accetta anche alias 'dtstart' o 'when'.",
                        },
                        "end_time": {
                            "type": "string",
                            "description": "Data e ora di fine (ISO-8601, es. '2026-09-24T16:00:00'). Se omesso, viene calcolato dalla durata.",
                        },
                        "duration": {
                            "type": "string",
                            "description": "Durata dell'evento (es. '30m', '1h', '1h30m'). Default 1 ora se non specificato né end_time.",
                        },
                        "location": {
                            "type": "string",
                            "description": "Luogo fisico o link a meeting virtuale (es. Google Meet, Zoom, Microsoft Teams).",
                        },
                        "description": {
                            "type": "string",
                            "description": "Note, ordine del giorno, PIN o dettagli aggiuntivi dell'evento.",
                        },
                        "category": {
                            "type": "string",
                            "description": "Categoria dell'evento (default 'meeting'). Opzioni: 'meeting', 'personal', 'homelab', 'flight', 'reminder'.",
                            "default": "meeting",
                        },
                        "calendar_id": {
                            "type": "string",
                            "description": "ID del calendario in cui creare l'evento. Se omesso, usa il calendario predefinito.",
                        },
                        "all_day": {
                            "type": "boolean",
                            "description": "Se True indica un evento che dura l'intera giornata (es. compleanni, ferie).",
                            "default": False,
                        },
                        "reminder_minutes": {
                            "type": "integer",
                            "description": "Minuti di anticipo per la notifica o promemoria (es. 15, 60).",
                        },
                        "events": {
                            "type": "array",
                            "description": "Lista di eventi multipli da creare in batch (supporta output massivo da email o estrazioni complesse).",
                            "items": {"type": "object"},
                        },
                    },
                },
            },
            {
                "name": "calendar_update_event",
                "description": "Modifica un evento esistente specificandone l'UID e i campi da aggiornare.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event_id": {
                            "type": "string",
                            "description": "UID dell'evento da modificare.",
                        },
                        "summary": {"type": "string", "description": "Nuovo titolo dell'evento"},
                        "start_time": {"type": "string", "description": "Nuova data/ora di inizio"},
                        "end_time": {"type": "string", "description": "Nuova data/ora di fine"},
                        "location": {"type": "string", "description": "Nuovo luogo o link virtuale"},
                        "description": {"type": "string", "description": "Nuova descrizione o note"},
                        "category": {"type": "string", "description": "Nuova categoria"},
                        "status": {"type": "string", "description": "Stato ('confirmed', 'tentative', 'cancelled')"},
                    },
                    "required": ["event_id"],
                },
            },
            {
                "name": "calendar_delete_event",
                "description": "Elimina un evento dal calendario dato il suo UID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "event_id": {
                            "type": "string",
                            "description": "UID dell'evento da eliminare.",
                        },
                    },
                    "required": ["event_id"],
                },
            },
            {
                "name": "calendar_check_availability",
                "description": "Verifica gli slot orari liberi disponibili per una determinata giornata lavorativa per pianificare nuove call o impegni.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Data da verificare in formato 'YYYY-MM-DD' (default a oggi se omessa).",
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "description": "Durata minima desiderata per lo slot in minuti (default 30 min).",
                            "default": 30,
                        },
                        "start_hour": {
                            "type": "integer",
                            "description": "Ora inizio orario di lavoro (default 9 = 09:00).",
                            "default": 9,
                        },
                        "end_hour": {
                            "type": "integer",
                            "description": "Ora fine orario di lavoro (default 18 = 18:00).",
                            "default": 18,
                        },
                        "calendar_id": {
                            "type": "string",
                            "description": "Filtra la disponibilità su uno specifico calendario (opzionale).",
                        },
                    },
                },
            },
            {
                "name": "calendar_create_calendar",
                "description": "Crea un nuovo calendario (es. 'Lavoro', 'Palestra', 'Progetto Homelab') specificando nome, colore esadecimale e descrizione.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Nome del nuovo calendario.",
                        },
                        "color": {
                            "type": "string",
                            "description": "Colore esadecimale (es. '#10b981', '#f59e0b', '#3b82f6'). Default '#3b82f6'.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Descrizione facoltativa dello scopo del calendario.",
                        },
                    },
                    "required": ["name"],
                },
            },
            {
                "name": "calendar_update_calendar",
                "description": "Modifica o rinomina un calendario esistente (nome, colore o visibilità).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "calendar_id": {
                            "type": "string",
                            "description": "ID o nome del calendario da modificare.",
                        },
                        "name": {
                            "type": "string",
                            "description": "Nuovo nome del calendario (opzionale).",
                        },
                        "color": {
                            "type": "string",
                            "description": "Nuovo colore esadecimale (opzionale).",
                        },
                        "is_visible": {
                            "type": "boolean",
                            "description": "Visibilità del calendario (opzionale).",
                        },
                    },
                    "required": ["calendar_id"],
                },
            },
            {
                "name": "calendar_delete_calendar",
                "description": "Elimina un calendario e tutti i suoi eventi associati.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "calendar_id": {
                            "type": "string",
                            "description": "ID o nome del calendario da eliminare.",
                        },
                    },
                    "required": ["calendar_id"],
                },
            },
            {
                "name": "calendar_import_feed",
                "description": "Sottoscrive o importa un feed esterno iCal o Google Calendar tramite URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL del feed (es. indirizzo segreto iCal di Google Calendar https://calendar.google.com/calendar/ical/.../basic.ics o webcal://).",
                        },
                        "name": {
                            "type": "string",
                            "description": "Nome da assegnare al calendario (opzionale).",
                        },
                        "color": {
                            "type": "string",
                            "description": "Colore esadecimale (opzionale).",
                        },
                    },
                    "required": ["url"],
                },
            },
        ]

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        try:
            if tool_name == "calendar_list_calendars":
                return self._list_calendars()
            elif tool_name == "calendar_create_calendar":
                return self._create_calendar(args)
            elif tool_name == "calendar_update_calendar":
                return self._update_calendar(args)
            elif tool_name == "calendar_delete_calendar":
                return self._delete_calendar(args)
            elif tool_name == "calendar_import_feed":
                return self._import_feed(args)
            elif tool_name == "calendar_list_events":
                return self._list_events(args)
            elif tool_name == "calendar_get_event":
                return self._get_event(args)
            elif tool_name == "calendar_create_event":
                return self._create_event(args)
            elif tool_name == "calendar_update_event":
                return self._update_event(args)
            elif tool_name == "calendar_delete_event":
                return self._delete_event(args)
            elif tool_name == "calendar_check_availability":
                return self._check_availability(args)
            else:
                return {"error": f"Tool '{tool_name}' non gestito dal registry calendar"}
        except Exception as e:
            logger.error(f"Errore esecuzione tool '{tool_name}': {e}", exc_info=True)
            return {"error": f"Errore interno calendar: {str(e)}"}

    def _list_calendars(self) -> Dict[str, Any]:
        cals = calendar_db.list_calendars()
        return {
            "status": "success",
            "count": len(cals),
            "calendars": cals,
        }

    def _find_calendar_id(self, cal_id_or_name: str) -> Optional[str]:
        if not cal_id_or_name:
            return None
        cals = calendar_db.list_calendars()
        for c in cals:
            if c["id"] == cal_id_or_name or c["name"].lower() == cal_id_or_name.lower():
                return c["id"]
        return None

    def _create_calendar(self, args: Dict[str, Any]) -> Dict[str, Any]:
        name = args.get("name", "").strip()
        if not name:
            return {"error": "Nome calendario obbligatorio"}
        color = args.get("color") or "#3b82f6"
        desc = args.get("description", "")
        cal = calendar_db.create_calendar({
            "name": name,
            "color": color,
            "description": desc,
            "source": "local",
            "is_visible": True,
            "is_read_only": False,
        })
        return {
            "status": "created",
            "calendar": cal,
            "message": f"Calendario '{name}' creato con successo (ID: {cal['id']})."
        }

    def _update_calendar(self, args: Dict[str, Any]) -> Dict[str, Any]:
        cal_id_or_name = args.get("calendar_id", "").strip()
        target_id = self._find_calendar_id(cal_id_or_name)
        if not target_id:
            return {"error": f"Calendario '{cal_id_or_name}' non trovato"}
        updates: Dict[str, Any] = {}
        if "name" in args and args["name"]:
            updates["name"] = args["name"].strip()
        if "color" in args and args["color"]:
            updates["color"] = args["color"].strip()
        if "is_visible" in args:
            updates["is_visible"] = bool(args["is_visible"])
        cal = calendar_db.update_calendar(target_id, updates)
        return {
            "status": "updated",
            "calendar": cal,
            "message": f"Calendario '{target_id}' aggiornato con successo."
        }

    def _delete_calendar(self, args: Dict[str, Any]) -> Dict[str, Any]:
        cal_id_or_name = args.get("calendar_id", "").strip()
        target_id = self._find_calendar_id(cal_id_or_name)
        if not target_id:
            return {"error": f"Calendario '{cal_id_or_name}' non trovato"}
        cals = calendar_db.list_calendars()
        if len(cals) <= 1:
            return {"error": "Impossibile eliminare l'unico calendario rimasto nel sistema."}
        deleted = calendar_db.delete_calendar(target_id)
        return {
            "status": "deleted" if deleted else "not_found",
            "calendar_id": target_id,
            "message": f"Calendario '{cal_id_or_name}' eliminato con successo." if deleted else "Errore eliminazione."
        }

    def _import_feed(self, args: Dict[str, Any]) -> Dict[str, Any]:
        url = args.get("url", "").strip()
        if not url:
            return {"error": "URL feed obbligatorio"}
        import calendar_sync
        provider = "google" if "google.com" in url.lower() else "webcal"
        name = args.get("name") or ("Google Calendar" if provider == "google" else "Feed Sottoscritto")
        color = args.get("color") or ("#4285f4" if provider == "google" else "#06b6d4")
        cal = calendar_db.create_calendar({
            "name": name,
            "color": color,
            "source": provider,
            "sync_url": url,
            "is_visible": True,
            "is_read_only": False,
        })
        sync_res = calendar_sync.fetch_and_sync_ical_feed(url, calendar_id=cal["id"])
        return {
            "status": "success",
            "calendar": calendar_db.get_calendar(cal["id"]),
            "synced_events": sync_res.get("synced_count", 0),
            "message": f"Feed importato con successo nel calendario '{name}': {sync_res.get('synced_count', 0)} eventi sincronizzati."
        }

    def _list_events(self, args: Dict[str, Any]) -> Dict[str, Any]:
        now = datetime.now()
        start_d = args.get("start_date") or now.strftime("%Y-%m-%d")
        end_d = args.get("end_date") or (now + timedelta(days=7)).strftime("%Y-%m-%d")

        # Assicura formato con timestamp se è solo data YYYY-MM-DD
        if len(start_d) == 10:
            start_d += "T00:00:00"
        if len(end_d) == 10:
            end_d += "T23:59:59"

        cal_id = args.get("calendar_id")
        cal_ids = [cal_id] if cal_id else None
        category = args.get("category")
        query = args.get("query")
        limit = int(args.get("limit", 100))

        events = calendar_db.list_events(
            start_dt=start_d,
            end_dt=end_d,
            calendar_ids=cal_ids,
            category=category,
            query=query,
            limit=limit,
        )

        return {
            "status": "success",
            "range": {"start": start_d, "end": end_d},
            "count": len(events),
            "events": events,
        }

    def _get_event(self, args: Dict[str, Any]) -> Dict[str, Any]:
        uid = args.get("event_id") or args.get("uid")
        if not uid:
            return {"error": "Parametro 'event_id' obbligatorio"}

        ev = calendar_db.get_event(uid)
        if not ev:
            return {"status": "not_found", "error": f"Evento {uid} non trovato"}

        return {"status": "success", "event": ev}

    def _create_single_event(self, item: Dict[str, Any]) -> Dict[str, Any]:
        summary = item.get("summary") or item.get("title") or "Nuovo Evento"

        # Tolleranza alias per start_time
        start_raw = item.get("start_time") or item.get("dtstart") or item.get("start") or item.get("when")
        dtstart = _normalize_iso_datetime(start_raw)

        # Gestione end_time e duration
        end_raw = item.get("end_time") or item.get("dtend") or item.get("end")
        duration_raw = item.get("duration")

        if end_raw:
            dtend = _normalize_iso_datetime(end_raw)
        else:
            duration_mins = _parse_natural_duration(duration_raw) or 60
            try:
                s_dt = datetime.fromisoformat(dtstart.replace("Z", "").split("+")[0])
                dtend = (s_dt + timedelta(minutes=duration_mins)).isoformat()
            except Exception:
                dtend = dtstart

        cal_id = item.get("calendar_id")

        # Deduplicazione automatica intelligente
        existing = calendar_db.find_existing_event(
            summary=summary,
            dtstart=dtstart,
            calendar_id=cal_id,
        )
        if existing:
            uid = existing["uid"]
            return {
                "status": "already_exists",
                "uid": uid,
                "summary": summary,
                "dtstart": dtstart,
                "dtend": existing.get("dtend"),
                "markdown_link": f"[{summary}](#event-{uid})",
                "message": f"Evento già presente nel calendario: [{summary}](#event-{uid}) ({dtstart})",
                "duplicate": True,
            }

        # Salvataggio nuovo evento
        ev_data = {
            "calendar_id": cal_id,
            "summary": summary,
            "description": item.get("description", ""),
            "location": item.get("location", ""),
            "dtstart": dtstart,
            "dtend": dtend,
            "all_day": bool(item.get("all_day", False)),
            "category": item.get("category", "meeting"),
            "importance": item.get("importance", "normal"),
            "reminder_minutes": item.get("reminder_minutes"),
            "source_type": item.get("source_type", "agent"),
            "source_id": item.get("source_id"),
        }

        created = calendar_db.save_event(ev_data)
        uid = created["uid"]

        return {
            "status": "created",
            "uid": uid,
            "event": created,
            "summary": summary,
            "dtstart": dtstart,
            "dtend": dtend,
            "location": created.get("location", ""),
            "markdown_link": f"[{summary}](#event-{uid})",
            "message": f"Evento creato con successo: [{summary}](#event-{uid}) per {dtstart}",
            "duplicate": False,
        }

    def _create_event(self, args: Dict[str, Any]) -> Dict[str, Any]:
        # Supporto batching automatico se viene fornita una lista di eventi
        events_batch = args.get("events")
        if isinstance(events_batch, list) and events_batch:
            created_list = []
            duplicate_count = 0
            for item in events_batch:
                res = self._create_single_event(item)
                if res.get("duplicate"):
                    duplicate_count += 1
                created_list.append(res)
            return {
                "status": "batch_completed",
                "total": len(created_list),
                "created_count": len(created_list) - duplicate_count,
                "duplicates_count": duplicate_count,
                "results": created_list,
            }

        # Creazione singolo evento
        return self._create_single_event(args)

    def _update_event(self, args: Dict[str, Any]) -> Dict[str, Any]:
        uid = args.get("event_id") or args.get("uid")
        if not uid:
            return {"error": "Parametro 'event_id' obbligatorio"}

        existing = calendar_db.get_event(uid)
        if not existing:
            return {"status": "not_found", "error": f"Evento {uid} non trovato"}

        update_dict = dict(existing)
        if "summary" in args:
            update_dict["summary"] = args["summary"]
        if "start_time" in args or "dtstart" in args:
            update_dict["dtstart"] = _normalize_iso_datetime(args.get("start_time") or args.get("dtstart"))
        if "end_time" in args or "dtend" in args:
            update_dict["dtend"] = _normalize_iso_datetime(args.get("end_time") or args.get("dtend"))
        if "location" in args:
            update_dict["location"] = args["location"]
        if "description" in args:
            update_dict["description"] = args["description"]
        if "category" in args:
            update_dict["category"] = args["category"]
        if "status" in args:
            update_dict["status"] = args["status"]

        updated = calendar_db.save_event(update_dict)
        return {
            "status": "updated",
            "uid": uid,
            "summary": updated["summary"],
            "dtstart": updated["dtstart"],
            "dtend": updated["dtend"],
            "message": f"Evento [{updated['summary']}](#event-{uid}) aggiornato con successo.",
        }

    def _delete_event(self, args: Dict[str, Any]) -> Dict[str, Any]:
        uid = args.get("event_id") or args.get("uid")
        if not uid:
            return {"error": "Parametro 'event_id' obbligatorio"}

        existing = calendar_db.get_event(uid)
        if not existing:
            return {"status": "not_found", "error": f"Evento {uid} non trovato"}

        deleted = calendar_db.delete_event(uid)
        if deleted:
            return {
                "status": "deleted",
                "uid": uid,
                "summary": existing.get("summary"),
                "message": f"Evento '{existing.get('summary')}' rimosso dal calendario.",
            }
        return {"status": "error", "error": f"Impossibile eliminare l'evento {uid}"}

    def _check_availability(self, args: Dict[str, Any]) -> Dict[str, Any]:
        target_date = args.get("date") or datetime.now().strftime("%Y-%m-%d")
        duration_minutes = int(args.get("duration_minutes", 30))
        start_hour = int(args.get("start_hour", 9))
        end_hour = int(args.get("end_hour", 18))
        cal_id = args.get("calendar_id")
        cal_ids = [cal_id] if cal_id else None

        slots = calendar_db.find_free_slots(
            target_date=target_date,
            duration_minutes=duration_minutes,
            start_hour=start_hour,
            end_hour=end_hour,
            calendar_ids=cal_ids,
        )

        return {
            "status": "success",
            "date": target_date,
            "work_hours": f"{start_hour:02d}:00 - {end_hour:02d}:00",
            "requested_duration_minutes": duration_minutes,
            "free_slots_count": len(slots),
            "free_slots": slots,
        }
