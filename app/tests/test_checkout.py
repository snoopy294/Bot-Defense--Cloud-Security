from __future__ import annotations

import json
import time

from checkout.handler import handler


def _seed_reservation(tables, *, session_id="sess-1", ttl_delta=300, status="active"):
    tables.Table("Reservations").put_item(Item={
        "reservation_id": "res-1",
        "product_id": "prod-1",
        "session_id": session_id,
        "ttl": int(time.time()) + ttl_delta,
        "status": status,
    })


def _event(reservation_id: str, session_id: str = "sess-1") -> dict:
    return {
        "body": json.dumps({"reservation_id": reservation_id}),
        "requestContext": {"authorizer": {"lambda": {"session_id": session_id}}},
    }


def test_checkout_converts_reservation_to_order(tables):
    _seed_reservation(tables)
    result = handler(_event("res-1"), None)
    assert result["statusCode"] == 200
    order_id = json.loads(result["body"])["order_id"]

    order = tables.Table("Orders").get_item(Key={"order_id": order_id})["Item"]
    assert order["reservation_id"] == "res-1"
    assert order["product_id"] == "prod-1"

    reservation = tables.Table("Reservations").get_item(Key={"reservation_id": "res-1"})["Item"]
    assert reservation["status"] == "consumed"


def test_checkout_rejects_reservation_owned_by_other_session(tables):
    _seed_reservation(tables, session_id="sess-1")
    result = handler(_event("res-1", session_id="sess-2"), None)
    assert result["statusCode"] == 404


def test_checkout_rejects_expired_reservation(tables):
    _seed_reservation(tables, ttl_delta=-10)
    result = handler(_event("res-1"), None)
    assert result["statusCode"] == 410
