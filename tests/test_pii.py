from app.guardrails import scan_input
from app.guardrails.pii import redact


def test_email_redacted():
    text, types = redact("contact me at user@example.com for updates")
    assert "[EMAIL_REDACTED]" in text
    assert "user@example.com" not in text
    assert "email" in types


def test_phone_redacted():
    text, types = redact("call me on +91 98765 43210 anytime")
    assert "[PHONE_REDACTED]" in text
    assert "98765" not in text
    assert "phone" in types


def test_card_redacted_not_as_phone():
    text, types = redact("my card number is 4111 1111 1111 1111")
    assert "[CARD_REDACTED]" in text
    assert "4111" not in text
    assert "card" in types
    assert "phone" not in types


def test_ssn_redacted():
    text, types = redact("my SSN is 123-45-6789")
    assert "[SSN_REDACTED]" in text
    assert "123-45-6789" not in text
    assert "ssn" in types


def test_order_id_survives_phone_redaction():
    """Order ID must be extracted before PII redaction (PRD 8.1)."""
    result = scan_input("where is order 5, call me on +91 98765 43210", None)
    assert result["order_id"] == "5"
    assert "43210" not in result["sanitized"]
    assert "[PHONE_REDACTED]" in result["sanitized"]


def test_no_pii_value_in_redaction_types():
    """Redaction types list must never contain the matched value."""
    _, types = redact("email: secret@corp.com, card: 4111 1111 1111 1111")
    for t in types:
        assert "@" not in t
        assert t in ("card", "email", "phone", "ssn")


def test_multiple_pii_types_all_redacted():
    text, types = redact(
        "email foo@bar.com, SSN 123-45-6789, phone +1 800 555 1234"
    )
    assert "foo@bar.com" not in text
    assert "123-45-6789" not in text
    assert "555" not in text
    assert set(types) >= {"email", "ssn", "phone"}
