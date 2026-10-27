"""Step di calendario: crea, elenca, aggiorna o elimina eventi direttamente sul DB del calendario."""
import logging
from typing import Any, Dict

from app.automations.steps.base import Outcome, StepContext, completed, failed
from app.automations.templating import resolve_parameters
from app.calendar import db as calendar_db

logger = logging.getLogger("automations.steps.calendar")

_EVENT_ID_KEYS = ("event_id", "uid", "id")


def _event_id(params: Dict[str, Any]):
    return next((params[k] for k in _EVENT_ID_KEYS if params.get(k)), None)


def _apply(action: str, params: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    if action in ("create", "create_event", "add_event"):
        ev = calendar_db.create_event(
            summary=params.get("summary", "Nuovo Evento"),
            start_time=params.get("dtstart") or params.get("start_time") or params.get("start") or "",
            end_time=params.get("dtend") or params.get("end_time") or params.get("end"),
            duration=params.get("duration"),
            description=params.get("description", ""),
            location=params.get("location", ""),
            calendar_id=params.get("calendar_id"),
            all_day=params.get("all_day", False),
            color=params.get("color"),
            source_type="automation",
            source_id=run_id,
        )
        return {"status": "created", "event": ev}
    if action in ("list", "list_events", "get_events", "search"):
        events = calendar_db.list_events(
            calendar_id=params.get("calendar_id"),
            start_after=params.get("start_after") or params.get("start_dt"),
            start_before=params.get("start_before") or params.get("end_dt"),
            query=params.get("query"),
            limit=params.get("limit", 50),
        )
        return {"status": "success", "count": len(events), "events": events}
    if action in ("delete", "delete_event"):
        event_id = _event_id(params)
        deleted = calendar_db.delete_event(event_id)
        return {"status": "success" if deleted else "not_found", "event_id": event_id}
    if action in ("update", "update_event"):
        ev = calendar_db.update_event(_event_id(params), **{k: v for k, v in params.items() if k not in _EVENT_ID_KEYS})
        return {"status": "success" if ev else "not_found", "event": ev}
    return {"status": "error", "error": f"Azione calendario sconosciuta: {action}"}


def run(ctx: StepContext) -> Outcome:
    params = resolve_parameters(ctx.step.parameters, ctx.data)
    action = ctx.step.action_or_tool or params.get("action", "create_event")
    action = action.removeprefix("calendar_").removeprefix("calendar.")

    if ctx.run.is_dry_run:
        return completed({"dry_run": True, "action": action, "parameters": params},
                         [{"tool_name": f"calendar_{action}", "args": params, "dry_run": True}])

    try:
        res = _apply(action, params, ctx.run.run_id)
    except Exception as e:
        logger.error(f"Errore esecuzione step calendario '{ctx.step.step_id}': {e}", exc_info=True)
        return failed(f"Errore esecuzione calendario: {e}", {"error": str(e)})
    return completed(res, [{"tool_name": f"calendar_{action}", "args": params, "result": res}])
