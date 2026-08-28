from __future__ import annotations

import json
import time

from admin.handler import handler


def _event(token: str | None, products: list[dict]) -> dict:
    headers = {"x-admin-token": token} if token else {}
    return {"headers": headers, "body": json.dumps({"products": products})}


def test_admin_rejects_wrong_token(tables, admin_secret):
    result = handler(_event("wrong-token", []), None)
    assert result["statusCode"] == 401


def test_admin_reset_reseeds_products_and_clears_reservations_orders(tables, admin_secret):
    tables.Table("Reservations").put_item(Item={
        "reservation_id": "res-old", "product_id": "prod-old",
        "session_id": "sess-old", "ttl": 0, "status": "active",
    })
    tables.Table("Orders").put_item(Item={
        "order_id": "order-old", "reservation_id": "res-old",
        "product_id": "prod-old", "session_id": "sess-old", "created_at": 0,
    })

    drop_at = int(time.time()) + 3600
    result = handler(_event(admin_secret, [
        {"product_id": "prod-1", "title": "Elite Trainer Box", "price": 49.99, "stock": 5, "drop_at": drop_at},
    ]), None)

    assert result["statusCode"] == 200
    assert json.loads(result["body"]) == {"reset": 1}

    product = tables.Table("Products").get_item(Key={"product_id": "prod-1"})["Item"]
    assert product["stock"] == 5
    assert product["catalog_pk"] == "PRODUCT"

    assert "Item" not in tables.Table("Reservations").get_item(Key={"reservation_id": "res-old"})
    assert "Item" not in tables.Table("Orders").get_item(Key={"order_id": "order-old"})
