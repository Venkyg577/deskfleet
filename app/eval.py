"""Offline evaluation harness for the ticket graph.

Runs a labeled dataset through the same pipeline the API uses (scan_input +
compiled graph) and scores predicted decisions against expected ones. The
headline metric is decision accuracy across RESOLVED / ESCALATE / REFUSE.

REFUSE tickets short-circuit on the injection scan before any LLM call, so
they are fully deterministic and need no network or API key. Everything else
needs a real provider (LLM_PROVIDER=openai). See scripts/run_eval.py.
"""

import json
import time
from pathlib import Path
from typing import Any

from app.graph.build import compile_graph
from app.graph.state import TicketState
from app.guardrails import scan_input

DECISIONS = ("RESOLVED", "ESCALATE", "REFUSE")


def load_dataset(path: str | Path) -> list[dict]:
    """Read a JSONL dataset, one ticket object per line."""
    rows: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _initial_state(row: dict, scan: dict) -> TicketState:
    return {
        "ticket_id": row["id"],
        "raw_ticket": row["ticket"],
        "ticket": scan["sanitized"],
        "order_id": scan["order_id"],
        "category": "",
        "category_reason": "",
        "facts": [],
        "tool_calls": [],
        "draft": "",
        "review_verdict": None,
        "review_issues": [],
        "iterations": 0,
        "decision": None,
        "escalation_reason": None,
        "redactions": scan["redaction_types"],
        "node_latency_ms": {},
        "tokens": {"prompt": 0, "completion": 0},
    }


def predict(row: dict, graph: Any = None) -> dict:
    """Run one ticket through the pipeline and return the predicted outcome.

    Injection tickets short-circuit to REFUSE without touching the graph. For
    anything else, pass a compiled graph in to avoid recompiling per row.
    """
    scan = scan_input(row["ticket"], row.get("order_id"))
    if scan["is_injection"]:
        return {"decision": "REFUSE", "category": None, "ran_graph": False}

    if graph is None:
        graph = compile_graph()
    final = graph.invoke(_initial_state(row, scan))
    return {
        "decision": final["decision"],
        "category": final["category"],
        "ran_graph": True,
    }


def evaluate(rows: list[dict]) -> dict:
    """Score every row and return a metrics dict plus per-row detail."""
    # Compile once up front. Building the graph never calls the model, so this
    # is safe even under the fake provider; only invoking it (on non-refuse
    # rows) would need a real LLM.
    graph = compile_graph()

    results: list[dict] = []
    confusion: dict[str, dict[str, int]] = {d: {p: 0 for p in DECISIONS} for d in DECISIONS}

    for row in rows:
        start = time.perf_counter()
        pred = predict(row, graph)
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        expected = row["expected_decision"]
        got = pred["decision"]
        decision_ok = got == expected
        if expected in confusion and got in confusion[expected]:
            confusion[expected][got] += 1

        exp_cat = row.get("expected_category")
        category_ok: bool | None = None
        if exp_cat is not None and got != "REFUSE":
            category_ok = pred["category"] == exp_cat

        results.append({
            "id": row["id"],
            "expected_decision": expected,
            "got_decision": got,
            "decision_ok": decision_ok,
            "expected_category": exp_cat,
            "got_category": pred["category"],
            "category_ok": category_ok,
            "latency_ms": elapsed_ms,
        })

    total = len(results)
    decision_correct = sum(1 for r in results if r["decision_ok"])
    predicted_escalate = sum(1 for r in results if r["got_decision"] == "ESCALATE")

    per_path: dict[str, dict] = {}
    for d in DECISIONS:
        subset = [r for r in results if r["expected_decision"] == d]
        n = len(subset)
        c = sum(1 for r in subset if r["decision_ok"])
        per_path[d] = {"count": n, "correct": c, "accuracy": (c / n) if n else None}

    cat_rows = [r for r in results if r["category_ok"] is not None]
    cat_correct = sum(1 for r in cat_rows if r["category_ok"])

    return {
        "total": total,
        "decision_accuracy": (decision_correct / total) if total else None,
        "decision_correct": decision_correct,
        "per_path": per_path,
        "category_accuracy": (cat_correct / len(cat_rows)) if cat_rows else None,
        "category_scored": len(cat_rows),
        "category_correct": cat_correct,
        "escalation_rate": (predicted_escalate / total) if total else None,
        "confusion": confusion,
        "results": results,
    }
