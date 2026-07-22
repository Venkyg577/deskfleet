import json
import logging
from pathlib import Path

import httpx

from app.config import settings

log = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_TIMEOUT = httpx.Timeout(5.0)


def _load_fixture(name: str) -> dict | list:
    return json.loads((FIXTURES_DIR / name).read_text())


def _get(path: str) -> dict | list | None:
    url = f"{settings.STORE_API_BASE}{path}"
    for attempt in range(2):
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                r = client.get(url)
                r.raise_for_status()
                return r.json()
        except Exception as exc:
            log.warning("GET %s attempt %d failed: %s", url, attempt + 1, exc)
    return None


def fetch_cart(order_id: str) -> dict | None:
    if settings.STORE_API_OFFLINE:
        return None
    return _get(f"/carts/{order_id}")


def fetch_product(product_id: int) -> dict | None:
    if settings.STORE_API_OFFLINE:
        products: list = _load_fixture("products.json")  # type: ignore[assignment]
        return next((p for p in products if p["id"] == product_id), None)
    data = _get(f"/products/{product_id}")
    if not data:
        products = _load_fixture("products.json")  # type: ignore[assignment]
        return next((p for p in products if p["id"] == product_id), None)
    return data


def fetch_all_products() -> list:
    if settings.STORE_API_OFFLINE:
        return _load_fixture("products.json")  # type: ignore[return-value]
    data = _get("/products")
    if not data:
        log.warning("fetch_all_products fell back to fixture")
        return _load_fixture("products.json")  # type: ignore[return-value]
    return data  # type: ignore[return-value]
