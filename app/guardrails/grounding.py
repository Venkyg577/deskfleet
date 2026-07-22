import json
import re

from app.policy import SUPPORT_POLICY

_RE_CURRENCY = re.compile(r'\$[\d,]+(?:\.\d+)?')
_RE_ISO_DATE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b')
_RE_INTEGER = re.compile(r'\b(\d{2,})\b')


def check_grounding(
    draft: str,
    facts: list[dict],
    policy: str = SUPPORT_POLICY,
) -> tuple[bool, str | None]:
    """Check that every number, currency amount, and ISO date in the draft
    appears in the serialized facts or the policy text.

    Returns (True, None) when grounded, (False, offending_value) on failure.
    This is a deterministic non-LLM check run after Reviewer approval.
    """
    if not draft:
        return True, None

    haystack = json.dumps(facts) + "\n" + policy

    # Currency amounts: $129.90 -> search for 129.90 (and float-normalized
    # form "129.9") in haystack. Needed because json.loads drops trailing zeros
    # on floats (129.90 -> 129.9 in Python).
    for m in _RE_CURRENCY.finditer(draft):
        numeric = m.group().lstrip("$").replace(",", "")
        try:
            normalized = str(float(numeric))  # "129.90" -> "129.9"
        except ValueError:
            normalized = numeric
        if numeric not in haystack and normalized not in haystack:
            return False, m.group()

    # ISO dates: 2026-07-24
    for m in _RE_ISO_DATE.finditer(draft):
        if m.group() not in haystack:
            return False, m.group()

    # Bare integers (2+ digits), after stripping currency and date contexts.
    stripped = _RE_CURRENCY.sub("", draft)
    stripped = _RE_ISO_DATE.sub("", stripped)
    for m in _RE_INTEGER.finditer(stripped):
        if m.group() not in haystack:
            return False, m.group()

    return True, None
