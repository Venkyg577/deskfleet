from app.tools.registry import execute_tool
from app.metrics import guardrail_blocks_total


def test_off_allowlist_returns_error():
    tc = execute_tool("delete_user", {"id": 1})
    assert tc["ok"] is False
    assert tc["error"] == "TOOL_NOT_ALLOWED"
    assert tc["result"] is None
    assert tc["latency_ms"] == 0


def test_off_allowlist_second_tool_also_blocked():
    tc = execute_tool("drop_table", {"name": "tickets"})
    assert tc["ok"] is False
    assert tc["error"] == "TOOL_NOT_ALLOWED"


def test_off_allowlist_increments_guardrail_counter():
    before = guardrail_blocks_total.labels(type="off_allowlist")._value.get()
    execute_tool("not_a_real_tool", {})
    after = guardrail_blocks_total.labels(type="off_allowlist")._value.get()
    assert after == before + 1
