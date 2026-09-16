from __future__ import annotations

import os
import time
import uuid

import boto3
from botocore.exceptions import ClientError

from common.logging import log_request
from common.responses import json_response
from common.validation import endpoint, body_object, identifier

RESERVATION_TTL_SECONDS = 300


def _products_table():
    return boto3.resource("dynamodb").Table(os.environ["PRODUCTS_TABLE"])


@endpoint
def handler(event: dict, context) -> dict:
    start = time.time()
    session_id = event["requestContext"]["authorizer"]["lambda"]["session_id"]
    request_id = event.get("requestContext", {}).get("requestId")
    product_id = identifier(body_object(event).get("product_id"))
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

    reservation_id = str(uuid.uuid4())
    try:
        boto3.client("dynamodb").transact_write_items(TransactItems=[
            {"Update": {
                "TableName": os.environ["PRODUCTS_TABLE"],
                "Key": {"product_id": {"S": product_id}},
                "UpdateExpression": "SET stock = stock - :one",
                "ConditionExpression": "stock > :zero AND drop_at <= :now",
                "ExpressionAttributeValues": {":one": {"N": "1"}, ":zero": {"N": "0"}, ":now": {"N": str(now)}},
            }},
            {"Put": {
                "TableName": os.environ["RESERVATIONS_TABLE"],
                "Item": {"reservation_id": {"S": reservation_id}, "product_id": {"S": product_id},
                         "session_id": {"S": session_id}, "ttl": {"N": str(now + RESERVATION_TTL_SECONDS)},
                         "status": {"S": "active"}},
                "ConditionExpression": "attribute_not_exists(reservation_id)",
            }},
        ])
    except ClientError as err:
        reasons = err.response.get("CancellationReasons", [])
        if err.response["Error"]["Code"] == "TransactionCanceledException" and reasons and reasons[0].get("Code") == "ConditionalCheckFailed":
            result = json_response(409, {"error": "sold_out"})
            log_request(route="POST /cart", method="POST", status=409, start_time=start,
                        session_id=session_id, product_id=product_id, outcome="sold_out",
                        request_id=request_id)
            return result
        raise

    result = json_response(201, {"reservation_id": reservation_id})
    log_request(route="POST /cart", method="POST", status=201, start_time=start,
                session_id=session_id, product_id=product_id, outcome="reserved",
                request_id=request_id)
    return result
