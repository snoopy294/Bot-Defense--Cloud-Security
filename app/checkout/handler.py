from __future__ import annotations

import json
import os
import time
import uuid

import boto3

from common.logging import log_request
from common.responses import json_response


def _reservations_table():
    return boto3.resource("dynamodb").Table(os.environ["RESERVATIONS_TABLE"])


def _orders_table():
    return boto3.resource("dynamodb").Table(os.environ["ORDERS_TABLE"])


def handler(event: dict, context) -> dict:
    start = time.time()
    session_id = event["requestContext"]["authorizer"]["lambda"]["session_id"]
    reservation_id = json.loads(event.get("body") or "{}").get("reservation_id")
    now = int(time.time())

    reservations = _reservations_table()
    reservation = reservations.get_item(Key={"reservation_id": reservation_id}).get("Item")

    if reservation is None or reservation["session_id"] != session_id:
        result = json_response(404, {"error": "not_found"})
        log_request(route="POST /checkout", method="POST", status=404, start_time=start,
                    session_id=session_id, product_id=None, outcome="not_found")
        return result

    if reservation["status"] != "active" or now >= int(reservation["ttl"]):
        result = json_response(410, {"error": "expired"})
        log_request(route="POST /checkout", method="POST", status=410, start_time=start,
                    session_id=session_id, product_id=reservation.get("product_id"), outcome="expired")
        return result

    order_id = str(uuid.uuid4())
    _orders_table().put_item(Item={
        "order_id": order_id,
        "reservation_id": reservation_id,
        "product_id": reservation["product_id"],
        "session_id": session_id,
        "created_at": now,
    })
    reservations.update_item(
        Key={"reservation_id": reservation_id},
        UpdateExpression="SET #s = :consumed",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":consumed": "consumed"},
    )

    result = json_response(200, {"order_id": order_id})
    log_request(route="POST /checkout", method="POST", status=200, start_time=start,
                session_id=session_id, product_id=reservation["product_id"], outcome="ordered")
    return result
