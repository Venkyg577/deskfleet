import re

# Patterns from PRD section 8.3. Card runs first: card and phone patterns overlap.
# Replacements use typed placeholders so redacted text stays readable.
_PII_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "card",
        re.compile(r"\b(?:\d[ -]?){13,16}\b"),
        "[CARD_REDACTED]",
    ),
    (
        "ssn",
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "[SSN_REDACTED]",
    ),
    (
        "email",
        re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"),
        "[EMAIL_REDACTED]",
    ),
    (
        "phone",
        re.compile(r"\+?\d[\d\s\-()]{8,}\d"),
        "[PHONE_REDACTED]",
    ),
]


def redact(text: str) -> tuple[str, list[str]]:
    """Replace PII with typed placeholders.

    Returns (redacted_text, redaction_types). Types are recorded; matched
    values are never stored or returned.
    """
    types_found: list[str] = []
    for pii_type, pattern, placeholder in _PII_PATTERNS:
        new_text, count = pattern.subn(placeholder, text)
        if count:
            types_found.append(pii_type)
            text = new_text
    return text, types_found
