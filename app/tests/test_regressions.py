import importlib
import json
import time
import uuid
from decimal import Decimal
from unittest.mock import Mock

import boto3
import pytest
from botocore.exceptions import ClientError

from authorizer.handler import handler as authorize
from catalog.handler import handler as catalog
from cart.handler import handler as cart
from checkout.handler import handler as checkout
from admin.handler import handler as reset


def event(body=None, session="session-a", route="POST /cart"):
    return {"body": json.dumps(body), "routeKey": route,
            "requestContext": {"authorizer": {"lambda": {"session_id": session}}}}


def product(tables):
    item = {"product_id": "p", "catalog_pk": "PRODUCT", "title": "Box",
            "stock": 3, "price": Decimal("10"), "drop_at": int(time.time()) - 1}
    tables.Table("Products").put_item(Item=item)
    return item


def reservation(tables):
    tables.Table("Reservations").put_item(Item={
        "reservation_id": "r", "product_id": "p", "session_id": "session-a",
        "status": "active", "ttl": int(time.time()) + 300})


def test_cookie_round_trip(tables):
    product(tables)
    auth = authorize({}, None)
    first = event(route="GET /products")
    first["requestContext"]["authorizer"]["lambda"] = auth["context"]
    response = catalog(first, None)
    cookie = response["cookies"][0]
    assert "Secure; HttpOnly; SameSite=Lax" in cookie
    auth2 = authorize({"cookies": ["other=1; " + cookie.split(";")[0]]}, None)
    assert auth2["context"]["session_id"] == auth["context"]["session_id"]
    sid = auth2["context"]["session_id"]
    reserved = cart(event({"product_id": "p"}, sid), None)
    rid = json.loads(reserved["body"])["reservation_id"]
    assert checkout(event({"reservation_id": rid}, sid), None)["statusCode"] == 200


def test_expired_and_unknown_sessions_rotate(tables):
    old = str(uuid.uuid4())
    tables.Table("Sessions").put_item(Item={"session_id": old, "ttl": 1, "request_count": 1})
    for sid in (old, str(uuid.uuid4())):
        result = authorize({"headers": {"Cookie": f"session_id={sid}"}}, None)
        assert result["context"]["session_id"] != sid
        assert result["context"]["is_new_session"] == "true"


def test_origin_rejection_happens_before_storage(monkeypatch):
    module = importlib.import_module("authorizer.handler")
    table = Mock(side_effect=AssertionError("must not touch storage"))
    monkeypatch.setattr(module, "_table", table)
    monkeypatch.setenv("ORIGIN_SECRET", "expected")
    for headers in ({}, {"x-origin-verify": "wrong"}):
        assert authorize({"headers": headers}, None) == {"isAuthorized": False}
    monkeypatch.setenv("ORIGIN_SECRET", "")
    assert authorize({}, None) == {"isAuthorized": False}
    table.assert_not_called()


def test_origin_correct_secret_allows_session(tables, monkeypatch):
    monkeypatch.setenv("ORIGIN_SECRET", "expected")
    assert authorize({"headers": {"X-Origin-Verify": "expected"}}, None)["isAuthorized"]


def test_cart_reservation_failure_rolls_back_stock(tables, monkeypatch):
    product(tables)
    reservation(tables)
    module = importlib.import_module("cart.handler")
    monkeypatch.setattr(module.uuid, "uuid4", lambda: "r")
    with pytest.raises(ClientError):
        cart(event({"product_id": "p"}), None)
    assert tables.Table("Products").get_item(Key={"product_id": "p"})["Item"]["stock"] == 3
    assert tables.Table("Reservations").scan()["Count"] == 1


def test_checkout_retry_is_same_order_even_after_reservation_deleted(tables):
    reservation(tables)
    first = checkout(event({"reservation_id": "r"}), None)
    tables.Table("Reservations").delete_item(Key={"reservation_id": "r"})
    assert checkout(event({"reservation_id": "r"}), None) == first
    assert checkout(event({"reservation_id": "r"}, "another"), None)["statusCode"] == 404
    assert tables.Table("Orders").scan()["Count"] == 1


def test_checkout_stale_active_read_does_not_duplicate_order(tables, monkeypatch):
    reservation(tables)
    module = importlib.import_module("checkout.handler")
    real_table = tables.Table("Reservations")
    stale = real_table.get_item(Key={"reservation_id": "r"})
    original = module._reservations_table

    def interleaved_read(**kwargs):
        monkeypatch.setattr(module, "_reservations_table", original)
        assert checkout(event({"reservation_id": "r"}), None)["statusCode"] == 200
        return stale

    monkeypatch.setattr(module, "_reservations_table", lambda: Mock(get_item=interleaved_read))
    assert checkout(event({"reservation_id": "r"}), None)["statusCode"] == 200
    assert tables.Table("Orders").scan()["Count"] == 1


def test_checkout_order_failure_rolls_back_consumption(tables, monkeypatch):
    reservation(tables)
    client = boto3.client("dynamodb")
    real_write = client.transact_write_items

    def fail_order(**kwargs):
        kwargs["TransactItems"][1]["Put"]["ConditionExpression"] = "attribute_exists(order_id)"
        return real_write(**kwargs)

    monkeypatch.setattr(client, "transact_write_items", fail_order)
    module = importlib.import_module("checkout.handler")
    monkeypatch.setattr(module.boto3, "client", lambda *a, **kw: client)
    assert checkout(event({"reservation_id": "r"}), None)["statusCode"] == 409
    assert tables.Table("Reservations").get_item(Key={"reservation_id": "r"})["Item"]["status"] == "active"
    assert tables.Table("Orders").scan()["Count"] == 0


@pytest.mark.parametrize("fn,key", [(cart, "product_id"), (checkout, "reservation_id")])
@pytest.mark.parametrize("payload", ["{", "[]", "null", "{}", '{"ID": null}'])
def test_invalid_request_is_400(fn, key, payload):
    request = event()
    request["body"] = payload.replace("ID", key)
    assert fn(request, None)["statusCode"] == 400


def test_reset_validates_all_products_before_deleting(tables, admin_secret):
    reservation(tables)
    item = product(tables)
    item["price"] = 10
    request = event({"products": [item, {"product_id": "bad"}]})
    request["headers"] = {"x-admin-token": admin_secret}
    assert reset(request, None)["statusCode"] == 400
    assert tables.Table("Reservations").scan()["Count"] == 1


def test_catalog_reads_subsequent_query_pages(tables, monkeypatch):
    item = product(tables)
    table = Mock()
    table.query.side_effect = [{"Items": [item], "LastEvaluatedKey": {"product_id": "p"}},
                               {"Items": [{**item, "product_id": "p2"}]}]
    monkeypatch.setattr(importlib.import_module("catalog.handler"), "_table", lambda: table)
    result = catalog(event(route="GET /products"), None)
    assert [p["product_id"] for p in json.loads(result["body"])] == ["p", "p2"]
    assert table.query.call_args.kwargs["ExclusiveStartKey"] == {"product_id": "p"}


def test_logs_do_not_expose_session_token(capsys):
    from common.logging import log_request
    log_request(route="r", method="GET", status=200, start_time=time.time(),
                session_id="secret-session", product_id=None, outcome="ok", request_id="id")
    output = capsys.readouterr().out
    assert "secret-session" not in output
    assert len(json.loads(output)["session_id"]) == 64
