"""Valutazione dei modelli su routing, scelta dei tool, piani, rollback ed estrazione dei fatti.

    python -m app.evals run --models A,B [--suites routing,tools] [--repeat 3] [--cases id1,id2] [--interleaved on|off]
    python -m app.evals compare [report.json ...]

I modelli vanno sempre indicati: un processo separato non conosce il modello attivo nel backend. Ogni modello
viene caricato dal server LLM: indicare solo modelli che stanno nella VRAM disponibile.
"""
import argparse
import logging
import sys
from pathlib import Path

from app.evals.runner import compare_markdown, evaluate_model, latest_reports, save_report
from app.evals.suites import SUITES


def _split(value: str) -> list:
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.evals", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="esegue le suite e salva un report per modello in data/evals/")
    run.add_argument("--models", required=True, help="modelli separati da virgola")
    run.add_argument("--suites", default=",".join(SUITES), help=f"suite separate da virgola (default: {','.join(SUITES)})")
    run.add_argument("--repeat", type=int, default=1, help="esecuzioni per caso, per misurare la stabilità")
    run.add_argument("--cases", default="", help="solo questi id di caso")
    run.add_argument("--interleaved", choices=["auto", "on", "off"], default="auto",
                     help="pensiero dei passi precedenti nell'agent loop: dal profilo del modello o forzato (variante nel report)")
    compare = sub.add_parser("compare", help="tabella Markdown dei report (default: l'ultimo di ogni modello)")
    compare.add_argument("reports", nargs="*", type=Path)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if args.command == "compare":
        print(compare_markdown(latest_reports(args.reports)))
        return 0

    suites = _split(args.suites)
    unknown = [s for s in suites if s not in SUITES]
    if unknown:
        parser.error(f"suite sconosciute: {', '.join(unknown)}")

    from app.llm.providers import get_provider

    provider = get_provider()
    models = _split(args.models)
    available = provider.list_models()
    missing = [m for m in models if available and m not in available]
    if missing:
        parser.error(f"modelli non disponibili sul server: {', '.join(missing)}")

    from app.core.config import settings

    settings.agent_interleaved_thinking = args.interleaved
    variant = None if args.interleaved == "auto" else f"interleaved {args.interleaved}"
    reports = []
    for model in models:
        report = evaluate_model(model, suites, repeat=max(1, args.repeat), case_ids=_split(args.cases),
                                progress=lambda line: print(line, flush=True), variant=variant)
        path = save_report(report)
        print(f"Report salvato: {path} ({report['duration_s']} s)")
        reports.append(report)
    print()
    print(compare_markdown(reports))
    return 0


if __name__ == "__main__":
    sys.exit(main())
