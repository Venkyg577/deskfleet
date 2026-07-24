#!/usr/bin/env python3
"""Run the labeled eval dataset through the graph and print a scorecard.

Usage:
    # Full run, needs LLM_PROVIDER=openai and a key in .env
    python scripts/run_eval.py

    # Guardrail-only subset, deterministic, no network or key
    LLM_PROVIDER=fake STORE_API_OFFLINE=1 python scripts/run_eval.py --subset refuse

    # Write a JSON report alongside the printed scorecard
    python scripts/run_eval.py --report tests/eval/report.json

The REFUSE subset short-circuits on the injection scan before any LLM call,
so it runs with no key and is what CI gates on. The full set needs a real
provider to produce a genuine decision-accuracy number.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.eval import evaluate, load_dataset

_DEFAULT_DATASET = Path(__file__).parent.parent / "tests" / "eval" / "dataset.jsonl"


def _filter(rows: list[dict], subset: str) -> list[dict]:
    if subset == "all":
        return rows
    if subset == "refuse":
        return [r for r in rows if r["expected_decision"] == "REFUSE"]
    raise ValueError(f"unknown subset: {subset}")


def _print_report(metrics: dict, provider: str, subset: str) -> None:
    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x * 100:.1f}%"

    print(f"\nDeskFleet eval  provider={provider}  subset={subset}  n={metrics['total']}")
    print("-" * 52)
    print(f"Decision accuracy : {pct(metrics['decision_accuracy'])} "
          f"({metrics['decision_correct']}/{metrics['total']})")
    print(f"Category accuracy : {pct(metrics['category_accuracy'])} "
          f"({metrics['category_correct']}/{metrics['category_scored']} scored)")
    print(f"Escalation rate   : {pct(metrics['escalation_rate'])} (predicted ESCALATE)")
    print("\nPer expected decision:")
    for d, s in metrics["per_path"].items():
        if s["count"]:
            print(f"  {d:9s} {pct(s['accuracy']):>6s}  ({s['correct']}/{s['count']})")
    print("\nConfusion (rows = expected, cols = predicted):")
    cols = ["RESOLVED", "ESCALATE", "REFUSE"]
    print("           " + "".join(f"{c:>10s}" for c in cols))
    for exp in cols:
        cells = "".join(f"{metrics['confusion'][exp][p]:>10d}" for p in cols)
        print(f"  {exp:8s}" + cells)

    misses = [r for r in metrics["results"] if not r["decision_ok"]]
    if misses:
        print(f"\nDecision misses ({len(misses)}):")
        for r in misses:
            print(f"  {r['id']:18s} expected {r['expected_decision']:9s} got {r['got_decision']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DeskFleet eval dataset.")
    parser.add_argument("--dataset", default=str(_DEFAULT_DATASET))
    parser.add_argument("--subset", choices=["all", "refuse"], default="all")
    parser.add_argument("--report", default=None, help="path to write a JSON report")
    args = parser.parse_args()

    provider = settings.LLM_PROVIDER
    subset = args.subset

    # The fake provider only produces valid outputs for the REFUSE path, which
    # never invokes the model. Force the refuse subset rather than crash.
    if provider == "fake" and subset == "all":
        print("provider=fake cannot score the LLM paths; restricting to --subset refuse",
              file=sys.stderr)
        subset = "refuse"

    rows = _filter(load_dataset(args.dataset), subset)
    metrics = evaluate(rows)
    _print_report(metrics, provider, subset)

    if args.report:
        payload = {"provider": provider, "subset": subset, **metrics}
        Path(args.report).write_text(json.dumps(payload, indent=2))
        print(f"wrote {args.report}")

    # Non-zero exit if any decision was wrong, so CI can gate on it.
    if metrics["decision_correct"] != metrics["total"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
