#!/usr/bin/env python3
"""Run a single support ticket through the graph without HTTP.

Usage:
    python scripts/run_ticket.py "<ticket text>" [order_id]

Prints the final state as formatted JSON.
"""

import json
import sys
import uuid
from pathlib import Path

# Ensure project root is on the path when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.graph.build import compile_graph
from app.graph.state import TicketState
from app.guardrails import scan_input


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_ticket.py '<ticket text>' [order_id]")
        sys.exit(1)

    raw_ticket = sys.argv[1]
    explicit_order_id = sys.argv[2] if len(sys.argv) > 2 else None

    scan = scan_input(raw_ticket, explicit_order_id)

    if scan["is_injection"]:
        print(json.dumps({
            "ticket_id": str(uuid.uuid4()),
            "decision": "REFUSE",
            "reply": "This request cannot be processed.",
            "category": None,
            "tool_calls": [],
            "iterations": 0,
            "escalation_reason": None,
            "node_latency_ms": {},
            "tokens": {"prompt": 0, "completion": 0},
        }, indent=2))
        return

    ticket_id = str(uuid.uuid4())
    initial_state: TicketState = {
        "ticket_id": ticket_id,
        "raw_ticket": raw_ticket,
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

    graph = compile_graph()
    final = graph.invoke(initial_state)

    output = {
        "ticket_id": final["ticket_id"],
        "decision": final["decision"],
        "category": final["category"],
        "category_reason": final["category_reason"],
        "reply": final["draft"],
        "tool_calls": [
            {
                "name": tc["name"],
                "args": tc["args"],
                "ok": tc["ok"],
                "latency_ms": tc["latency_ms"],
            }
            for tc in final["tool_calls"]
        ],
        "facts_count": len(final["facts"]),
        "iterations": final["iterations"],
        "escalation_reason": final.get("escalation_reason"),
        "node_latency_ms": final["node_latency_ms"],
        "tokens": final["tokens"],
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
