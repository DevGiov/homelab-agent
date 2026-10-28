"""Esecuzione delle suite per uno o più modelli e report.

Ogni modello esegue tutte le suite prima del successivo, così il server carica un modello alla volta. Il report
di un modello è un JSON in `data/evals/`; `compare` affianca l'ultimo report di ogni modello in una tabella
Markdown. Le chiamate LLM delle valutazioni finiscono tra le chiamate delle metriche (turn_key `eval:…`), ma non
tra i turni.
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from app.core.config import settings
from app.evals.suites import SUITES, Outcome, load_cases
from app.observability.report import percentile
from app.observability.turns import capture_llm_calls

logger = logging.getLogger("evals")


def reports_dir() -> Path:
    path = Path(settings.data_dir) / "evals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_case(run_fn: Callable[[Dict[str, Any], str], Outcome], case: Dict[str, Any], model: str, key: str) -> Dict[str, Any]:
    """Un'esecuzione di un caso: esito, durata e token. Un'eccezione conta come caso fallito."""
    start = time.monotonic()
    with capture_llm_calls(key) as trace:
        try:
            outcome = run_fn(case, model)
        except Exception as e:
            logger.warning(f"Caso '{case['id']}' interrotto: {e}")
            outcome = Outcome(False, f"errore: {str(e)[:200]}")
    return {
        "passed": outcome.passed,
        "skipped": outcome.skipped,
        "detail": outcome.detail,
        "duration_ms": int((time.monotonic() - start) * 1000),
        "llm_calls": trace.llm_calls,
        "prompt_tokens": trace.prompt_tokens,
        "completion_tokens": trace.completion_tokens,
    }


def summarize(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Accuratezza sulle esecuzioni valutabili, durata mediana e token di una suite."""
    runs = [r for c in cases for r in c["runs"] if not r["skipped"]]
    passed = sum(r["passed"] for r in runs)
    return {
        "cases": len(cases),
        "runs": len(runs),
        "passed": passed,
        "skipped": sum(1 for c in cases if all(r["skipped"] for r in c["runs"])),
        "accuracy": round(100 * passed / len(runs), 1) if runs else None,
        "p50_ms": percentile([r["duration_ms"] for r in runs], 0.5),
        "prompt_tokens": sum(r["prompt_tokens"] for r in runs),
        "completion_tokens": sum(r["completion_tokens"] for r in runs),
    }


def evaluate_model(
    model: str,
    suites: Iterable[str],
    repeat: int = 1,
    case_ids: Optional[List[str]] = None,
    progress: Callable[[str], None] = lambda _: None,
) -> Dict[str, Any]:
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%S")
    report: Dict[str, Any] = {"model": model, "started_at": started.isoformat(), "repeat": repeat, "suites": {}}
    for suite in suites:
        cases = []
        for case in load_cases(suite):
            if case_ids and case["id"] not in case_ids:
                continue
            runs = [run_case(SUITES[suite], case, model, f"eval:{run_id}:{suite}:{case['id']}") for _ in range(repeat)]
            cases.append({"id": case["id"], "runs": runs})
            mark = "–" if runs[0]["skipped"] else f"{sum(r['passed'] for r in runs)}/{repeat}"
            progress(f"[{model}] {suite}/{case['id']}: {mark} {runs[-1]['detail']}")
        report["suites"][suite] = {**summarize(cases), "results": cases}
    report["duration_s"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
    return report


def save_report(report: Dict[str, Any]) -> Path:
    safe_model = "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in report["model"])
    stamp = report["started_at"][:19].replace(":", "").replace("-", "")
    path = reports_dir() / f"{stamp}_{safe_model}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def latest_reports(paths: Optional[List[Path]] = None) -> List[Dict[str, Any]]:
    """I report indicati, o per ogni modello in `data/evals/` il risultato più recente di ogni suite (un'esecuzione
    parziale aggiorna solo le sue suite); `started_at` è quello dell'esecuzione più recente."""
    if paths:
        return [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    latest: Dict[str, Dict[str, Any]] = {}
    for path in sorted(reports_dir().glob("*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        merged = latest.setdefault(report["model"], {"model": report["model"], "suites": {}})
        merged["started_at"] = report["started_at"]
        merged["suites"].update(report["suites"])
    return list(latest.values())


def _cell(summary: Optional[Dict[str, Any]]) -> str:
    if not summary or summary["accuracy"] is None:
        return "—"
    seconds = (summary["p50_ms"] or 0) / 1000
    return f"{summary['accuracy']:.0f}% ({summary['passed']}/{summary['runs']}) · {seconds:.1f} s"


def compare_markdown(reports: List[Dict[str, Any]]) -> str:
    """Tabella suite × modello (accuratezza, esecuzioni superate, durata mediana) e casi falliti per modello."""
    if not reports:
        return "Nessun report di valutazione."
    suites = sorted({s for r in reports for s in r["suites"]}, key=lambda s: list(SUITES).index(s) if s in SUITES else 99)
    lines = [
        "| Suite | " + " | ".join(r["model"] for r in reports) + " |",
        "| :--- | " + " | ".join(":---" for _ in reports) + " |",
    ]
    for suite in suites:
        lines.append(f"| {suite} | " + " | ".join(_cell(r["suites"].get(suite)) for r in reports) + " |")
    lines.append("| **data** | " + " | ".join(r["started_at"][:16].replace("T", " ") for r in reports) + " |")
    for r in reports:
        failures = [
            f"- `{suite}/{c['id']}`: {next(run['detail'] for run in c['runs'] if not run['passed'] and not run['skipped'])}"
            for suite, s in r["suites"].items()
            for c in s["results"]
            if any(not run["passed"] and not run["skipped"] for run in c["runs"])
        ]
        lines += ["", f"**{r['model']}**: " + ("nessun caso fallito" if not failures else f"{len(failures)} casi falliti"), *failures]
    return "\n".join(lines)
