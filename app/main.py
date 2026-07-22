import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import PRICE_TABLE, settings
from app.graph.build import compile_graph
from app.graph.state import TicketState
from app.guardrails import scan_input
from app.guardrails.pii import redact
from app.metrics import (
    cost_usd_total, node_latency_seconds, review_iterations,
    ticket_latency_seconds, tickets_total, tokens_total,
)
from app.store import get_ticket, init_db, save_ticket, save_tool_calls

log = logging.getLogger(__name__)

_graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph
    init_db()
    _graph = compile_graph()
    log.info("graph compiled, service ready")
    yield


app = FastAPI(title="DeskFleet", version="1.0.0", lifespan=lifespan)


# ── Request / response models ──────────────────────────────────────────────────

class ResolveRequest(BaseModel):
    ticket: str = Field(min_length=1, max_length=4000)
    order_id: str | None = None
    ticket_id: str | None = None


class ResolveResponse(BaseModel):
    ticket_id: str
    decision: str
    category: str | None
    reply: str
    tool_calls: list[dict]
    iterations: int
    escalation_reason: str | None
    langsmith_trace_url: str | None
    latency_ms: int
    tokens: dict[str, int]
    cost_usd: float


# ── Helpers ────────────────────────────────────────────────────────────────────

def _cost(tokens: dict[str, int]) -> float:
    price = PRICE_TABLE.get(settings.LLM_MODEL, {})
    return (
        tokens.get("prompt", 0) * price.get("input", 0)
        + tokens.get("completion", 0) * price.get("output", 0)
    )


def _trace_url(run_id: uuid.UUID) -> str | None:
    if not settings.LANGCHAIN_TRACING_V2 or not settings.LANGCHAIN_API_KEY:
        return None
    try:
        from langsmith import Client as LSClient
        return str(LSClient().share_run(run_id))
    except Exception as exc:
        log.warning("trace URL unavailable: %s", exc)
        return f"https://smith.langchain.com/projects/p/{settings.LANGCHAIN_PROJECT}"


def _update_metrics(final: dict, latency_ms: int, cost: float) -> None:
    decision = final.get("decision") or "ESCALATE"
    category = final.get("category") or "other"
    tickets_total.labels(decision=decision, category=category).inc()
    ticket_latency_seconds.observe(latency_ms / 1000)
    for node, ms in final.get("node_latency_ms", {}).items():
        node_latency_seconds.labels(node=node).observe(ms / 1000)
    t = final.get("tokens", {})
    tokens_total.labels(kind="prompt").inc(t.get("prompt", 0))
    tokens_total.labels(kind="completion").inc(t.get("completion", 0))
    cost_usd_total.inc(cost)
    review_iterations.observe(final.get("iterations", 0))


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.post("/resolve", response_model=ResolveResponse)
async def resolve(req: ResolveRequest):
    t0 = time.monotonic()
    ticket_id = req.ticket_id or str(uuid.uuid4())

    scan = scan_input(req.ticket, req.order_id)

    if scan["is_injection"]:
        latency_ms = int((time.monotonic() - t0) * 1000)
        tickets_total.labels(decision="REFUSE", category="none").inc()
        ticket_latency_seconds.observe(latency_ms / 1000)
        save_ticket(
            ticket_id=ticket_id, raw_ticket=req.ticket,
            ticket=scan["sanitized"], category="none", decision="REFUSE",
            reply="This request cannot be processed.",
            escalation_reason=scan["injection_pattern"],
            iterations=0, tokens_prompt=0, tokens_completion=0,
            cost_usd=0.0, latency_ms=latency_ms, langsmith_trace_url=None,
        )
        return ResolveResponse(
            ticket_id=ticket_id, decision="REFUSE", category=None,
            reply="This request cannot be processed.",
            tool_calls=[], iterations=0, escalation_reason=None,
            langsmith_trace_url=None, latency_ms=latency_ms,
            tokens={"prompt": 0, "completion": 0}, cost_usd=0.0,
        )

    initial_state: TicketState = {
        "ticket_id": ticket_id,
        "raw_ticket": req.ticket,
        "ticket": scan["sanitized"],
        "order_id": scan["order_id"],
        "category": "", "category_reason": "",
        "facts": [], "tool_calls": [], "draft": "",
        "review_verdict": None, "review_issues": [],
        "iterations": 0, "decision": None, "escalation_reason": None,
        "redactions": scan["redaction_types"],
        "node_latency_ms": {}, "tokens": {"prompt": 0, "completion": 0},
    }

    run_id = uuid.uuid4()
    final = _graph.invoke(initial_state, config={"run_id": run_id})

    # Outbound PII scan on the draft before returning.
    reply, _ = redact(final["draft"])

    tokens = final.get("tokens", {"prompt": 0, "completion": 0})
    cost = _cost(tokens)
    latency_ms = int((time.monotonic() - t0) * 1000)
    trace_url = _trace_url(run_id)

    _update_metrics(final, latency_ms, cost)

    decision = final.get("decision") or "ESCALATE"
    category = final.get("category") or "other"

    save_ticket(
        ticket_id=ticket_id, raw_ticket=req.ticket,
        ticket=scan["sanitized"], category=category, decision=decision,
        reply=reply, escalation_reason=final.get("escalation_reason"),
        iterations=final.get("iterations", 0),
        tokens_prompt=tokens.get("prompt", 0),
        tokens_completion=tokens.get("completion", 0),
        cost_usd=cost, latency_ms=latency_ms, langsmith_trace_url=trace_url,
    )
    save_tool_calls(ticket_id, final.get("tool_calls", []))

    return ResolveResponse(
        ticket_id=ticket_id, decision=decision, category=category,
        reply=reply,
        tool_calls=[
            {"name": tc["name"], "args": tc["args"],
             "ok": tc["ok"], "latency_ms": tc["latency_ms"]}
            for tc in final.get("tool_calls", [])
        ],
        iterations=final.get("iterations", 0),
        escalation_reason=final.get("escalation_reason"),
        langsmith_trace_url=trace_url,
        latency_ms=latency_ms, tokens=tokens, cost_usd=cost,
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "llm_provider": settings.LLM_PROVIDER,
        "version": "1.0.0",
    }


@app.get("/metrics")
async def metrics():
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/tickets/{ticket_id}")
async def ticket_detail(ticket_id: str):
    record = get_ticket(ticket_id)
    if not record:
        raise HTTPException(status_code=404, detail="ticket not found")
    return record


# Static UI — mounted last so API routes take priority.
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
