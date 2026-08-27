# Phase 1 Drop App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the serverless "drop" target app (API Gateway HTTP API + Lambda authorizer + catalog/cart/checkout/admin handlers + 4 DynamoDB tables), deployed by a new `infra/modules/app/` Terraform module, so later phases have a real contention-driven app to attack, log, and defend.

**Architecture:** Five Python Lambda handlers under `app/` (`authorizer`, `catalog`, `cart`, `checkout`, `admin`) share `app/common/` helpers for JSON responses and structured logging. Each handler is tested in isolation with `pytest` + `moto` (mocked DynamoDB/SSM) before any Terraform is written. Terraform then wires the same handlers behind an HTTP API with a Lambda REQUEST authorizer, one least-privilege IAM role per function, and stage access logging.

**Tech Stack:** Python 3.12, boto3, pytest, moto, Terraform >= 1.6, AWS provider ~> 5.0 (matches `infra/envs/dev/versions.tf`).

**Spec:** `docs/superpowers/specs/2026-06-03-phase-1-drop-app-design.md`

## Global Constraints

- Per-function least privilege: each Lambda's IAM role touches only the tables/actions listed in the spec's Security section — verify every `aws_iam_role_policy` against that table before moving on.
- Catalog's IAM policy is `GetItem`/`Query` only — **no `Scan`**. Since `GET /products` must list all products, `Products` gets a GSI (`catalog-index`, hash key `catalog_pk`, constant value `"PRODUCT"`) so listing is a `Query`, not a `Scan`. This is a deviation from a literal reading of the data model table (which didn't mention this GSI) but is required to satisfy the spec's own IAM constraint — call it out in the Task 7 commit message.
- Admin secret is never created by Terraform (never appears in tfvars/state): the module only declares the SSM parameter *name* (`var.admin_secret_param_name`); the value is put out-of-band via `aws ssm put-parameter ... --type SecureString`.
- Structured JSON log line per request: `ts, session_id, route, method, status, latency_ms, product_id, outcome` — every handler emits exactly this shape via `app/common/logging.py`.
- Resource naming prefix: `botdef-` (matches Phase 0's `botdef-github-actions-deploy`, `botdef-zero-spend-guard`).
- New Terraform must pass `terraform fmt -check -recursive infra/`, `checkov -d infra/`, `trivy config infra/` clean or carry justified inline skips in the Phase 0 style (see `infra/envs/dev/main.tf:12-23`).
- TDD: for every handler, the test is written and run-to-fail before the implementation.

---

## File Structure

```
app/
  common/
    responses.py       # json_response() — shared by all handlers
    logging.py          # log_request() — structured JSON log line
  authorizer/
    handler.py           # mints/validates anonymous session
  catalog/
    handler.py           # GET /products, GET /products/{id}
  cart/
    handler.py           # POST /cart
  checkout/
    handler.py           # POST /checkout
  admin/
    handler.py           # POST /admin/reset
  tests/
    conftest.py           # moto fixtures: aws creds, dynamodb tables, ssm param
    test_authorizer.py
    test_catalog.py
    test_cart.py
    test_cart_race.py     # the oversell race test
    test_checkout.py
    test_admin.py
  requirements.txt
  pytest.ini
infra/modules/app/
  variables.tf
  dynamodb.tf
  iam.tf
  lambda.tf
  api_gateway.tf
  outputs.tf
infra/envs/dev/
  main.tf                 # + module "app" block
  outputs.tf               # + api_endpoint output
```

---

### Task 1: Shared helpers and test scaffolding

**Files:**
- Create: `app/common/responses.py`
- Create: `app/common/logging.py`
- Create: `app/requirements.txt`
- Create: `app/pytest.ini`
- Create: `app/tests/conftest.py`
- Test: `app/tests/test_responses_and_logging.py`

**Interfaces:**
- Produces: `json_response(status: int, body, headers: dict | None = None) -> dict` (API Gateway HTTP API v2.0 proxy response shape).
- Produces: `log_request(*, route: str, method: str, status: int, start_time: float, session_id: str | None, product_id: str | None, outcome: str) -> None` (prints one JSON line to stdout).
- Produces fixtures (all in `app/tests/conftest.py`): `aws_credentials` (autouse), `aws` (yields inside a single `moto.mock_aws()` context), `tables` (depends on `aws`, creates `Sessions`/`Products`/`Reservations`/`Orders`, sets their env-var names, returns the `boto3.resource("dynamodb")`), `admin_secret` (depends on `aws`, puts `/botdef/admin-secret` = `"test-secret"` as SecureString, sets `ADMIN_SECRET_PARAM` env var, returns the string `"test-secret"`).

- [ ] **Step 1: Write the failing test**

```python
# app/tests/test_responses_and_logging.py
from __future__ import annotations

import json

from common.responses import json_response
from common.logging import log_request


def test_json_response_shape():
    result = json_response(201, {"reservation_id": "abc"})
    assert result["statusCode"] == 201
    assert result["headers"]["Content-Type"] == "application/json"
    assert json.loads(result["body"]) == {"reservation_id": "abc"}


def test_log_request_emits_expected_fields(capsys):
    log_request(
        route="POST /cart",
        method="POST",
        status=201,
        start_time=0.0,
        session_id="sess-1",
        product_id="prod-1",
        outcome="reserved",
    )
    line = json.loads(capsys.readouterr().out.strip())
    assert set(line.keys()) == {
        "ts", "session_id", "route", "method", "status",
        "latency_ms", "product_id", "outcome",
    }
    assert line["route"] == "POST /cart"
    assert line["outcome"] == "reserved"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_responses_and_logging.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'common'`

- [ ] **Step 3: Write `app/pytest.ini` and `app/requirements.txt`**

```ini
# app/pytest.ini
[pytest]
pythonpath = .
testpaths = tests
```

```
# app/requirements.txt
boto3>=1.34
pytest>=7.4
moto[dynamodb,ssm]>=5.0
```

```bash
cd app && pip install -r requirements.txt
```

- [ ] **Step 4: Write `app/common/responses.py`**

```python
from __future__ import annotations

import json
from typing import Any


def json_response(status: int, body: Any, headers: dict | None = None) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **(headers or {})},
        "body": json.dumps(body),
    }
```

- [ ] **Step 5: Write `app/common/logging.py`**

```python
from __future__ import annotations

import json
import time


def log_request(
    *,
    route: str,
    method: str,
    status: int,
    start_time: float,
    session_id: str | None,
    product_id: str | None,
    outcome: str,
) -> None:
    print(json.dumps({
        "ts": time.time(),
        "session_id": session_id,
        "route": route,
        "method": method,
        "status": status,
        "latency_ms": round((time.time() - start_time) * 1000, 2),
        "product_id": product_id,
        "outcome": outcome,
    }))
```

- [ ] **Step 6: Write `app/tests/conftest.py`**

```python
from __future__ import annotations

import os

import boto3
import pytest
from moto import mock_aws


@pytest.fixture(autouse=True)
def aws_credentials():
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture
def aws(aws_credentials):
    with mock_aws():
        yield


@pytest.fixture
def tables(aws):
    os.environ["SESSIONS_TABLE"] = "Sessions"
    os.environ["PRODUCTS_TABLE"] = "Products"
    os.environ["RESERVATIONS_TABLE"] = "Reservations"
    os.environ["ORDERS_TABLE"] = "Orders"

    ddb = boto3.resource("dynamodb", region_name="us-east-1")

    ddb.create_table(
        TableName="Sessions",
        KeySchema=[{"AttributeName": "session_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "session_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName="Products",
        KeySchema=[{"AttributeName": "product_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "product_id", "AttributeType": "S"},
            {"AttributeName": "catalog_pk", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "catalog-index",
            "KeySchema": [{"AttributeName": "catalog_pk", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName="Reservations",
        KeySchema=[{"AttributeName": "reservation_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "reservation_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    ddb.create_table(
        TableName="Orders",
        KeySchema=[{"AttributeName": "order_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "order_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb


@pytest.fixture
def admin_secret(aws):
    os.environ["ADMIN_SECRET_PARAM"] = "/botdef/admin-secret"
    client = boto3.client("ssm", region_name="us-east-1")
    client.put_parameter(Name="/botdef/admin-secret", Value="test-secret", Type="SecureString")
    return "test-secret"
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd app && python -m pytest tests/test_responses_and_logging.py -v`
Expected: PASS (2 tests)

- [ ] **Step 8: Commit**

```bash
git add app/common app/requirements.txt app/pytest.ini app/tests/conftest.py app/tests/test_responses_and_logging.py
git commit -m "feat(app): add shared response/logging helpers and moto test scaffolding"
```

---

### Task 2: Authorizer Lambda (session mint/validate)

**Files:**
- Create: `app/authorizer/handler.py`
- Test: `app/tests/test_authorizer.py`

**Interfaces:**
- Consumes: `os.environ["SESSIONS_TABLE"]` (set by `tables` fixture / Terraform env var).
- Produces: `handler(event: dict, context) -> dict` returning `{"isAuthorized": bool, "context": {"session_id": str, "is_new_session": "true"|"false"}}` on success, or `{"isAuthorized": False}` when the `session_id` cookie fails the UUID4 format check. Downstream handlers read `event["requestContext"]["authorizer"]["lambda"]["session_id"]`.

- [ ] **Step 1: Write the failing test**

```python
# app/tests/test_authorizer.py
from __future__ import annotations

from authorizer.handler import handler


def _event(cookie: str | None) -> dict:
    return {"cookies": [cookie] if cookie else []}


def test_mints_new_session_when_no_cookie(tables):
    result = handler(_event(None), None)
    assert result["isAuthorized"] is True
    assert result["context"]["is_new_session"] == "true"
    session_id = result["context"]["session_id"]

    item = tables.Table("Sessions").get_item(Key={"session_id": session_id})["Item"]
    assert item["request_count"] == 1


def test_reuses_valid_existing_session_and_increments_request_count(tables):
    first = handler(_event(None), None)
    session_id = first["context"]["session_id"]

    second = handler(_event(f"session_id={session_id}"), None)
    assert second["isAuthorized"] is True
    assert second["context"]["is_new_session"] == "false"
    assert second["context"]["session_id"] == session_id

    item = tables.Table("Sessions").get_item(Key={"session_id": session_id})["Item"]
    assert item["request_count"] == 2


def test_rejects_malformed_session_cookie(tables):
    result = handler(_event("session_id=not-a-uuid"), None)
    assert result == {"isAuthorized": False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_authorizer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'authorizer'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/authorizer/handler.py
from __future__ import annotations

import os
import re
import time
import uuid

import boto3

SESSION_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
SESSION_TTL_SECONDS = 3600


def _table():
    return boto3.resource("dynamodb").Table(os.environ["SESSIONS_TABLE"])


def _extract_session_id(event: dict) -> str | None:
    for cookie in event.get("cookies") or []:
        name, _, value = cookie.partition("=")
        if name == "session_id":
            return value
    return None


def handler(event: dict, context) -> dict:
    session_id = _extract_session_id(event)

    if session_id is not None and not SESSION_ID_RE.match(session_id):
        return {"isAuthorized": False}

    table = _table()
    now = int(time.time())

    if session_id is not None:
        existing = table.get_item(Key={"session_id": session_id}).get("Item")
        if existing is not None:
            table.update_item(
                Key={"session_id": session_id},
                UpdateExpression="SET request_count = request_count + :one",
                ExpressionAttributeValues={":one": 1},
            )
            return {
                "isAuthorized": True,
                "context": {"session_id": session_id, "is_new_session": "false"},
            }

    session_id = session_id or str(uuid.uuid4())
    table.put_item(Item={
        "session_id": session_id,
        "created_at": now,
        "ttl": now + SESSION_TTL_SECONDS,
        "request_count": 1,
    })
    return {
        "isAuthorized": True,
        "context": {"session_id": session_id, "is_new_session": "true"},
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m pytest tests/test_authorizer.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/authorizer app/tests/test_authorizer.py
git commit -m "feat(app): add session authorizer Lambda"
```

---

### Task 3: Catalog Lambda (GET /products, GET /products/{id})

**Files:**
- Create: `app/catalog/handler.py`
- Test: `app/tests/test_catalog.py`

**Interfaces:**
- Consumes: `os.environ["PRODUCTS_TABLE"]`; `event["routeKey"]` (`"GET /products"` or `"GET /products/{id}"`); `event["pathParameters"]["id"]` for detail; `event["requestContext"]["authorizer"]["lambda"]["session_id"]`.
- Produces: `handler(event: dict, context) -> dict`. Product items carry a `catalog_pk` attribute (constant `"PRODUCT"`) so listing can `Query` the `catalog-index` GSI instead of `Scan` (see Global Constraints).

- [ ] **Step 1: Write the failing test**

```python
# app/tests/test_catalog.py
from __future__ import annotations

import time

from catalog.handler import handler


def _seed(tables, *, drop_at: int, stock: int = 5):
    tables.Table("Products").put_item(Item={
        "product_id": "prod-1",
        "catalog_pk": "PRODUCT",
        "title": "Elite Trainer Box",
        "price": 49.99,
        "stock": stock,
        "total_units": stock,
        "drop_at": drop_at,
    })


def _event(route_key: str, path_id: str | None = None) -> dict:
    event = {
        "routeKey": route_key,
        "requestContext": {"authorizer": {"lambda": {"session_id": "sess-1"}}},
    }
    if path_id is not None:
        event["pathParameters"] = {"id": path_id}
    return event


def test_list_before_drop_hides_stock_and_shows_upcoming(tables):
    _seed(tables, drop_at=int(time.time()) + 3600)
    result = handler(_event("GET /products"), None)
    assert result["statusCode"] == 200
    import json
    body = json.loads(result["body"])
    assert body[0]["status"] == "upcoming"
    assert "stock" not in body[0]


def test_list_after_drop_shows_live_stock(tables):
    _seed(tables, drop_at=int(time.time()) - 10, stock=3)
    result = handler(_event("GET /products"), None)
    import json
    body = json.loads(result["body"])
    assert body[0]["status"] == "live"
    assert body[0]["stock"] == 3


def test_detail_not_found_returns_404(tables):
    result = handler(_event("GET /products/{id}", path_id="missing"), None)
    assert result["statusCode"] == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'catalog'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/catalog/handler.py
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
        "price": item["price"],
        "drop_at": int(item["drop_at"]),
    }
    if dropped:
        out["status"] = "live"
        out["stock"] = item["stock"]
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m pytest tests/test_catalog.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/catalog app/tests/test_catalog.py
git commit -m "feat(app): add catalog Lambda (list via GSI query, detail via get_item)"
```

---

### Task 4: Cart Lambda (POST /cart) + concurrent oversell race test

**Files:**
- Create: `app/cart/handler.py`
- Test: `app/tests/test_cart.py`
- Test: `app/tests/test_cart_race.py`

**Interfaces:**
- Consumes: `os.environ["PRODUCTS_TABLE"]`, `os.environ["RESERVATIONS_TABLE"]`; `event["body"]` (JSON `{"product_id": str}`); `event["requestContext"]["authorizer"]["lambda"]["session_id"]`.
- Produces: `handler(event: dict, context) -> dict`. `201` with `{"reservation_id": str}` on success; `404 not_found`; `425 too_early` with `{"drop_at": int}`; `409 sold_out`.

- [ ] **Step 1: Write the failing tests**

```python
# app/tests/test_cart.py
from __future__ import annotations

import json
import time

from cart.handler import handler


def _seed(tables, *, drop_at: int, stock: int = 1):
    tables.Table("Products").put_item(Item={
        "product_id": "prod-1",
        "catalog_pk": "PRODUCT",
        "title": "Elite Trainer Box",
        "price": 49.99,
        "stock": stock,
        "total_units": stock,
        "drop_at": drop_at,
    })


def _event(product_id: str, session_id: str = "sess-1") -> dict:
    return {
        "body": json.dumps({"product_id": product_id}),
        "requestContext": {"authorizer": {"lambda": {"session_id": session_id}}},
    }


def test_cart_too_early_returns_425(tables):
    _seed(tables, drop_at=int(time.time()) + 3600)
    result = handler(_event("prod-1"), None)
    assert result["statusCode"] == 425


def test_cart_reserves_and_decrements_stock(tables):
    _seed(tables, drop_at=int(time.time()) - 10, stock=1)
    result = handler(_event("prod-1"), None)
    assert result["statusCode"] == 201
    reservation_id = json.loads(result["body"])["reservation_id"]

    product = tables.Table("Products").get_item(Key={"product_id": "prod-1"})["Item"]
    assert product["stock"] == 0

    reservation = tables.Table("Reservations").get_item(Key={"reservation_id": reservation_id})["Item"]
    assert reservation["session_id"] == "sess-1"
    assert reservation["status"] == "active"


def test_cart_sold_out_returns_409(tables):
    _seed(tables, drop_at=int(time.time()) - 10, stock=0)
    result = handler(_event("prod-1"), None)
    assert result["statusCode"] == 409


def test_cart_unknown_product_returns_404(tables):
    result = handler(_event("missing"), None)
    assert result["statusCode"] == 404
```

```python
# app/tests/test_cart_race.py
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor

from cart.handler import handler


def test_concurrent_cart_requests_exactly_one_success(tables):
    tables.Table("Products").put_item(Item={
        "product_id": "prod-1",
        "catalog_pk": "PRODUCT",
        "title": "Elite Trainer Box",
        "price": 49.99,
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd app && python -m pytest tests/test_cart.py tests/test_cart_race.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cart'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/cart/handler.py
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
    product_id = json.loads(event.get("body") or "{}").get("product_id")
    now = int(time.time())

    products = _products_table()
    product = products.get_item(Key={"product_id": product_id}).get("Item")

    if product is None:
        result = json_response(404, {"error": "not_found"})
        log_request(route="POST /cart", method="POST", status=404, start_time=start,
                    session_id=session_id, product_id=product_id, outcome="not_found")
        return result

    if now < int(product["drop_at"]):
        result = json_response(425, {"error": "too_early", "drop_at": int(product["drop_at"])})
        log_request(route="POST /cart", method="POST", status=425, start_time=start,
                    session_id=session_id, product_id=product_id, outcome="too_early")
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
                        session_id=session_id, product_id=product_id, outcome="sold_out")
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
                session_id=session_id, product_id=product_id, outcome="reserved")
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd app && python -m pytest tests/test_cart.py tests/test_cart_race.py -v`
Expected: PASS (5 tests). The race test is the proof that the conditional `UpdateItem` prevents oversell — if it flakes, do not weaken the assertion; investigate the conditional expression first.

- [ ] **Step 5: Commit**

```bash
git add app/cart app/tests/test_cart.py app/tests/test_cart_race.py
git commit -m "feat(app): add cart Lambda with atomic-decrement oversell protection"
```

---

### Task 5: Checkout Lambda (POST /checkout)

**Files:**
- Create: `app/checkout/handler.py`
- Test: `app/tests/test_checkout.py`

**Interfaces:**
- Consumes: `os.environ["RESERVATIONS_TABLE"]`, `os.environ["ORDERS_TABLE"]`; `event["body"]` (JSON `{"reservation_id": str}`); `event["requestContext"]["authorizer"]["lambda"]["session_id"]`.
- Produces: `handler(event: dict, context) -> dict`. `200` with `{"order_id": str}`; `404 not_found` (missing or wrong session); `410 expired` (consumed or TTL passed).

- [ ] **Step 1: Write the failing test**

```python
# app/tests/test_checkout.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_checkout.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'checkout'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/checkout/handler.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m pytest tests/test_checkout.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/checkout app/tests/test_checkout.py
git commit -m "feat(app): add checkout Lambda with reservation ownership/expiry checks"
```

---

### Task 6: Admin Lambda (POST /admin/reset)

**Files:**
- Create: `app/admin/handler.py`
- Test: `app/tests/test_admin.py`

**Interfaces:**
- Consumes: `os.environ["PRODUCTS_TABLE"]`, `os.environ["RESERVATIONS_TABLE"]`, `os.environ["ORDERS_TABLE"]`, `os.environ["ADMIN_SECRET_PARAM"]`; `event["headers"]["x-admin-token"]`; `event["body"]` (JSON `{"products": [{"product_id", "title", "price", "stock", "drop_at"}]}`).
- Produces: `handler(event: dict, context) -> dict`. `401 unauthorized` on bad token; `200` with `{"reset": <count>}` on success. Seeded products carry `catalog_pk="PRODUCT"` so Task 3's catalog Query keeps working after a reset.

- [ ] **Step 1: Write the failing test**

```python
# app/tests/test_admin.py
from __future__ import annotations

import json
import time

from admin.handler import handler


def _event(token: str | None, products: list[dict]) -> dict:
    headers = {"x-admin-token": token} if token else {}
    return {"headers": headers, "body": json.dumps({"products": products})}


def test_admin_rejects_wrong_token(tables, admin_secret):
    result = handler(_event("wrong-token", []), None)
    assert result["statusCode"] == 401


def test_admin_reset_reseeds_products_and_clears_reservations_orders(tables, admin_secret):
    tables.Table("Reservations").put_item(Item={
        "reservation_id": "res-old", "product_id": "prod-old",
        "session_id": "sess-old", "ttl": 0, "status": "active",
    })
    tables.Table("Orders").put_item(Item={
        "order_id": "order-old", "reservation_id": "res-old",
        "product_id": "prod-old", "session_id": "sess-old", "created_at": 0,
    })

    drop_at = int(time.time()) + 3600
    result = handler(_event(admin_secret, [
        {"product_id": "prod-1", "title": "Elite Trainer Box", "price": 49.99, "stock": 5, "drop_at": drop_at},
    ]), None)

    assert result["statusCode"] == 200
    assert json.loads(result["body"]) == {"reset": 1}

    product = tables.Table("Products").get_item(Key={"product_id": "prod-1"})["Item"]
    assert product["stock"] == 5
    assert product["catalog_pk"] == "PRODUCT"

    assert "Item" not in tables.Table("Reservations").get_item(Key={"reservation_id": "res-old"})
    assert "Item" not in tables.Table("Orders").get_item(Key={"order_id": "order-old"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_admin.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'admin'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/admin/handler.py
from __future__ import annotations

import json
import os
import time

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
        products_table.put_item(Item={
            "product_id": product["product_id"],
            "catalog_pk": "PRODUCT",
            "title": product["title"],
            "price": product["price"],
            "stock": product["stock"],
            "total_units": product["stock"],
            "drop_at": product["drop_at"],
        })

    result = json_response(200, {"reset": len(products)})
    log_request(route="POST /admin/reset", method="POST", status=200, start_time=start,
                session_id=None, product_id=None, outcome="ok")
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m pytest tests/test_admin.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full app test suite**

Run: `cd app && python -m pytest -v`
Expected: PASS (all tests from Tasks 1-6, ~18 tests total)

- [ ] **Step 6: Commit**

```bash
git add app/admin app/tests/test_admin.py
git commit -m "feat(app): add admin reset Lambda with SSM-backed token check"
```

---

### Task 7: Terraform module `infra/modules/app/`

**Files:**
- Create: `infra/modules/app/variables.tf`
- Create: `infra/modules/app/dynamodb.tf`
- Create: `infra/modules/app/iam.tf`
- Create: `infra/modules/app/lambda.tf`
- Create: `infra/modules/app/api_gateway.tf`
- Create: `infra/modules/app/outputs.tf`

**Interfaces:**
- Consumes: nothing outside this module (it is composed by Task 8).
- Produces: `module.app.api_endpoint` (invoke URL), `module.app.admin_secret_param_name` (SSM parameter name to populate out-of-band).

- [ ] **Step 1: Write `infra/modules/app/variables.tf`**

```hcl
variable "environment" {
  description = "Environment name (e.g. dev), used only for tagging via the caller's default_tags."
  type        = string
}

variable "admin_secret_param_name" {
  description = "SSM Parameter Store path for the admin secret. Terraform declares the name only — the value is put out-of-band (never in tfvars/state): aws ssm put-parameter --name <this> --type SecureString --value <secret>."
  type        = string
  default     = "/botdef/admin-secret"
}
```

- [ ] **Step 2: Write `infra/modules/app/dynamodb.tf`**

```hcl
resource "aws_dynamodb_table" "sessions" {
  name         = "botdef-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"

  attribute {
    name = "session_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }
}

# catalog_pk is a constant ("PRODUCT") on every item so GET /products can
# Query the catalog-index GSI instead of Scan — catalog-fn's IAM policy
# grants Query but not Scan (see spec Security section + plan Task 3).
resource "aws_dynamodb_table" "products" {
  name         = "botdef-products"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "product_id"

  attribute {
    name = "product_id"
    type = "S"
  }

  attribute {
    name = "catalog_pk"
    type = "S"
  }

  global_secondary_index {
    name            = "catalog-index"
    hash_key        = "catalog_pk"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "reservations" {
  name         = "botdef-reservations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "reservation_id"

  attribute {
    name = "reservation_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "orders" {
  name         = "botdef-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "order_id"

  attribute {
    name = "order_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }
}
```

- [ ] **Step 3: Write `infra/modules/app/iam.tf`**

```hcl
data "aws_iam_policy_document" "lambda_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

locals {
  logs_statement = {
    Effect   = "Allow"
    Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    Resource = "*"
  }
}

# --- authorizer: PutItem/UpdateItem/GetItem on Sessions only ---
resource "aws_iam_role" "authorizer" {
  name               = "botdef-fn-authorizer"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy" "authorizer" {
  name = "botdef-fn-authorizer-policy"
  role = aws_iam_role.authorizer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.sessions.arn
      },
      local.logs_statement,
    ]
  })
}

# --- catalog: GetItem/Query on Products (+ its GSI) only ---
resource "aws_iam_role" "catalog" {
  name               = "botdef-fn-catalog"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy" "catalog" {
  name = "botdef-fn-catalog-policy"
  role = aws_iam_role.catalog.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["dynamodb:GetItem", "dynamodb:Query"]
        Resource = [
          aws_dynamodb_table.products.arn,
          "${aws_dynamodb_table.products.arn}/index/*",
        ]
      },
      local.logs_statement,
    ]
  })
}

