from langgraph.graph import END

from app.graph.state import TicketState


def route_after_review(state: TicketState) -> str:
    """Conditional edge after the Reviewer node (PRD section 7).

    The reviewer node already handles cap-breach and grounding failure by
    overriding verdict to 'escalate' before routing runs. So this function
    only sees three clean outcomes.
    """
    if state["review_verdict"] == "revise":
        return "responder"
    return END  # approve (RESOLVED) or escalate (ESCALATE)
