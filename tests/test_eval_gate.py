"""CI gate: the labeled REFUSE tickets must all be caught by the guardrail.

This runs the eval harness on the REFUSE subset of tests/eval/dataset.jsonl.
Those tickets short-circuit on the injection scan before any LLM call, so the
gate is deterministic and needs no network or API key (LLM_PROVIDER=fake).

It is a regression guard: if someone weakens the injection patterns, a labeled
attack starts scoring RESOLVED instead of REFUSE and this test goes red before
the change can deploy.
"""

from pathlib import Path

import pytest

from app.eval import evaluate, load_dataset

_DATASET = Path(__file__).parent / "eval" / "dataset.jsonl"


@pytest.fixture(scope="module")
def refuse_rows() -> list[dict]:
    rows = [r for r in load_dataset(_DATASET) if r["expected_decision"] == "REFUSE"]
    assert rows, "no REFUSE rows found in the eval dataset"
    return rows


def test_all_labeled_injections_are_refused(refuse_rows: list[dict]) -> None:
    metrics = evaluate(refuse_rows)
    assert metrics["decision_accuracy"] == 1.0, (
        "guardrail missed a labeled injection: "
        f"{[r['id'] for r in metrics['results'] if not r['decision_ok']]}"
    )


def test_refuse_subset_makes_no_llm_calls(refuse_rows: list[dict]) -> None:
    # Every REFUSE row must short-circuit before the graph. If any row reached
    # the graph, the fake LLM (empty response queue) would raise IndexError.
    metrics = evaluate(refuse_rows)
    assert all(not r["got_category"] for r in metrics["results"])
    assert metrics["per_path"]["REFUSE"]["count"] == len(refuse_rows)
