from __future__ import annotations

import os
import time

import boto3
from botocore.exceptions import ClientError

from common.logging import log_request
from common.responses import json_response
from common.validation import endpoint, body_object, identifier


def _reservations_table():
    return boto3.resource("dynamodb").Table(os.environ["RESERVATIONS_TABLE"])


def _orders_table():
    return boto3.resource("dynamodb").Table(os.environ["ORDERS_TABLE"])


@endpoint
def handler(event: dict, context) -> dict:
    start = time.time()
    session_id = event["requestContext"]["authorizer"]["lambda"]["session_id"]
    request_id = event.get("requestContext", {}).get("requestId")
    reservation_id = identifier(body_object(event).get("reservation_id"))
    now = int(time.time())

    def retry_response(existing):
        owned = existing["session_id"] == session_id
        status = 200 if owned else 404
        log_request(route="POST /checkout", method="POST", status=status, start_time=start,
                    session_id=session_id, product_id=existing.get("product_id") if owned else None,
                    outcome="ordered_retry" if owned else "not_found", request_id=request_id)
        return json_response(status, {"order_id": reservation_id} if owned else {"error": "not_found"})

    orders = _orders_table()
    existing = orders.get_item(Key={"order_id": reservation_id}, ConsistentRead=True).get("Item")
    if existing:
        return retry_response(existing)
    reservations = _reservations_table()
    reservation = reservations.get_item(Key={"reservation_id": reservation_id}, ConsistentRead=True).get("Item")

    if reservation is None or reservation["session_id"] != session_id:
        result = json_response(404, {"error": "not_found"})
        log_request(route="POST /checkout", method="POST", status=404, start_time=start,
                    session_id=session_id, product_id=None, outcome="not_found",
                    request_id=request_id)
        return result

    if reservation["status"] != "active" or now >= int(reservation["ttl"]):
        existing = orders.get_item(Key={"order_id": reservation_id}, ConsistentRead=True).get("Item")
        if existing and existing["session_id"] == session_id:
            return retry_response(existing)
        result = json_response(410, {"error": "expired"})
        log_request(route="POST /checkout", method="POST", status=410, start_time=start,
                    session_id=session_id, product_id=reservation.get("product_id"),
                    outcome="expired", request_id=request_id)
        return result

    order_id = reservation_id
    try:
        boto3.client("dynamodb").transact_write_items(TransactItems=[
            {"Update": {
                "TableName": os.environ["RESERVATIONS_TABLE"],
                "Key": {"reservation_id": {"S": reservation_id}},
                "UpdateExpression": "SET #s = :consumed",
                "ConditionExpression": "#s = :active AND session_id = :session AND #ttl > :now",
                "ExpressionAttributeNames": {"#s": "status", "#ttl": "ttl"},
                "ExpressionAttributeValues": {":consumed": {"S": "consumed"}, ":active": {"S": "active"},
                                              ":session": {"S": session_id}, ":now": {"N": str(now)}},
            }},
            {"Put": {
                "TableName": os.environ["ORDERS_TABLE"],
                "Item": {"order_id": {"S": order_id}, "reservation_id": {"S": reservation_id},
                         "product_id": {"S": reservation["product_id"]}, "session_id": {"S": session_id},
                         "created_at": {"N": str(now)}},
                "ConditionExpression": "attribute_not_exists(order_id)",
            }},
        ])
    except ClientError as err:
        if err.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        existing = orders.get_item(Key={"order_id": order_id}, ConsistentRead=True).get("Item")
        if existing and existing["session_id"] == session_id:
            return retry_response(existing)
        log_request(route="POST /checkout", method="POST", status=409, start_time=start,
                    session_id=session_id, product_id=reservation["product_id"],
                    outcome="reservation_conflict", request_id=request_id)
        return json_response(409, {"error": "reservation_conflict"})

    result = json_response(200, {"order_id": order_id})
    log_request(route="POST /checkout", method="POST", status=200, start_time=start,
                session_id=session_id, product_id=reservation["product_id"], outcome="ordered",
                request_id=request_id)
    return result
