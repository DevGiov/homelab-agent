"""Metriche di esecuzione: riepilogo di una finestra, serie temporali per i grafici e ultimi turni."""
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import verify_api_key
from app.observability import report, store

router = APIRouter(prefix="/v1/metrics", tags=["metrics"], dependencies=[Depends(verify_api_key)])

# Finestra massima: la conservazione predefinita è di 30 giorni
Hours = Query(24, gt=0, le=24 * 30)


@router.get("/summary")
def get_summary(hours: float = Hours) -> Dict[str, Any]:
    return report.summary(hours)


@router.get("/timeseries")
def get_timeseries(hours: float = Hours, buckets: int = Query(48, ge=2, le=200)) -> Dict[str, Any]:
    return report.timeseries(hours, buckets)


@router.get("/turns")
def get_turns(
    limit: int = Query(50, ge=1, le=500),
    source: Optional[Literal["chat", "automation"]] = None,
) -> List[Dict[str, Any]]:
    return store.latest_turns(limit, source)
