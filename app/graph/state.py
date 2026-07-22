from operator import add
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel

from app.tools.registry import ToolCall


def _merge(a: dict, b: dict) -> dict:
    return {**a, **b}


def _sum_tokens(a: dict, b: dict) -> dict:
    merged = dict(a)
    for k, v in b.items():
        merged[k] = merged.get(k, 0) + v
    return merged


class Fact(TypedDict):
    source: str   # tool name that produced it
    key: str      # e.g. "order.status"
    value: str


class TicketState(TypedDict):
    ticket_id: str
    raw_ticket: str              # audit log only, NEVER sent to a model
    ticket: str                  # sanitized, nodes read this
    order_id: str | None
    category: str
    category_reason: str
    facts: Annotated[list[Fact], add]
    tool_calls: Annotated[list[ToolCall], add]
    draft: str
    review_verdict: str | None   # approve | revise | escalate
    review_issues: list[str]
    iterations: int
    decision: str | None         # RESOLVED | ESCALATE | REFUSE
    escalation_reason: str | None
    redactions: list[str]        # types redacted, never the values
    node_latency_ms: Annotated[dict[str, int], _merge]
    tokens: Annotated[dict[str, int], _sum_tokens]


# ── Pydantic output models for structured LLM calls ───────────────────────────

class Classification(BaseModel):
    category: Literal["order", "product", "refund", "other"]
    reason: str


class Review(BaseModel):
    grounded: bool
    policy_ok: bool
    addresses_ticket: bool
    verdict: Literal["approve", "revise", "escalate"]
    issues: list[str]
    reason: str
