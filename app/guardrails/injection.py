import re

# Patterns from PRD section 8.2. Any match is a REFUSE. Case-insensitive.
# Do not echo the matched pattern back to the caller.
_RAW_PATTERNS: list[tuple[str, str]] = [
    ("ignore_instructions",     r"ignore (all )?(previous|prior|above) instructions"),
    ("disregard_system",        r"disregard (the )?(system|previous|above)"),
    ("you_are_now",             r"you are now (a|an|the)?"),
    ("new_prompt",              r"new (system )?(prompt|instructions?|role)"),
    ("xml_tag",                 r"<\/?(system|assistant|instructions?)>"),
    ("reveal_system_prompt",    r"(reveal|print|show) (me )?(your |the )?(system prompt|instructions|prompt)"),
    ("jailbreak_mode",          r"developer mode|jailbreak|DAN mode"),
    ("override_safety",         r"override (your )?(safety|guardrails|rules)"),
]

INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in _RAW_PATTERNS
]


def scan_for_injection(text: str) -> tuple[bool, str | None]:
    """Return (True, pattern_name) on first match, (False, None) otherwise."""
    for name, pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            return True, name
    return False, None
