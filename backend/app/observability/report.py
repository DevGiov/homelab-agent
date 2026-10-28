"""Aggregazioni delle metriche per la dashboard: riepilogo di una finestra temporale e serie a intervalli."""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from app.observability import store
from app.security import audit_log


def percentile(values: List[float], q: float) -> Optional[float]:
    """Percentile per rango più vicino; None se non ci sono valori."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]


def rate(tokens: int, ms: int) -> Optional[float]:
    """Token al secondo, None se manca il tempo."""
    return round(tokens * 1000 / ms, 1) if ms else None


def _llm_speeds(calls: Iterable[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """Velocità di prompt (solo token nuovi, la cache non costa) e di generazione sulle chiamate con i tempi di llama.cpp."""
    timed = [c for c in calls if c["prompt_ms"] is not None]
    new_prompt = sum(c["prompt_tokens"] - c["cached_tokens"] for c in timed)
    prompt_total = sum(c["prompt_tokens"] for c in timed)
    return {
        "prompt_tok_s": rate(new_prompt, sum(c["prompt_ms"] for c in timed)),
        "gen_tok_s": rate(sum(c["completion_tokens"] for c in timed), sum(c["completion_ms"] or 0 for c in timed)),
        "cache_hit_pct": round(100 * sum(c["cached_tokens"] for c in timed) / prompt_total, 1) if prompt_total else None,
    }


def _turns_block(turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    durations = [t["duration_ms"] for t in turns]
    by_status: Dict[str, int] = defaultdict(int)
    by_source: Dict[str, int] = defaultdict(int)
    for t in turns:
        by_status[t["status"]] += 1
        by_source[t["source"]] += 1
    return {
        "total": len(turns),
        "by_status": dict(by_status),
        "by_source": dict(by_source),
        "p50_ms": percentile(durations, 0.5),
        "p95_ms": percentile(durations, 0.95),
        "max_ms": max(durations) if durations else None,
        "tool_calls": sum(t["tool_calls"] for t in turns),
        "tool_errors": sum(t["tool_errors"] for t in turns),
    }


def _health_block(samples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_service: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in samples:
        by_service[s["service"]].append(s)
    result = []
    for service, rows in sorted(by_service.items()):
        last = rows[-1]
        latencies = [r["latency_ms"] for r in rows if r["ok"] and r["latency_ms"] is not None]
        result.append(
            {
                "service": service,
                "samples": len(rows),
                "uptime_pct": round(100 * sum(r["ok"] for r in rows) / len(rows), 1),
                "ok": bool(last["ok"]),
                "last_error": last["error"],
                "last_checked": last["ts"],
                "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
            }
        )
    return result


def summary(hours: float) -> Dict[str, Any]:
    since = store.since_iso(hours)
    turns = store.select("SELECT * FROM turns WHERE ts >= ? ORDER BY ts", (since,))
    calls = store.select("SELECT * FROM llm_calls WHERE ts >= ? ORDER BY ts", (since,))
    samples = store.select("SELECT * FROM health_samples WHERE ts >= ? ORDER BY ts", (since,))

    by_model: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in calls:
        by_model[c["model"] or "?"].append(c)
    models = [
        {
            "model": model,
            "calls": len(rows),
            "errors": sum(1 for r in rows if r["error"]),
            "p50_ms": percentile([r["duration_ms"] for r in rows], 0.5),
            "completion_tokens": sum(r["completion_tokens"] for r in rows),
            **_llm_speeds(rows),
        }
        for model, rows in sorted(by_model.items(), key=lambda item: -len(item[1]))
    ]

    return {
        "window_hours": hours,
        "turns": _turns_block(turns),
        "llm": {
            "calls": len(calls),
            "errors": sum(1 for c in calls if c["error"]),
            "prompt_tokens": sum(c["prompt_tokens"] for c in calls),
            "cached_tokens": sum(c["cached_tokens"] for c in calls),
            "completion_tokens": sum(c["completion_tokens"] for c in calls),
            **_llm_speeds(calls),
        },
        "models": models,
        "tools": audit_log.tool_stats(since)[:15],
        "health": _health_block(samples),
    }


def _bucket_index(ts: str, start: datetime, size: timedelta, count: int) -> int:
    return min(count - 1, max(0, int((datetime.fromisoformat(ts) - start) / size)))


def timeseries(hours: float, buckets: int) -> Dict[str, Any]:
    """Turni, chiamate LLM e salute dei servizi in `buckets` intervalli uguali sulla finestra."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    size = (end - start) / buckets
    since = start.isoformat()

    turn_groups: List[List[Dict[str, Any]]] = [[] for _ in range(buckets)]
    for t in store.select("SELECT * FROM turns WHERE ts >= ?", (since,)):
        turn_groups[_bucket_index(t["ts"], start, size, buckets)].append(t)
    call_groups: List[List[Dict[str, Any]]] = [[] for _ in range(buckets)]
    for c in store.select("SELECT * FROM llm_calls WHERE ts >= ?", (since,)):
        call_groups[_bucket_index(c["ts"], start, size, buckets)].append(c)

    health: Dict[str, List[Dict[str, Any]]] = {}
    for s in store.select("SELECT * FROM health_samples WHERE ts >= ?", (since,)):
        series = health.setdefault(s["service"], [{"samples": 0, "ok": 0, "latency": []} for _ in range(buckets)])
        point = series[_bucket_index(s["ts"], start, size, buckets)]
        point["samples"] += 1
        point["ok"] += s["ok"]
        if s["ok"] and s["latency_ms"] is not None:
            point["latency"].append(s["latency_ms"])

    points = []
    for i in range(buckets):
        turns, calls = turn_groups[i], call_groups[i]
        points.append(
            {
                "start": (start + size * i).isoformat(),
                "turns": len(turns),
                "errors": sum(1 for t in turns if t["status"] == "error"),
                "stopped": sum(1 for t in turns if t["status"] == "stopped"),
                "p50_ms": percentile([t["duration_ms"] for t in turns], 0.5),
                "tool_errors": sum(t["tool_errors"] for t in turns),
                "llm_calls": len(calls),
                **_llm_speeds(calls),
            }
        )
    return {
        "window_hours": hours,
        "bucket_minutes": round(size.total_seconds() / 60, 1),
        "points": points,
        "health": {
            service: [
                {
                    "uptime_pct": round(100 * p["ok"] / p["samples"], 1) if p["samples"] else None,
                    "avg_latency_ms": round(sum(p["latency"]) / len(p["latency"])) if p["latency"] else None,
                }
                for p in series
            ]
            for service, series in sorted(health.items())
        },
    }
