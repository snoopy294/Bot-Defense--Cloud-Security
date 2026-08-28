from __future__ import annotations

import json
import time
from decimal import Decimal

from cart.handler import handler


def _seed(tables, *, drop_at: int, stock: int = 1):
    tables.Table("Products").put_item(Item={
        "product_id": "prod-1",
        "catalog_pk": "PRODUCT",
        "title": "Elite Trainer Box",
        "price": Decimal("49.99"),
        "stock": stock,
        "total_units": stock,
        "drop_at": drop_at,
    })


def _event(product_id: str, session_id: str = "sess-1") -> dict:
    return {
        "body": json.dumps({"product_id": product_id}),
        "requestContext": {"authorizer": {"lambda": {"session_id": session_id}}},
    }


def test_cart_too_early_returns_425(tables):
    _seed(tables, drop_at=int(time.time()) + 3600)
    result = handler(_event("prod-1"), None)
    assert result["statusCode"] == 425


def test_cart_reserves_and_decrements_stock(tables):
    _seed(tables, drop_at=int(time.time()) - 10, stock=1)
    result = handler(_event("prod-1"), None)
    assert result["statusCode"] == 201
    reservation_id = json.loads(result["body"])["reservation_id"]

    product = tables.Table("Products").get_item(Key={"product_id": "prod-1"})["Item"]
    assert product["stock"] == 0

    reservation = tables.Table("Reservations").get_item(Key={"reservation_id": reservation_id})["Item"]
    assert reservation["session_id"] == "sess-1"
    assert reservation["status"] == "active"


def test_cart_sold_out_returns_409(tables):
    _seed(tables, drop_at=int(time.time()) - 10, stock=0)
    result = handler(_event("prod-1"), None)
    assert result["statusCode"] == 409


def test_cart_unknown_product_returns_404(tables):
    result = handler(_event("missing"), None)
    assert result["statusCode"] == 404
