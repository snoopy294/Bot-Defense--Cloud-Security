from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from cart.handler import handler


def test_concurrent_cart_requests_exactly_one_success(tables):
    tables.Table("Products").put_item(Item={
        "product_id": "prod-1",
        "catalog_pk": "PRODUCT",
        "title": "Elite Trainer Box",
        "price": Decimal("49.99"),
        "stock": 1,
        "total_units": 1,
        "drop_at": int(time.time()) - 10,
    })

    def attempt(i: int) -> int:
        event = {
            "body": json.dumps({"product_id": "prod-1"}),
            "requestContext": {"authorizer": {"lambda": {"session_id": f"sess-{i}"}}},
        }
        return handler(event, None)["statusCode"]

    with ThreadPoolExecutor(max_workers=10) as pool:
        statuses = list(pool.map(attempt, range(10)))

    assert statuses.count(201) == 1
    assert statuses.count(409) == 9
