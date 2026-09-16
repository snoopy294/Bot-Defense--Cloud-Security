from __future__ import annotations

import os
import time
import hmac
from decimal import Decimal, DecimalException

import boto3
from boto3.dynamodb.types import TypeSerializer

from common.logging import log_request
from common.responses import json_response
from common.validation import endpoint, body_object, identifier, InvalidRequest


def _ssm():
    return boto3.client("ssm")


def _admin_secret() -> str:
    resp = _ssm().get_parameter(Name=os.environ["ADMIN_SECRET_PARAM"], WithDecryption=True)
    return resp["Parameter"]["Value"]


def _table(env_key: str):
    return boto3.resource("dynamodb").Table(os.environ[env_key])


def _clear_table(table, key_name: str) -> None:
    with table.batch_writer() as batch:
        scan_kwargs = {"ProjectionExpression": key_name}
        while True:
            resp = table.scan(**scan_kwargs)
            for item in resp.get("Items", []):
                batch.delete_item(Key={key_name: item[key_name]})
            if "LastEvaluatedKey" not in resp:
                break
            scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


@endpoint
def handler(event: dict, context) -> dict:
    start = time.time()
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    token = headers.get("x-admin-token")
    request_id = event.get("requestContext", {}).get("requestId")

    if not token or not hmac.compare_digest(token.encode(), _admin_secret().encode()):
        result = json_response(401, {"error": "unauthorized"})
        log_request(route="POST /admin/reset", method="POST", status=401, start_time=start,
                    session_id=None, product_id=None, outcome="unauthorized",
                    request_id=request_id)
        return result

    products = body_object(event).get("products")
    if not isinstance(products, list):
        raise InvalidRequest("invalid_products")
    seen = set()
    for product in products:
        if not isinstance(product, dict):
            raise InvalidRequest("invalid_product")
        product_id = identifier(product.get("product_id"))
        if product_id in seen:
            raise InvalidRequest("duplicate_product")
        seen.add(product_id)
        if not isinstance(product.get("title"), str) or not product["title"].strip() or len(product["title"]) > 500:
            raise InvalidRequest("invalid_title")
        for key in ("stock", "drop_at"):
            if type(product.get(key)) is not int or product[key] < 0:
                raise InvalidRequest(f"invalid_{key}")
        if type(product.get("price")) not in (int, float):
            raise InvalidRequest("invalid_price")
        price = Decimal(str(product["price"]))
        if not price.is_finite() or price < 0:
            raise InvalidRequest("invalid_price")
        try:
            for value in (price, product["stock"], product["drop_at"]):
                TypeSerializer().serialize(value)
        except (TypeError, ValueError, DecimalException) as exc:
            raise InvalidRequest("invalid_number") from exc

    _clear_table(_table("RESERVATIONS_TABLE"), "reservation_id")
    _clear_table(_table("ORDERS_TABLE"), "order_id")

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
                session_id=None, product_id=None, outcome="ok", request_id=request_id)
    return result
