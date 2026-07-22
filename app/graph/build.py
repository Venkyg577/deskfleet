from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.graph.nodes import make_classifier, make_researcher, make_responder, make_reviewer
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

    # Phase 4: linear spine only. Conditional edges added in Phase 5.
    builder.add_edge(START, "classifier")
    builder.add_edge("classifier", "researcher")
    builder.add_edge("researcher", "responder")
    builder.add_edge("responder", "reviewer")
    builder.add_edge("reviewer", END)

    return builder.compile()