# --- cart: GetItem/UpdateItem on Products + PutItem on Reservations ---
resource "aws_iam_role" "cart" {
  name               = "botdef-fn-cart"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy" "cart" {
  name = "botdef-fn-cart-policy"
  role = aws_iam_role.cart.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.products.arn
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.reservations.arn
      },
      local.logs_statement,
    ]
  })
}

# --- checkout: GetItem/UpdateItem on Reservations + PutItem on Orders ---
resource "aws_iam_role" "checkout" {
  name               = "botdef-fn-checkout"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy" "checkout" {
  name = "botdef-fn-checkout-policy"
  role = aws_iam_role.checkout.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.reservations.arn
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.orders.arn
      },
      local.logs_statement,
    ]
  })
}

# --- admin: write Products, delete/scan Reservations+Orders, read the admin secret ---
resource "aws_iam_role" "admin" {
  name               = "botdef-fn-admin"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy" "admin" {
  name = "botdef-fn-admin-policy"
  role = aws_iam_role.admin.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.products.arn
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:Scan", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem"]
        Resource = [aws_dynamodb_table.reservations.arn, aws_dynamodb_table.orders.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = "arn:aws:ssm:*:*:parameter${var.admin_secret_param_name}"
      },
      local.logs_statement,
    ]
  })
}
```

- [ ] **Step 4: Write `infra/modules/app/lambda.tf`**

```hcl
data "archive_file" "app" {
  type        = "zip"
  source_dir  = "${path.module}/../../../app"
  output_path = "${path.module}/build/app.zip"
  excludes    = ["tests", "requirements.txt", "pytest.ini", "README.md"]
}

