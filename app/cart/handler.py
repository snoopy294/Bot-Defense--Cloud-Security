from __future__ import annotations

import json
import os
import time
import uuid

import boto3
from botocore.exceptions import ClientError

from common.logging import log_request
from common.responses import json_response

RESERVATION_TTL_SECONDS = 300


def _products_table():
    return boto3.resource("dynamodb").Table(os.environ["PRODUCTS_TABLE"])


def _reservations_table():
    return boto3.resource("dynamodb").Table(os.environ["RESERVATIONS_TABLE"])


def handler(event: dict, context) -> dict:
    start = time.time()
    session_id = event["requestContext"]["authorizer"]["lambda"]["session_id"]
    request_id = event.get("requestContext", {}).get("requestId")
    product_id = json.loads(event.get("body") or "{}").get("product_id")
    now = int(time.time())

    products = _products_table()
    product = products.get_item(Key={"product_id": product_id}).get("Item")

    if product is None:
        result = json_response(404, {"error": "not_found"})
        log_request(route="POST /cart", method="POST", status=404, start_time=start,
                    session_id=session_id, product_id=product_id, outcome="not_found",
                    request_id=request_id)
        return result

    if now < int(product["drop_at"]):
        result = json_response(425, {"error": "too_early", "drop_at": int(product["drop_at"])})
        log_request(route="POST /cart", method="POST", status=425, start_time=start,
                    session_id=session_id, product_id=product_id, outcome="too_early",
                    request_id=request_id)
        return result

    try:
        products.update_item(
            Key={"product_id": product_id},
            UpdateExpression="SET stock = stock - :one",
            ConditionExpression="stock > :zero",
            ExpressionAttributeValues={":one": 1, ":zero": 0},
        )
    except ClientError as err:
        if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
            result = json_response(409, {"error": "sold_out"})
            log_request(route="POST /cart", method="POST", status=409, start_time=start,
                        session_id=session_id, product_id=product_id, outcome="sold_out",
                        request_id=request_id)
            return result
        raise

    reservation_id = str(uuid.uuid4())
    _reservations_table().put_item(Item={
        "reservation_id": reservation_id,
        "product_id": product_id,
        "session_id": session_id,
        "ttl": now + RESERVATION_TTL_SECONDS,
        "status": "active",
    })

    result = json_response(201, {"reservation_id": reservation_id})
    log_request(route="POST /cart", method="POST", status=201, start_time=start,
                session_id=session_id, product_id=product_id, outcome="reserved",
                request_id=request_id)
    return result
