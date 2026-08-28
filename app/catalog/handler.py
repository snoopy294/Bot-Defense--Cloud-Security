from __future__ import annotations

import os
import time

import boto3
from boto3.dynamodb.conditions import Key

from common.logging import log_request
from common.responses import json_response


def _table():
    return boto3.resource("dynamodb").Table(os.environ["PRODUCTS_TABLE"])


def _serialize(item: dict, dropped: bool) -> dict:
    out = {
        "product_id": item["product_id"],
        "title": item["title"],
        "price": float(item["price"]),
        "drop_at": int(item["drop_at"]),
    }
    if dropped:
        out["status"] = "live"
        out["stock"] = int(item["stock"])
    else:
        out["status"] = "upcoming"
    return out


def handler(event: dict, context) -> dict:
    start = time.time()
    session_id = event["requestContext"]["authorizer"]["lambda"]["session_id"]
    route = event["routeKey"]
    now = int(time.time())
    table = _table()

    if route == "GET /products/{id}":
        product_id = event["pathParameters"]["id"]
        item = table.get_item(Key={"product_id": product_id}).get("Item")
        if item is None:
            result = json_response(404, {"error": "not_found"})
            outcome = "not_found"
        else:
            result = json_response(200, _serialize(item, now >= int(item["drop_at"])))
            outcome = "ok"
        log_request(route=route, method="GET", status=result["statusCode"],
                    start_time=start, session_id=session_id, product_id=product_id, outcome=outcome)
        return result

    resp = table.query(IndexName="catalog-index", KeyConditionExpression=Key("catalog_pk").eq("PRODUCT"))
    items = [_serialize(item, now >= int(item["drop_at"])) for item in resp.get("Items", [])]
    result = json_response(200, items)
    log_request(route=route, method="GET", status=200, start_time=start,
                session_id=session_id, product_id=None, outcome="ok")
    return result
