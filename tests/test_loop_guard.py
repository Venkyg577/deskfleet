import pytest
from langchain_core.messages import AIMessage

from app.graph.build import compile_graph
from app.graph.state import Classification, Review, TicketState
from app.llm import FakeLLM

_BASE_STATE: TicketState = {
    "ticket_id": "test-loop",
    "raw_ticket": "Where is my order?",
    "ticket": "Where is my order?",
    "order_id": None,
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
    "redactions": [],
    "node_latency_ms": {},
    "tokens": {"prompt": 0, "completion": 0},
}


@pytest.mark.timeout(15)
def test_loop_terminates_and_escalates_at_max_iters():
    """Reviewer always returns revise. Graph must terminate at MAX_ITERS with ESCALATE."""
    llm = FakeLLM(responses=[
        # classifier
        Classification(category="order", reason="order status query"),
        # researcher: empty AIMessage = no tool calls, exits immediately
        AIMessage(content="", tool_calls=[]),
        # responder iteration 1
        AIMessage(content="Your order is on its way."),
        # reviewer iteration 1: revise (iterations=1, below MAX_ITERS=2)
        Review(
            grounded=True, policy_ok=False, addresses_ticket=False,
            verdict="revise",
            issues=["Missing ETA", "Missing carrier name"],
            reason="Response lacks shipping details",
        ),
        # responder iteration 2
        AIMessage(content="Your order is on its way and will arrive soon."),
        # reviewer iteration 2: revise again (iterations=2, >= MAX_ITERS=2 -> cap breach)
        Review(
            grounded=True, policy_ok=False, addresses_ticket=False,
            verdict="revise",
            issues=["Still missing ETA"],
            reason="Still lacks shipping details",
        ),
    ])

    graph = compile_graph(llm=llm)
    final = graph.invoke(dict(_BASE_STATE))

    assert final["decision"] == "ESCALATE"
    assert final["iterations"] == 2
    assert final["escalation_reason"] is not None
    assert "max_review_iterations_reached" in final["escalation_reason"]
