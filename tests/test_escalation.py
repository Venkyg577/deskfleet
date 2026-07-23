import pytest
from langchain_core.messages import AIMessage

from app.graph.build import compile_graph
from app.graph.state import Classification, Review, TicketState
from app.llm import FakeLLM


def _base_state(ticket: str, order_id: str | None) -> TicketState:
    return {
        "ticket_id": "test-esc",
        "raw_ticket": ticket,
        "ticket": ticket,
        "order_id": order_id,
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


def _order_tool_call(order_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "get_order_status",
            "args": {"order_id": order_id},
            "id": "call_1",
            "type": "tool_call",
        }],
    )


@pytest.mark.timeout(15)
def test_missing_order_forces_escalate_over_approve():
    """Order not found must ESCALATE even if the LLM reviewer says approve."""
    llm = FakeLLM(responses=[
        Classification(category="order", reason="order status"),
        _order_tool_call("99999"),          # researcher: look up unknown order
        AIMessage(content="", tool_calls=[]),  # researcher: exit loop
        AIMessage(content="I could not find order 99999."),  # responder
        Review(  # reviewer says approve, but the deterministic trigger overrides
            grounded=True, policy_ok=True, addresses_ticket=True,
            verdict="approve", issues=[], reason="looks fine",
        ),
    ])
    graph = compile_graph(llm=llm)
    final = graph.invoke(_base_state("Where is order 99999?", "99999"))

    assert final["decision"] == "ESCALATE"
    assert final["escalation_reason"] == "order_not_found"


@pytest.mark.timeout(15)
def test_human_request_forces_escalate_over_approve():
    """An explicit request for a human must ESCALATE even on an approve verdict."""
    llm = FakeLLM(responses=[
        Classification(category="order", reason="order status"),
        _order_tool_call("1"),              # researcher: look up a real order
        AIMessage(content="", tool_calls=[]),  # researcher: exit loop
        AIMessage(content="Your order 1 was delivered."),  # responder
        Review(
            grounded=True, policy_ok=True, addresses_ticket=True,
            verdict="approve", issues=[], reason="looks fine",
        ),
    ])
    graph = compile_graph(llm=llm)
    final = graph.invoke(
        _base_state("Where is order 1? I want to speak to a human agent.", "1")
    )

    assert final["decision"] == "ESCALATE"
    assert final["escalation_reason"] == "customer_requested_human"
