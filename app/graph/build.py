from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.graph.nodes import make_classifier, make_researcher, make_responder, make_reviewer
from app.graph.routing import route_after_review
from app.graph.state import TicketState
from app.llm import get_llm


def compile_graph(llm: BaseChatModel | None = None):
    """Build and compile the LangGraph StateGraph.

    Pass llm explicitly in tests to inject a FakeLLM; omit for production
    (falls back to get_llm()).
    """
    if llm is None:
        llm = get_llm()

    builder = StateGraph(TicketState)
    builder.add_node("classifier", make_classifier(llm))
    builder.add_node("researcher", make_researcher(llm))
    builder.add_node("responder", make_responder(llm))
    builder.add_node("reviewer", make_reviewer(llm))

    builder.add_edge(START, "classifier")
    builder.add_edge("classifier", "researcher")
    builder.add_edge("researcher", "responder")
    builder.add_edge("responder", "reviewer")

    # Conditional edges from Reviewer: revise -> Responder, else -> END.
    # Cap breach and grounding failure are resolved inside the reviewer node
    # before routing runs, so route_after_review only sees approve or escalate
    # going to END, and revise going back to Responder.
    builder.add_conditional_edges(
        "reviewer",
        route_after_review,
        {"responder": "responder", END: END},
    )

    return builder.compile()
