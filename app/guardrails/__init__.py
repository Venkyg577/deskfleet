import logging
import re
from typing import TypedDict

from app.guardrails.injection import scan_for_injection
from app.guardrails.pii import redact
from app.metrics import guardrail_blocks_total

log = logging.getLogger(__name__)

# Order ID extraction: must run BEFORE PII redaction (phone patterns can
# swallow digits that look like order IDs if redaction runs first).
_RE_ORDER_ID = re.compile(r'\b(?:order|ord)[\s#:]*(\d{1,6})\b', re.IGNORECASE)


class ScanResult(TypedDict):
    sanitized: str
    order_id: str | None
    is_injection: bool
    injection_pattern: str | None
    redaction_types: list[str]


def scan_input(raw_ticket: str, explicit_order_id: str | None = None) -> ScanResult:
    """Apply the four-step inbound guardrail pipeline (PRD section 8.1).

    1. Extract order_id from raw text (before any redaction).
    2. Scan for prompt injection on the raw text.
    3. Redact PII.
    4. Return ScanResult. Callers short-circuit on is_injection=True.
    """
    # Step 1: extract order_id
    order_id: str | None = explicit_order_id
    if not order_id:
        m = _RE_ORDER_ID.search(raw_ticket)
        if m:
            order_id = m.group(1)

    # Step 2: injection scan on raw text
    is_injection, pattern_name = scan_for_injection(raw_ticket)
    if is_injection:
        guardrail_blocks_total.labels(type="injection").inc()
        log.warning("injection blocked", extra={"pattern": pattern_name})

    # Step 3: PII redaction
    sanitized, redaction_types = redact(raw_ticket)

    return ScanResult(
        sanitized=sanitized,
        order_id=order_id,
        is_injection=is_injection,
        injection_pattern=pattern_name,
        redaction_types=redaction_types,
    )
