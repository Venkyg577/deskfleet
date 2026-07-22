from app.guardrails.grounding import check_grounding

_FACTS = [
    {"source": "get_order_status", "key": "order.total_usd", "value": "129.90"},
    {"source": "get_order_status", "key": "order.eta", "value": "2026-07-24"},
    {"source": "get_order_status", "key": "order.order_id", "value": "5"},
]


def test_fabricated_price_caught():
    draft = "Your refund of $999.00 has been processed."
    ok, offender = check_grounding(draft, _FACTS)
    assert ok is False
    assert offender is not None
    assert "999" in offender


def test_grounded_price_passes():
    draft = "Your order total was $129.90 and will arrive on 2026-07-24."
    ok, offender = check_grounding(draft, _FACTS)
    assert ok is True
    assert offender is None


def test_fabricated_date_caught():
    draft = "Your order will arrive on 2026-12-31."
    ok, offender = check_grounding(draft, _FACTS)
    assert ok is False
    assert offender == "2026-12-31"


def test_policy_number_allowed():
    # "30" appears in SUPPORT_POLICY ("30 days"), must not fail grounding.
    ok, offender = check_grounding("Our return window is 30 days.", [], )
    assert ok is True


def test_empty_draft_passes():
    ok, offender = check_grounding("", _FACTS)
    assert ok is True
    assert offender is None


def test_grounded_order_id_passes():
    draft = "We found your order 5 and it is on the way."
    ok, offender = check_grounding(draft, _FACTS)
    assert ok is True
