import json
import logging
import re
import time
from typing import Any

import tiktoken
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.config import settings
from app.graph.state import Classification, Fact, Review, TicketState
from app.guardrails.grounding import check_grounding
from app.policy import SUPPORT_POLICY
from app.tools.registry import TOOL_SCHEMAS, ToolCall, execute_tool

log = logging.getLogger(__name__)

_enc: tiktoken.Encoding | None = None


def _tokenizer() -> tiktoken.Encoding:
    global _enc
    if _enc is None:
        _enc = tiktoken.encoding_for_model(settings.LLM_MODEL)
    return _enc


def _count(text: str) -> int:
    try:
        return len(_tokenizer().encode(text))
    except Exception:
        return 0


def _prompt_tokens(messages: list) -> int:
    return sum(
        _count(m.content)
        for m in messages
        if hasattr(m, "content") and isinstance(m.content, str)
    )


def _completion_tokens(response: Any) -> int:
    if isinstance(response, AIMessage):
        return _count(response.content or "")
    if hasattr(response, "model_dump_json"):
        return _count(response.model_dump_json())
    return _count(str(response))


def _flatten_to_facts(tool_call: ToolCall) -> list[Fact]:
    """Flatten a tool result into Fact key/value pairs for the Responder."""
    if not tool_call["ok"] or tool_call["result"] is None:
        return []
    source = tool_call["name"]
    facts: list[Fact] = []

    def _walk(obj: Any, prefix: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                _walk(v, f"{prefix}.{k}" if prefix else k)
        elif isinstance(obj, list):
            facts.append(Fact(source=source, key=prefix or "results", value=json.dumps(obj)))
        else:
            facts.append(Fact(source=source, key=prefix or "value", value="" if obj is None else str(obj)))

    _walk(tool_call["result"], "")
    return facts


def _format_facts(facts: list[Fact]) -> str:
    if not facts:
        return "No facts available."
    return "\n".join(
        f"{i + 1}. [{f['source']}] {f['key']} = {f['value']}"
        for i, f in enumerate(facts)
    )


# ── Node factories ─────────────────────────────────────────────────────────────

def make_classifier(llm: BaseChatModel):
    chain = llm.with_structured_output(Classification)

    def classifier(state: TicketState) -> dict:
        t0 = time.monotonic()
        messages = [
            SystemMessage(content=(
                "You are a support ticket classifier. Classify the ticket into exactly one of:\n"
                "- order: questions about order status, shipping, delivery, or tracking\n"
                "- product: questions about product details, availability, or specifications\n"
                "- refund: requests for returns, refunds, or exchanges\n"
                "- other: anything that does not clearly fit the above\n\n"
                "Pick 'other' rather than guess. Respond with JSON only."
            )),
            HumanMessage(content=state["ticket"]),
        ]
        pt = _prompt_tokens(messages)
        result: Classification = chain.invoke(messages)
        ct = _completion_tokens(result)
        latency_ms = int((time.monotonic() - t0) * 1000)
        log.info("classifier: category=%s", result.category)
        return {
            "category": result.category,
            "category_reason": result.reason,
            "node_latency_ms": {"classifier": latency_ms},
            "tokens": {"prompt": pt, "completion": ct},
        }

    return classifier


def make_researcher(llm: BaseChatModel):
    bound = llm.bind_tools(TOOL_SCHEMAS)

    def researcher(state: TicketState) -> dict:
        t0 = time.monotonic()
        order_id_str = state["order_id"] or "not provided"
        messages: list = [
            SystemMessage(content=(
                "You are a support research assistant. Gather facts using tools only. "
                "Do NOT write any customer-facing text.\n\n"
                f"Ticket category: {state['category']}\n"
                f"Order ID: {order_id_str}\n\n"
                "Instructions:\n"
                "- Use get_order_status for order, shipping, or delivery questions\n"
                "- Use get_product to look up product details by numeric ID\n"
                "- Use search_products to find products by keyword\n"
                "- If an order returns found=false, record it as a fact and stop\n"
                "- Do not retry a tool that already returned a result"
            )),
            HumanMessage(content=state["ticket"]),
        ]
        new_facts: list[Fact] = []
        new_calls: list[ToolCall] = []
        call_count = 0
        prompt_tokens = 0
        completion_tokens = 0

        while call_count < settings.MAX_TOOL_CALLS:
            prompt_tokens += _prompt_tokens(messages)
            response: AIMessage = bound.invoke(messages)
            completion_tokens += _completion_tokens(response)

            if not response.tool_calls:
                break

            messages.append(response)
            for tc in response.tool_calls:
                result = execute_tool(tc["name"], tc["args"])
                new_calls.append(result)
                call_count += 1

                content = json.dumps(
                    result["result"] if result["ok"] else {"error": result["error"]}
                )
                messages.append(ToolMessage(content=content, tool_call_id=tc["id"]))
                new_facts.extend(_flatten_to_facts(result))

                # found:false means the order doesn't exist; stop calling tools
                r = result["result"]
                if isinstance(r, dict) and r.get("found") is False:
                    break

        latency_ms = int((time.monotonic() - t0) * 1000)
        log.info("researcher: %d tool calls, %d facts", len(new_calls), len(new_facts))
        return {
            "facts": new_facts,
            "tool_calls": new_calls,
            "node_latency_ms": {"researcher": latency_ms},
            "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
        }

    return researcher


def make_responder(llm: BaseChatModel):
    def responder(state: TicketState) -> dict:
        t0 = time.monotonic()
        facts_block = _format_facts(state["facts"])

        fix_block = ""
        if state.get("review_issues"):
            items = "\n".join(f"- {issue}" for issue in state["review_issues"])
            fix_block = f"\n\nFix these specific problems from the previous draft:\n{items}"

        messages = [
            SystemMessage(content=(
                "You are a customer support agent for DeskFleet.\n\n"
                f"FACTS (from tool lookups, use these as your only source of truth):\n"
                f"{facts_block}\n\n"
                f"POLICY:\n{SUPPORT_POLICY}\n\n"
                "INSTRUCTIONS:\n"
                "- Answer the customer's question using only the facts above and the policy.\n"
                "- If facts are insufficient, say so plainly. Do not invent details.\n"
                "- Be concise, professional, and specific. Cite actual values from the facts.\n"
                "- Do not make up prices, dates, order IDs, or tracking numbers."
                f"{fix_block}"
            )),
            HumanMessage(content=state["ticket"]),
        ]
        pt = _prompt_tokens(messages)
        response: AIMessage = llm.invoke(messages)
        ct = _completion_tokens(response)
        draft = response.content if isinstance(response.content, str) else str(response.content)
        latency_ms = int((time.monotonic() - t0) * 1000)
        log.info("responder: draft=%d chars", len(draft))
        return {
            "draft": draft,
            "node_latency_ms": {"responder": latency_ms},
            "tokens": {"prompt": pt, "completion": ct},
        }

    return responder


# Customer explicitly asking for a human. Matches "speak to a person",
# "talk to a human agent", "connect me to a representative", etc.
_HUMAN_REQUEST = re.compile(
    r"\b(speak|talk|connect|transfer|escalate)\b[\w\s,'-]{0,30}\b"
    r"(person|human|agent|representative|rep|manager|supervisor)\b",
    re.IGNORECASE,
)


def _forced_escalation(ticket: str, facts: list[Fact]) -> str | None:
    """Deterministic escalation triggers (PRD 6.4). These override an LLM
    'approve' because a rewrite cannot fix them."""
    for f in facts:
        if f["key"].split(".")[-1] == "found" and f["value"].strip().lower() == "false":
            return "order_not_found"
    if _HUMAN_REQUEST.search(ticket):
        return "customer_requested_human"
    return None


def make_reviewer(llm: BaseChatModel):
    chain = llm.with_structured_output(Review)

    def reviewer(state: TicketState) -> dict:
        t0 = time.monotonic()
        facts_block = _format_facts(state["facts"])
        messages = [
            SystemMessage(content=(
                "You are a quality reviewer for DeskFleet support responses.\n\n"
                f"FACTS (ground truth the Responder used):\n{facts_block}\n\n"
                f"POLICY:\n{SUPPORT_POLICY}\n\n"
                f"DRAFT REPLY:\n{state['draft']}\n\n"
                "Evaluate the draft on three dimensions and respond with JSON:\n"
                "- grounded: every factual claim appears in the facts or policy\n"
                "- policy_ok: the reply follows the support policy\n"
                "- addresses_ticket: the reply answers what the customer asked\n\n"
                "Verdict:\n"
                "- approve: all three pass\n"
                "- revise: fixable issues (missed question, tone, minor gap)\n"
                "- escalate: unfixable (order not found, customer demands human, policy exception)\n\n"
                "List each specific issue in 'issues'."
            )),
            HumanMessage(content=state["ticket"]),
        ]
        pt = _prompt_tokens(messages)
        review: Review = chain.invoke(messages)
        ct = _completion_tokens(review)
        latency_ms = int((time.monotonic() - t0) * 1000)

        new_iterations = state["iterations"] + 1
        verdict = review.verdict
        issues = review.issues

        updates: dict = {
            "review_issues": issues,
            "iterations": new_iterations,
            "node_latency_ms": {"reviewer": latency_ms},
            "tokens": {"prompt": pt, "completion": ct},
        }

        # Deterministic escalation triggers override any LLM verdict, including
        # approve, because a rewrite cannot fix a missing order or a human request.
        forced = _forced_escalation(state["ticket"], list(state["facts"]))

        if forced:
            updates.update({
                "review_verdict": "escalate",
                "decision": "ESCALATE",
                "escalation_reason": forced,
            })

        elif verdict == "approve":
            # Deterministic grounding post-check before committing to RESOLVED.
            ok, offender = check_grounding(state["draft"], list(state["facts"]))
            if not ok:
                updates.update({
                    "review_verdict": "escalate",
                    "decision": "ESCALATE",
                    "escalation_reason": f"ungrounded_value_in_draft: {offender}",
                })
            else:
                updates.update({
                    "review_verdict": "approve",
                    "decision": "RESOLVED",
                })

        elif verdict == "escalate":
            updates.update({
                "review_verdict": "escalate",
                "decision": "ESCALATE",
                "escalation_reason": review.reason,
            })

        else:  # revise
            if new_iterations >= settings.MAX_ITERS:
                # Cap breach: force escalate (PRD section 7).
                reason = "max_review_iterations_reached: " + "; ".join(issues)
                updates.update({
                    "review_verdict": "escalate",
                    "decision": "ESCALATE",
                    "escalation_reason": reason,
                })
            else:
                updates.update({"review_verdict": "revise"})

        log.info(
            "reviewer: verdict=%s decision=%s iterations=%d",
            updates.get("review_verdict"), updates.get("decision"), new_iterations,
        )
        return updates

    return reviewer
