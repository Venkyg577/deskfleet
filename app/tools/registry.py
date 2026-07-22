import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, TypedDict

from app.metrics import guardrail_blocks_total, tool_calls_total
from app.tools.store_api import fetch_cart, fetch_product, fetch_all_products

log = logging.getLogger(__name__)

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── TypedDict returned by every tool call ─────────────────────────────────────

class ToolCall(TypedDict):
    name: str
    args: dict
    ok: bool
    result: dict | list | None
    error: str | None
    latency_ms: int


# ── Tool implementations ───────────────────────────────────────────────────────

def _load_overlay() -> dict:
    return json.loads((_FIXTURES_DIR / "order_status.json").read_text())


def get_order_status(order_id: str) -> dict:
    """Return fulfilment status for the given order ID.

    Fetches live cart data from FakeStoreAPI for user_id, placed_on, and
    raw item list, then joins the local order_status.json fixture for
    status, carrier, eta, and total_usd. This is a documented fixture
    overlay; see README for rationale (D3).
    """
    overlay = _load_overlay()

    if order_id not in overlay:
        return {"found": False, "order_id": order_id}

    entry = overlay[order_id]
    if not entry.get("found", True):
        return entry

    result: dict = dict(entry)

    # Enrich with live cart data when available.
    cart = fetch_cart(order_id)
    if cart and isinstance(cart, dict) and "userId" in cart:
        result["user_id"] = cart["userId"]
        raw_date = cart.get("date", "")
        result["placed_on"] = raw_date[:10] if raw_date else result.get("placed_on")
        if "products" in cart:
            result["items"] = [
                {"product_id": p["productId"], "quantity": p["quantity"]}
                for p in cart["products"]
            ]

    return result


def get_product(product_id: int) -> dict:
    """Return product details by numeric ID."""
    data = fetch_product(product_id)
    if data is None:
        return {"found": False, "product_id": product_id}
    return data


def search_products(query: str, limit: int = 5) -> list[dict]:
    """Search the product catalog by keyword. Client-side filter over the
    cached /products response; FakeStoreAPI has no search endpoint."""
    limit = min(max(limit, 1), 10)
    q = query.lower()
    products = fetch_all_products()
    matches = [
        {
            "id": p["id"],
            "title": p["title"],
            "price": p["price"],
            "category": p["category"],
        }
        for p in products
        if q in p.get("title", "").lower()
        or q in p.get("description", "").lower()
        or q in p.get("category", "").lower()
    ]
    return matches[:limit]


# ── Allowlist and schemas ──────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, Callable[..., Any]] = {
    "get_order_status": get_order_status,
    "get_product": get_product,
    "search_products": search_products,
}

# JSON schemas passed to llm.bind_tools() in the Researcher node.
TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": (
                "Look up the current fulfilment status of a customer order by its "
                "order ID. Use this for any question about where an order is, when "
                "it will arrive, or whether it shipped."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "Numeric order identifier, e.g. '5'",
                    }
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product",
            "description": "Return product details including price, category, and description by numeric product ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "integer",
                        "description": "Numeric product identifier, e.g. 7",
                    }
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search the product catalog by keyword. Returns id, title, price, and category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword, e.g. 'jacket'",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return (1-10, default 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
]


# ── Chokepoint ─────────────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict) -> ToolCall:
    """Dispatch a tool call through the allowlist. Never raises to the caller."""
    if name not in TOOL_REGISTRY:
        guardrail_blocks_total.labels(type="off_allowlist").inc()
        log.warning("blocked off-allowlist tool", extra={"tool": name})
        return ToolCall(
            name=name, args=args, ok=False,
            result=None, error="TOOL_NOT_ALLOWED", latency_ms=0,
        )

    t0 = time.monotonic()
    try:
        result = TOOL_REGISTRY[name](**args)
        latency_ms = int((time.monotonic() - t0) * 1000)
        tool_calls_total.labels(tool=name, outcome="ok").inc()
        return ToolCall(
            name=name, args=args, ok=True,
            result=result, error=None, latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        tool_calls_total.labels(tool=name, outcome="error").inc()
        log.error("tool %s raised: %s", name, exc, extra={"tool": name})
        return ToolCall(
            name=name, args=args, ok=False,
            result=None, error=str(exc), latency_ms=latency_ms,
        )
