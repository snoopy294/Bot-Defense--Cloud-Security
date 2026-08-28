from __future__ import annotations

import json
import os
import time
from decimal import Decimal

import boto3

from common.logging import log_request
from common.responses import json_response


def _ssm():
    return boto3.client("ssm")


def _admin_secret() -> str:
    resp = _ssm().get_parameter(Name=os.environ["ADMIN_SECRET_PARAM"], WithDecryption=True)
    return resp["Parameter"]["Value"]


def _table(env_key: str):
    return boto3.resource("dynamodb").Table(os.environ[env_key])


def _clear_table(table) -> None:
    key_name = table.key_schema[0]["AttributeName"]
    items = table.scan(ProjectionExpression=key_name).get("Items", [])
    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={key_name: item[key_name]})


def handler(event: dict, context) -> dict:
    start = time.time()
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    token = headers.get("x-admin-token")

    if token != _admin_secret():
        result = json_response(401, {"error": "unauthorized"})
        log_request(route="POST /admin/reset", method="POST", status=401, start_time=start,
                    session_id=None, product_id=None, outcome="unauthorized")
        return result

    products = json.loads(event.get("body") or "{}").get("products", [])

    _clear_table(_table("RESERVATIONS_TABLE"))
    _clear_table(_table("ORDERS_TABLE"))

    products_table = _table("PRODUCTS_TABLE")
    for product in products:
        price = product["price"]
        if isinstance(price, float):
            price = Decimal(str(price))
        products_table.put_item(Item={
            "product_id": product["product_id"],
            "catalog_pk": "PRODUCT",
            "title": product["title"],
            "price": price,
            "stock": product["stock"],
            "total_units": product["stock"],
            "drop_at": product["drop_at"],
        })

    result = json_response(200, {"reset": len(products)})
    log_request(route="POST /admin/reset", method="POST", status=200, start_time=start,
                session_id=None, product_id=None, outcome="ok")
    return result