locals {
  common_env = {
    SESSIONS_TABLE     = aws_dynamodb_table.sessions.name
    PRODUCTS_TABLE     = aws_dynamodb_table.products.name
    RESERVATIONS_TABLE = aws_dynamodb_table.reservations.name
    ORDERS_TABLE       = aws_dynamodb_table.orders.name
    ADMIN_SECRET_PARAM = var.admin_secret_param_name
  }
}

resource "aws_lambda_function" "authorizer" {
  function_name    = "botdef-fn-authorizer"
  role             = aws_iam_role.authorizer.arn
  handler          = "authorizer.handler.handler"
  runtime          = "python3.12"
  timeout          = 5
  filename         = data.archive_file.app.output_path
  source_code_hash = data.archive_file.app.output_base64sha256

  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "catalog" {
  function_name    = "botdef-fn-catalog"
  role             = aws_iam_role.catalog.arn
  handler          = "catalog.handler.handler"
  runtime          = "python3.12"
  timeout          = 5
  filename         = data.archive_file.app.output_path
  source_code_hash = data.archive_file.app.output_base64sha256

  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "cart" {
  function_name    = "botdef-fn-cart"
  role             = aws_iam_role.cart.arn
  handler          = "cart.handler.handler"
  runtime          = "python3.12"
  timeout          = 5
  filename         = data.archive_file.app.output_path
  source_code_hash = data.archive_file.app.output_base64sha256

  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "checkout" {
  function_name    = "botdef-fn-checkout"
  role             = aws_iam_role.checkout.arn
  handler          = "checkout.handler.handler"
  runtime          = "python3.12"
  timeout          = 5
  filename         = data.archive_file.app.output_path
  source_code_hash = data.archive_file.app.output_base64sha256

  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "admin" {
  function_name    = "botdef-fn-admin"
  role             = aws_iam_role.admin.arn
  handler          = "admin.handler.handler"
  runtime          = "python3.12"
  timeout          = 5
  filename         = data.archive_file.app.output_path
  source_code_hash = data.archive_file.app.output_base64sha256

  environment {
    variables = local.common_env
  }
}
```

- [ ] **Step 5: Write `infra/modules/app/api_gateway.tf`**

```hcl
resource "aws_apigatewayv2_api" "app" {
  name          = "botdef-app"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_authorizer" "session" {
  api_id                            = aws_apigatewayv2_api.app.id
  name                               = "botdef-session-authorizer"
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = aws_lambda_function.authorizer.invoke_arn
  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
  identity_sources                  = ["$request.header.Cookie"]
}

resource "aws_lambda_permission" "authorizer_invoke" {
  statement_id  = "AllowAPIGatewayInvokeAuthorizer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.authorizer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.app.execution_arn}/*/*"
}

locals {
  routes = {
    catalog_list   = { key = "GET /products", fn = aws_lambda_function.catalog }
    catalog_detail = { key = "GET /products/{id}", fn = aws_lambda_function.catalog }
    cart           = { key = "POST /cart", fn = aws_lambda_function.cart }
    checkout       = { key = "POST /checkout", fn = aws_lambda_function.checkout }
    admin_reset    = { key = "POST /admin/reset", fn = aws_lambda_function.admin }
  }
}

resource "aws_apigatewayv2_integration" "fn" {
  for_each                = local.routes
  api_id                   = aws_apigatewayv2_api.app.id
  integration_type         = "AWS_PROXY"
  integration_uri          = each.value.fn.invoke_arn
  payload_format_version   = "2.0"
}

resource "aws_apigatewayv2_route" "fn" {
  for_each           = local.routes
  api_id             = aws_apigatewayv2_api.app.id
  route_key          = each.value.key
  target             = "integrations/${aws_apigatewayv2_integration.fn[each.key].id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.session.id
}

resource "aws_lambda_permission" "fn_invoke" {
  for_each      = local.routes
  statement_id  = "AllowAPIGatewayInvoke${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = each.value.fn.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.app.execution_arn}/*/*"
}

resource "aws_cloudwatch_log_group" "access_logs" {
  name              = "/botdef/app/access-logs"
  retention_in_days = 30
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.app.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access_logs.arn
    format = jsonencode({
      requestId       = "$context.requestId"
      ip               = "$context.identity.sourceIp"
      requestTime      = "$context.requestTime"
      httpMethod       = "$context.httpMethod"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      responseLatency  = "$context.responseLatency"
    })
  }
}
```

- [ ] **Step 6: Write `infra/modules/app/outputs.tf`**

```hcl
output "api_endpoint" {
  description = "Invoke URL for the drop app HTTP API."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "admin_secret_param_name" {
  description = "SSM parameter name to populate out-of-band: aws ssm put-parameter --name <this> --type SecureString --value <secret>."
  value       = var.admin_secret_param_name
}
```

- [ ] **Step 7: Validate the module in isolation**

Run: `cd infra/modules/app && terraform fmt -check && terraform init -backend=false && terraform validate`
Expected: `terraform fmt -check` prints nothing (already formatted); `terraform validate` reports `Success! The configuration is valid.`

- [ ] **Step 8: Commit**

```bash
git add infra/modules/app
git commit -m "feat(infra): add app module — HTTP API, session authorizer, 5 least-privilege Lambda roles, 4 DynamoDB tables"
```

---

### Task 8: Compose the module into `infra/envs/dev`

**Files:**
- Modify: `infra/envs/dev/main.tf`
- Modify: `infra/envs/dev/outputs.tf`

**Interfaces:**
- Consumes: `module.app.api_endpoint`, `module.app.admin_secret_param_name` (from Task 7).

- [ ] **Step 1: Append the module block to `infra/envs/dev/main.tf`**

Add after the existing `aws_budgets_budget.zero_spend` resource:

```hcl
# ---------------------------------------------------------------------------
# Phase 1: the "drop" target app that later phases attack, log, and defend.
# ---------------------------------------------------------------------------
module "app" {
  source      = "../../modules/app"
  environment = "dev"
}
```

- [ ] **Step 2: Append the output to `infra/envs/dev/outputs.tf`**

```hcl
output "app_api_endpoint" {
  description = "Invoke URL for the Phase 1 drop app. GET <this>/products to smoke-test."
  value       = module.app.api_endpoint
}

output "app_admin_secret_param_name" {
  description = "Populate this SSM parameter out-of-band before calling POST /admin/reset: aws ssm put-parameter --name <this> --type SecureString --value <secret>."
  value       = module.app.admin_secret_param_name
}
```

- [ ] **Step 3: Validate the composed environment**

Run: `cd infra/envs/dev && terraform fmt -check -recursive .. && terraform init -backend=false && terraform validate`
Expected: `terraform fmt -check` prints nothing; `terraform validate` reports `Success! The configuration is valid.`

- [ ] **Step 4: Commit**

```bash
git add infra/envs/dev/main.tf infra/envs/dev/outputs.tf
git commit -m "feat(infra): compose the app module into the dev environment"
```

---

### Task 9: Full verification against the spec's Definition of Done

**Files:** none (verification only — fix forward in the relevant task's files if something fails).

- [ ] **Step 1: Run the full Python test suite**

Run: `cd app && python -m pytest -v`
Expected: all tests pass, including `test_concurrent_cart_requests_exactly_one_success`.

- [ ] **Step 2: Run Terraform formatting and validation across all of `infra/`**

Run: `terraform fmt -check -recursive infra/`
Expected: no output (already formatted). If it prints filenames, run `terraform fmt -recursive infra/` and re-check.

- [ ] **Step 3: Run Checkov**

Run: `checkov -d infra/ --compact`
Expected: no new HIGH/CRITICAL findings introduced by `infra/modules/app/` or the `infra/envs/dev` composition. If a finding appears (e.g. Lambda without X-Ray tracing, DynamoDB without a customer-managed KMS key), either fix it or add a `#checkov:skip=<ID>:<justification>` comment in the Phase 0 style (`infra/envs/dev/main.tf:19-23`) and note it in this plan's file.

- [ ] **Step 4: Run Trivy**

Run: `trivy config infra/ --severity HIGH,CRITICAL`
Expected: no new HIGH/CRITICAL findings from the app module. Same skip-and-document policy as Checkov if a finding is a known, accepted tradeoff.

- [ ] **Step 5: Cross-check the spec's Definition of Done checklist**

Confirm each line item from `docs/superpowers/specs/2026-06-03-phase-1-drop-app-design.md` "Definition of done":
- `app/` Python handlers (authorizer, catalog, cart, checkout, admin) implemented with TDD — Tasks 2-6.
- `infra/modules/app/` Terraform: HTTP API, authorizer + 4 handler Lambdas, 5 least-privilege roles, 4 DynamoDB tables, SSM admin-secret param, stage access logging — Task 7.
- Module composed into `infra/envs/dev/main.tf` — Task 8.
- `pytest` green, including the concurrent oversell race test — Step 1 above.
- `terraform fmt -check`, `checkov -d infra/`, `trivy config infra/` pass (or justified skips) — Steps 2-4 above.
- Structured per-request JSON logging present and consistent across all handlers — verify by grepping: `grep -rn "log_request(" app/*/handler.py` should show exactly one call per handler, all importing from `common.logging`.

- [ ] **Step 6: Update the spec status**

Edit `docs/superpowers/specs/2026-06-03-phase-1-drop-app-design.md` line 3 status line to reflect implementation is complete (e.g. `**Status:** implemented`).

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/specs/2026-06-03-phase-1-drop-app-design.md
git commit -m "docs: mark Phase 1 drop app spec as implemented"
```
