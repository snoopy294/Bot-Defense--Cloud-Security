from __future__ import annotations

import time
from decimal import Decimal

from catalog.handler import handler


def _seed(tables, *, drop_at: int, stock: int = 5):
    tables.Table("Products").put_item(Item={
        "product_id": "prod-1",
        "catalog_pk": "PRODUCT",
        "title": "Elite Trainer Box",
        "price": Decimal("49.99"),
        "stock": stock,
        "total_units": stock,
        "drop_at": drop_at,
    })


def _event(route_key: str, path_id: str | None = None) -> dict:
    event = {
        "routeKey": route_key,
        "requestContext": {"authorizer": {"lambda": {"session_id": "sess-1"}}},
    }
    if path_id is not None:
        event["pathParameters"] = {"id": path_id}
    return event


def test_list_before_drop_hides_stock_and_shows_upcoming(tables):
    _seed(tables, drop_at=int(time.time()) + 3600)
    result = handler(_event("GET /products"), None)
    assert result["statusCode"] == 200
    import json
    body = json.loads(result["body"])
    assert body[0]["status"] == "upcoming"
    assert "stock" not in body[0]


def test_list_after_drop_shows_live_stock(tables):
    _seed(tables, drop_at=int(time.time()) - 10, stock=3)
    result = handler(_event("GET /products"), None)
    import json
    body = json.loads(result["body"])
    assert body[0]["status"] == "live"
    assert body[0]["stock"] == 3


def test_detail_not_found_returns_404(tables):
    result = handler(_event("GET /products/{id}", path_id="missing"), None)
    assert result["statusCode"] == 404
