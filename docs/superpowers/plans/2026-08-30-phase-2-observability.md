# Phase 2 Observability / SOC Data Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the SOC data plane that turns the Phase 1 drop app's traffic into queryable data: correlate app logs with API Gateway access logs via `request_id`, stream both through CloudWatch subscription filters → Kinesis Firehose → S3, and expose them as two Athena tables (`app_logs`, `apigw_logs`) joinable at query time — via a new `infra/modules/logging/` Terraform module.

**Architecture:** The app's `log_request()` helper gains a `request_id` field (sourced from `event["requestContext"]["requestId"]`, already present on every Lambda invocation) so app-level and edge-level logs correlate. `infra/modules/app/` gets explicit per-function CloudWatch log groups (so subscription filters have something to attach to at `apply` time) and an updated API Gateway access-log format matching the Phase 2 schema. A new `infra/modules/logging/` module owns the S3 bucket, two Firehose delivery streams, the CloudWatch→Firehose subscription filters, and two Terraform-defined (no crawler) Glue/Athena tables. No transform/normalization Lambda — each source keeps its native schema, joined by `request_id` in Athena.

**Tech Stack:** Python 3.12 (app changes only — this phase is Terraform-heavy), Terraform >= 1.6, AWS provider ~> 5.0 (matches `infra/envs/dev/versions.tf`).

**Spec:** `docs/superpowers/specs/2026-08-30-phase-2-observability-design.md`

## Global Constraints

- Log sources: **both** app Lambda logs and API Gateway access logs are captured — do not wait for Phase 3 (CloudFront) to add edge signal.
- Ingestion pattern: CloudWatch Logs subscription filter → Kinesis Firehose → S3. No custom polling/export Lambda.
- Cost is accepted (draws from AWS free-account signup credits, not cash) — same guardrail as Phase 0. Do not add cost-avoidance workarounds (e.g. skip Firehose) that weren't in the approved spec.
- S3 layout: **one** bucket (`botdef-logs-<env>-<account_id>`), two prefixes (`app/`, `apigw/`), each Hive-partitioned by `year/month/day/hour` via Firehose's time-based prefix expressions.
- Athena schema: **two** separate Terraform-defined Glue tables (`app_logs`, `apigw_logs`), joined by `request_id` at query time. No Glue crawler, no merge/transform Lambda.
- Correlation key: `request_id`, added to the app's structured log output, sourced from `event["requestContext"]["requestId"]`.
- Resource naming prefix: `botdef-` (matches all existing phases).
- Live end-to-end verification (real traffic → S3 → Athena query) is **deferred to a manual runbook step** — Phase 1's infra was never actually `terraform apply`'d to a real AWS account (no `backend.hcl`/`terraform.tfvars` exist), so this plan's own verification task is static only: `pytest`, `terraform fmt -check`, `terraform validate`, `checkov`, `trivy`. Do NOT run `terraform apply` as part of this plan.
- New Terraform must pass `terraform fmt -check -recursive infra/`, `checkov -d infra/`, `trivy config infra/` clean or carry justified inline skips in the established style (see `infra/modules/app/dynamodb.tf`, `infra/bootstrap/main.tf`).
- TDD applies to the one Python task (Task 1); Terraform tasks are validated via `terraform validate`, with full static verification in the final task.

---

## File Structure

```
app/
  common/
    logging.py                        # MODIFY: log_request() gains request_id field
  authorizer/handler.py               # MODIFY: extract + pass request_id
  catalog/handler.py                  # MODIFY: extract + pass request_id
  cart/handler.py                     # MODIFY: extract + pass request_id
  checkout/handler.py                 # MODIFY: extract + pass request_id
  admin/handler.py                    # MODIFY: extract + pass request_id
  tests/
    test_responses_and_logging.py     # MODIFY: assert request_id field
infra/modules/app/
  lambda.tf                           # MODIFY: + 5 explicit aws_cloudwatch_log_group resources
  api_gateway.tf                      # MODIFY: access log format -> Phase 2 schema
  outputs.tf                          # MODIFY: + log group name/arn outputs
infra/modules/logging/
  variables.tf                        # environment, app_log_group_names, apigw_log_group_name
  s3.tf                               # logs bucket: versioning, SSE, lifecycle, public-access-block, TLS-only policy
  firehose.tf                         # 2 Firehose delivery streams + delivery IAM role
  subscriptions.tf                    # CloudWatch->Firehose subscription filters + IAM role
  glue.tf                             # Glue database + 2 catalog tables (app_logs, apigw_logs) + Athena workgroup
  outputs.tf                          # logs_bucket_name, athena_workgroup, glue_database
infra/envs/dev/
  main.tf                             # MODIFY: + module "logging" block
  outputs.tf                          # MODIFY: + logs_bucket_name, athena_workgroup outputs
docs/
  phase-2-observability.md            # NEW: runbook (setup, manual live-verification steps, cost notes)
```

---

### Task 1: Add `request_id` to the app's structured logs

**Files:**
- Modify: `app/common/logging.py`
- Modify: `app/authorizer/handler.py`
- Modify: `app/catalog/handler.py`
- Modify: `app/cart/handler.py`
- Modify: `app/checkout/handler.py`
- Modify: `app/admin/handler.py`
- Test: `app/tests/test_responses_and_logging.py`

**Interfaces:**
- Consumes: nothing new — `event["requestContext"]["requestId"]` is already present on every API Gateway HTTP API Lambda event (proxy integration and authorizer events alike).
- Produces: `log_request(*, route: str, method: str, status: int, start_time: float, session_id: str | None, product_id: str | None, outcome: str, request_id: str | None) -> None` — the new `request_id` keyword-only parameter, no default (every call site must pass it explicitly, matching the existing style for `product_id`).

- [ ] **Step 1: Write the failing test**

Replace the existing `test_log_request_emits_expected_fields` in `app/tests/test_responses_and_logging.py` with:

```python
def test_log_request_emits_expected_fields(capsys):
    log_request(
        route="POST /cart",
        method="POST",
        status=201,
        start_time=0.0,
        session_id="sess-1",
        product_id="prod-1",
        outcome="reserved",
        request_id="req-1",
    )
    line = json.loads(capsys.readouterr().out.strip())
    assert set(line.keys()) == {
        "ts", "request_id", "session_id", "route", "method", "status",
        "latency_ms", "product_id", "outcome",
    }
    assert line["request_id"] == "req-1"
    assert line["route"] == "POST /cart"
    assert line["outcome"] == "reserved"
```

(The rest of the file, `test_json_response_shape`, is unchanged.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd app && python -m pytest tests/test_responses_and_logging.py -v`
Expected: FAIL with `TypeError: log_request() missing 1 required keyword-only argument: 'request_id'`

- [ ] **Step 3: Update `app/common/logging.py`**

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
    request_id: str | None,
) -> None:
    print(json.dumps({
        "ts": time.time(),
        "request_id": request_id,
        "session_id": session_id,
        "route": route,
        "method": method,
        "status": status,
        "latency_ms": round((time.time() - start_time) * 1000, 2),
        "product_id": product_id,
        "outcome": outcome,
    }))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd app && python -m pytest tests/test_responses_and_logging.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Update `app/authorizer/handler.py`**

Add one line extracting `request_id` right after `session_id = _extract_session_id(event)`, and pass `request_id=request_id` to all three `log_request(...)` calls in the file:

```python
def handler(event: dict, context) -> dict:
    start = time.time()
    session_id = _extract_session_id(event)
    request_id = event.get("requestContext", {}).get("requestId")

    if session_id is not None and not SESSION_ID_RE.match(session_id):
        log_request(route="authorizer", method="AUTH", status=401, start_time=start,
                    session_id=session_id, product_id=None, outcome="invalid_session",
                    request_id=request_id)
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
            log_request(route="authorizer", method="AUTH", status=200, start_time=start,
                        session_id=session_id, product_id=None, outcome="existing_session",
                        request_id=request_id)
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
    log_request(route="authorizer", method="AUTH", status=200, start_time=start,
                session_id=session_id, product_id=None, outcome="new_session",
                request_id=request_id)
    return {
        "isAuthorized": True,
        "context": {"session_id": session_id, "is_new_session": "true"},
    }
```

- [ ] **Step 6: Update `app/catalog/handler.py`**

Add `request_id = event.get("requestContext", {}).get("requestId")` right after `session_id = ...` in `handler()`, and pass `request_id=request_id` to both `log_request(...)` calls:

```python
def handler(event: dict, context) -> dict:
    start = time.time()
    session_id = event["requestContext"]["authorizer"]["lambda"]["session_id"]
    request_id = event.get("requestContext", {}).get("requestId")
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
                    start_time=start, session_id=session_id, product_id=product_id,
                    outcome=outcome, request_id=request_id)
        return result

    resp = table.query(IndexName="catalog-index", KeyConditionExpression=Key("catalog_pk").eq("PRODUCT"))
    items = [_serialize(item, now >= int(item["drop_at"])) for item in resp.get("Items", [])]
    result = json_response(200, items)
    log_request(route=route, method="GET", status=200, start_time=start,
                session_id=session_id, product_id=None, outcome="ok", request_id=request_id)
    return result
```

- [ ] **Step 7: Update `app/cart/handler.py`**

Add `request_id = event.get("requestContext", {}).get("requestId")` right after `session_id = ...` in `handler()`, and pass `request_id=request_id` to all four `log_request(...)` calls:

```python
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
```

- [ ] **Step 8: Update `app/checkout/handler.py`**

Add `request_id = event.get("requestContext", {}).get("requestId")` right after `session_id = ...` in `handler()`, and pass `request_id=request_id` to all three `log_request(...)` calls:

```python
def handler(event: dict, context) -> dict:
    start = time.time()
    session_id = event["requestContext"]["authorizer"]["lambda"]["session_id"]
    request_id = event.get("requestContext", {}).get("requestId")
    reservation_id = json.loads(event.get("body") or "{}").get("reservation_id")
    now = int(time.time())

    reservations = _reservations_table()
    reservation = reservations.get_item(Key={"reservation_id": reservation_id}).get("Item")

    if reservation is None or reservation["session_id"] != session_id:
        result = json_response(404, {"error": "not_found"})
        log_request(route="POST /checkout", method="POST", status=404, start_time=start,
                    session_id=session_id, product_id=None, outcome="not_found",
                    request_id=request_id)
        return result

    if reservation["status"] != "active" or now >= int(reservation["ttl"]):
        result = json_response(410, {"error": "expired"})
        log_request(route="POST /checkout", method="POST", status=410, start_time=start,
                    session_id=session_id, product_id=reservation.get("product_id"),
                    outcome="expired", request_id=request_id)
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
                session_id=session_id, product_id=reservation["product_id"], outcome="ordered",
                request_id=request_id)
    return result
```

- [ ] **Step 9: Update `app/admin/handler.py`**

Add `request_id = event.get("requestContext", {}).get("requestId")` right after `token = ...` in `handler()`, and pass `request_id=request_id` to both `log_request(...)` calls:

```python
def handler(event: dict, context) -> dict:
    start = time.time()
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    token = headers.get("x-admin-token")
    request_id = event.get("requestContext", {}).get("requestId")

    if token != _admin_secret():
        result = json_response(401, {"error": "unauthorized"})
        log_request(route="POST /admin/reset", method="POST", status=401, start_time=start,
                    session_id=None, product_id=None, outcome="unauthorized",
                    request_id=request_id)
        return result

    products = json.loads(event.get("body") or "{}").get("products", [])

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
```

- [ ] **Step 10: Run the full app test suite**

Run: `cd app && python -m pytest -v`
Expected: PASS (all existing tests, unchanged in count — none of the other test event helpers include `requestContext.requestId`, so `request_id` resolves to `None` in those cases, which is valid).

- [ ] **Step 11: Commit**

```bash
git add app/common/logging.py app/authorizer/handler.py app/catalog/handler.py app/cart/handler.py app/checkout/handler.py app/admin/handler.py app/tests/test_responses_and_logging.py
git commit -m "feat(app): add request_id to structured logs for Phase 2 log correlation"
```

---

### Task 2: `infra/modules/app/` — explicit log groups, updated access-log format, new outputs

**Files:**
- Modify: `infra/modules/app/lambda.tf`
- Modify: `infra/modules/app/api_gateway.tf`
- Modify: `infra/modules/app/outputs.tf`

**Interfaces:**
- Consumes: nothing new.
- Produces (new module outputs, consumed by Task 4): `app_log_group_names: list(string)`, `app_log_group_arns: list(string)`, `access_log_group_name: string`, `access_log_group_arn: string`.

- [ ] **Step 1: Append explicit CloudWatch log groups to `infra/modules/app/lambda.tf`**

Add at the end of the file, after the `aws_lambda_function.admin` resource. Declaring these explicitly (instead of relying on Lambda's implicit `/aws/lambda/<name>` group) ensures the log group exists at `apply` time so Task 3's subscription filters have something to attach to, and lets Terraform manage retention:

```hcl
# Explicit log groups (instead of relying on Lambda's implicit creation) so
# Phase 2's subscription filters have something to attach to at apply time,
# and so Terraform manages retention.
resource "aws_cloudwatch_log_group" "authorizer" {
  #checkov:skip=CKV_AWS_158:Accepted — see access_logs log group in api_gateway.tf; same lab-scale tradeoff (default AWS-managed encryption, no CMK).
  name              = "/aws/lambda/${aws_lambda_function.authorizer.function_name}"
  retention_in_days = 365
}

resource "aws_cloudwatch_log_group" "catalog" {
  #checkov:skip=CKV_AWS_158:Accepted — see aws_cloudwatch_log_group.authorizer above.
  name              = "/aws/lambda/${aws_lambda_function.catalog.function_name}"
  retention_in_days = 365
}

resource "aws_cloudwatch_log_group" "cart" {
  #checkov:skip=CKV_AWS_158:Accepted — see aws_cloudwatch_log_group.authorizer above.
  name              = "/aws/lambda/${aws_lambda_function.cart.function_name}"
  retention_in_days = 365
}

resource "aws_cloudwatch_log_group" "checkout" {
  #checkov:skip=CKV_AWS_158:Accepted — see aws_cloudwatch_log_group.authorizer above.
  name              = "/aws/lambda/${aws_lambda_function.checkout.function_name}"
  retention_in_days = 365
}

resource "aws_cloudwatch_log_group" "admin" {
  #checkov:skip=CKV_AWS_158:Accepted — see aws_cloudwatch_log_group.authorizer above.
  name              = "/aws/lambda/${aws_lambda_function.admin.function_name}"
  retention_in_days = 365
}
```

- [ ] **Step 2: Update the access log format in `infra/modules/app/api_gateway.tf`**

Replace the `access_log_settings` block inside `aws_apigatewayv2_stage.default` with the Phase 2 schema (adds `user_agent`, `integration_error`, renames fields to match the spec, uses `requestTimeEpoch` instead of `requestTime` so `ts` is numeric like the app logs):

```hcl
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access_logs.arn
    format = jsonencode({
      request_id        = "$context.requestId"
      ts                = "$context.requestTimeEpoch"
      source_ip         = "$context.identity.sourceIp"
      user_agent        = "$context.identity.userAgent"
      route             = "$context.routeKey"
      method            = "$context.httpMethod"
      status            = "$context.status"
      latency_ms        = "$context.responseLatency"
      integration_error = "$context.integrationErrorMessage"
    })
  }
```

(This is the only change in the file — the rest of `aws_apigatewayv2_stage.default` and every other resource in `api_gateway.tf` stays as-is.)

- [ ] **Step 3: Append outputs to `infra/modules/app/outputs.tf`**

```hcl
output "app_log_group_names" {
  description = "CloudWatch Logs group names for the 5 app Lambda functions, consumed by Phase 2's logging module for subscription filters."
  value = [
    aws_cloudwatch_log_group.authorizer.name,
    aws_cloudwatch_log_group.catalog.name,
    aws_cloudwatch_log_group.cart.name,
    aws_cloudwatch_log_group.checkout.name,
    aws_cloudwatch_log_group.admin.name,
  ]
}

output "app_log_group_arns" {
  description = "ARNs of the 5 app Lambda log groups, consumed by Phase 2's logging module IAM policy for subscription filters."
  value = [
    aws_cloudwatch_log_group.authorizer.arn,
    aws_cloudwatch_log_group.catalog.arn,
    aws_cloudwatch_log_group.cart.arn,
    aws_cloudwatch_log_group.checkout.arn,
    aws_cloudwatch_log_group.admin.arn,
  ]
}

output "access_log_group_name" {
  description = "CloudWatch Logs group name for API Gateway access logs, consumed by Phase 2's logging module for its subscription filter."
  value       = aws_cloudwatch_log_group.access_logs.name
}

output "access_log_group_arn" {
  description = "ARN of the API Gateway access log group, consumed by Phase 2's logging module IAM policy for its subscription filter."
  value       = aws_cloudwatch_log_group.access_logs.arn
}
```

- [ ] **Step 4: Validate the module in isolation**

Run: `cd infra/modules/app && terraform fmt -check && terraform init -backend=false && terraform validate`
Expected: `terraform fmt -check` prints nothing; `terraform validate` reports `Success! The configuration is valid.`

- [ ] **Step 5: Commit**

```bash
git add infra/modules/app/lambda.tf infra/modules/app/api_gateway.tf infra/modules/app/outputs.tf
git commit -m "feat(infra): add explicit Lambda log groups and Phase 2 access-log schema to app module"
```

---

### Task 3: Terraform module `infra/modules/logging/`

**Files:**
- Create: `infra/modules/logging/variables.tf`
- Create: `infra/modules/logging/s3.tf`
- Create: `infra/modules/logging/firehose.tf`
- Create: `infra/modules/logging/subscriptions.tf`
- Create: `infra/modules/logging/glue.tf`
- Create: `infra/modules/logging/outputs.tf`

**Interfaces:**
- Consumes (module input variables): `environment: string`, `app_log_group_names: list(string)` (from Task 2's `module.app.app_log_group_names`), `apigw_log_group_name: string` (from Task 2's `module.app.access_log_group_name`).
- Produces: `module.logging.logs_bucket_name`, `module.logging.athena_workgroup`, `module.logging.glue_database` (consumed by Task 4).

- [ ] **Step 1: Write `infra/modules/logging/variables.tf`**

```hcl
variable "environment" {
  description = "Environment name (e.g. dev), used only for tagging via the caller's default_tags."
  type        = string
}

variable "app_log_group_names" {
  description = "CloudWatch Logs group names for the app Lambda functions (module.app.app_log_group_names), subscribed into the app-logs Firehose stream."
  type        = list(string)
}

variable "apigw_log_group_name" {
  description = "CloudWatch Logs group name for API Gateway access logs (module.app.access_log_group_name), subscribed into the apigw-logs Firehose stream."
  type        = string
}
```

- [ ] **Step 2: Write `infra/modules/logging/s3.tf`**

```hcl
data "aws_caller_identity" "current" {}

# Account ID is appended to keep the bucket name globally unique, matching
# infra/bootstrap's state-bucket convention.
resource "aws_s3_bucket" "logs" {
  bucket = "botdef-logs-${var.environment}-${data.aws_caller_identity.current.account_id}"

  #checkov:skip=CKV_AWS_18:Accepted — access logging needs a second bucket + recurring cost; not justified for a single-user lab logs bucket. Revisit if multi-user.
  #checkov:skip=CKV_AWS_144:Accepted — cross-region replication is out of scope (YAGNI, doubles cost) for a personal lab.
  #checkov:skip=CKV2_AWS_62:Accepted — event notifications add no value for a log-landing bucket.
}

resource "aws_s3_bucket_versioning" "logs" {
  bucket = aws_s3_bucket.logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    apply_server_side_encryption_by_default {
      # checkov:skip=CKV_AWS_145:Accepted — SSE-S3 (AES256) default encryption, matching the
      # accepted tradeoff on the 4 app DynamoDB tables (infra/modules/app/dynamodb.tf). A
      # customer-managed KMS key adds ~$1/mo with no meaningful risk reduction for this lab's
      # synthetic traffic logs. Revisit if real PII ever enters the pipeline.
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# Keep the actively-destroyed dev environment cheap: raw logs expire after 30
# days rather than accumulating indefinitely.
resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    id     = "expire-old-logs"
    status = "Enabled"
    filter {}
    expiration {
      days = 30
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket                  = aws_s3_bucket.logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "logs_tls_only" {
  bucket = aws_s3_bucket.logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.logs.arn,
        "${aws_s3_bucket.logs.arn}/*",
      ]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}
```

- [ ] **Step 3: Write `infra/modules/logging/firehose.tf`**

```hcl
data "aws_iam_policy_document" "firehose_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }
  }
}

# One delivery role for both streams, scoped to only this bucket.
resource "aws_iam_role" "firehose" {
  name               = "botdef-firehose-delivery"
  assume_role_policy = data.aws_iam_policy_document.firehose_trust.json
}

resource "aws_iam_role_policy" "firehose" {
  name = "botdef-firehose-delivery-policy"
  role = aws_iam_role.firehose.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:PutObject",
        "s3:GetBucketLocation",
        "s3:ListBucket",
      ]
      Resource = [
        aws_s3_bucket.logs.arn,
        "${aws_s3_bucket.logs.arn}/*",
      ]
    }]
  })
}

resource "aws_cloudwatch_log_group" "firehose_errors" {
  #checkov:skip=CKV_AWS_158:Accepted — see infra/modules/app/api_gateway.tf access_logs group; same lab-scale tradeoff.
  name              = "/aws/firehose/botdef-delivery-errors"
  retention_in_days = 365
}

# Hive-style time partitioning via Firehose's built-in prefix expressions
# (delivery-time based) — no custom partitioning Lambda needed.
resource "aws_kinesis_firehose_delivery_stream" "app_logs" {
  name        = "botdef-app-logs"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn             = aws_iam_role.firehose.arn
    bucket_arn            = aws_s3_bucket.logs.arn
    prefix                = "app/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    error_output_prefix   = "app-errors/!{firehose:error-output-type}/"
    buffering_size         = 1
    buffering_interval     = 60

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose_errors.name
      log_stream_name = "app-logs"
    }
  }
}

resource "aws_kinesis_firehose_delivery_stream" "apigw_logs" {
  name        = "botdef-apigw-logs"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn             = aws_iam_role.firehose.arn
    bucket_arn            = aws_s3_bucket.logs.arn
    prefix                = "apigw/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    error_output_prefix   = "apigw-errors/!{firehose:error-output-type}/"
    buffering_size         = 1
    buffering_interval     = 60

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose_errors.name
      log_stream_name = "apigw-logs"
    }
  }
}
```

- [ ] **Step 4: Write `infra/modules/logging/subscriptions.tf`**

```hcl
data "aws_iam_policy_document" "cwl_to_firehose_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["logs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cwl_to_firehose" {
  name               = "botdef-cwl-to-firehose"
  assume_role_policy = data.aws_iam_policy_document.cwl_to_firehose_trust.json
}

resource "aws_iam_role_policy" "cwl_to_firehose" {
  name = "botdef-cwl-to-firehose-policy"
  role = aws_iam_role.cwl_to_firehose.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["firehose:PutRecord", "firehose:PutRecordBatch"]
      Resource = [
        aws_kinesis_firehose_delivery_stream.app_logs.arn,
        aws_kinesis_firehose_delivery_stream.apigw_logs.arn,
      ]
    }]
  })
}

# One subscription filter per app Lambda log group (AWS requires the filter
# to attach directly to each source log group), all feeding the same stream.
resource "aws_cloudwatch_log_subscription_filter" "app_logs" {
  for_each        = toset(var.app_log_group_names)
  name            = "botdef-app-logs-to-firehose"
  log_group_name  = each.value
  filter_pattern  = ""
  destination_arn = aws_kinesis_firehose_delivery_stream.app_logs.arn
  role_arn        = aws_iam_role.cwl_to_firehose.arn
}

resource "aws_cloudwatch_log_subscription_filter" "apigw_logs" {
  name            = "botdef-apigw-logs-to-firehose"
  log_group_name  = var.apigw_log_group_name
  filter_pattern  = ""
  destination_arn = aws_kinesis_firehose_delivery_stream.apigw_logs.arn
  role_arn        = aws_iam_role.cwl_to_firehose.arn
}
```

- [ ] **Step 5: Write `infra/modules/logging/glue.tf`**

```hcl
resource "aws_glue_catalog_database" "logs" {
  name = "botdef_logs_${var.environment}"
}

resource "aws_glue_catalog_table" "apigw_logs" {
  name          = "apigw_logs"
  database_name = aws_glue_catalog_database.logs.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "json"
  }

  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "month"
    type = "string"
  }
  partition_keys {
    name = "day"
    type = "string"
  }
  partition_keys {
    name = "hour"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.logs.id}/apigw/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "request_id"
      type = "string"
    }
    columns {
      name = "ts"
      type = "bigint"
    }
    columns {
      name = "source_ip"
      type = "string"
    }
    columns {
      name = "user_agent"
      type = "string"
    }
    columns {
      name = "route"
      type = "string"
    }
    columns {
      name = "method"
      type = "string"
    }
    columns {
      name = "status"
      type = "string"
    }
    columns {
      name = "latency_ms"
      type = "string"
    }
    columns {
      name = "integration_error"
      type = "string"
    }
  }
}

resource "aws_glue_catalog_table" "app_logs" {
  name          = "app_logs"
  database_name = aws_glue_catalog_database.logs.name
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "json"
  }

  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "month"
    type = "string"
  }
  partition_keys {
    name = "day"
    type = "string"
  }
  partition_keys {
    name = "hour"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.logs.id}/app/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "ts"
      type = "double"
    }
    columns {
      name = "request_id"
      type = "string"
    }
    columns {
      name = "session_id"
      type = "string"
    }
    columns {
      name = "route"
      type = "string"
    }
    columns {
      name = "method"
      type = "string"
    }
    columns {
      name = "status"
      type = "int"
    }
    columns {
      name = "latency_ms"
      type = "double"
    }
    columns {
      name = "product_id"
      type = "string"
    }
    columns {
      name = "outcome"
      type = "string"
    }
  }
}

resource "aws_athena_workgroup" "analytics" {
  name = "botdef-analytics"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = false

    result_configuration {
      output_location = "s3://${aws_s3_bucket.logs.id}/athena-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
```

- [ ] **Step 6: Write `infra/modules/logging/outputs.tf`**

```hcl
output "logs_bucket_name" {
  description = "S3 bucket holding raw app + API Gateway logs."
  value       = aws_s3_bucket.logs.id
}

output "athena_workgroup" {
  description = "Athena workgroup name to run queries against (see docs/phase-2-observability.md for the example join query)."
  value       = aws_athena_workgroup.analytics.name
}

output "glue_database" {
  description = "Glue Catalog database name containing the app_logs and apigw_logs tables."
  value       = aws_glue_catalog_database.logs.name
}
```

- [ ] **Step 7: Validate the module in isolation**

Run: `cd infra/modules/logging && terraform fmt -check && terraform init -backend=false && terraform validate`
Expected: `terraform fmt -check` prints nothing (already formatted); `terraform validate` reports `Success! The configuration is valid.`

- [ ] **Step 8: Commit**

```bash
git add infra/modules/logging
git commit -m "feat(infra): add logging module — Firehose, S3, Glue/Athena for the SOC data plane"
```

---

### Task 4: Compose the `logging` module into `infra/envs/dev`

**Files:**
- Modify: `infra/envs/dev/main.tf`
- Modify: `infra/envs/dev/outputs.tf`

**Interfaces:**
- Consumes: `module.app.app_log_group_names`, `module.app.access_log_group_name` (Task 2); `module.logging.logs_bucket_name`, `module.logging.athena_workgroup` (Task 3).

- [ ] **Step 1: Append the module block to `infra/envs/dev/main.tf`**

Add after the existing `module "app"` block:

```hcl
# ---------------------------------------------------------------------------
# Phase 2: observability / SOC data plane — Firehose -> S3 -> Athena for both
# the app's structured logs and API Gateway access logs, correlated by
# request_id.
# ---------------------------------------------------------------------------
module "logging" {
  source               = "../../modules/logging"
  environment           = "dev"
  app_log_group_names  = module.app.app_log_group_names
  apigw_log_group_name = module.app.access_log_group_name
}
```

- [ ] **Step 2: Append outputs to `infra/envs/dev/outputs.tf`**

```hcl
output "logs_bucket_name" {
  description = "S3 bucket holding Phase 2 raw logs (app/ and apigw/ prefixes)."
  value       = module.logging.logs_bucket_name
}

output "athena_workgroup" {
  description = "Athena workgroup for querying Phase 2 logs. See docs/phase-2-observability.md for the join query."
  value       = module.logging.athena_workgroup
}
```

- [ ] **Step 3: Validate the composed environment**

Run: `cd infra/envs/dev && terraform fmt -check -recursive .. && terraform init -backend=false && terraform validate`
Expected: `terraform fmt -check` prints nothing; `terraform validate` reports `Success! The configuration is valid.`

- [ ] **Step 4: Commit**

```bash
git add infra/envs/dev/main.tf infra/envs/dev/outputs.tf
git commit -m "feat(infra): compose the logging module into the dev environment"
```

---

### Task 5: Static verification, runbook, and spec status

**Files:**
- Create: `docs/phase-2-observability.md`
- Modify: `docs/superpowers/specs/2026-08-30-phase-2-observability-design.md`

- [ ] **Step 1: Run the full Python test suite**

Run: `cd app && python -m pytest -v`
Expected: all tests pass (Task 1's `request_id` change plus every Phase 1 test).

- [ ] **Step 2: Run Terraform formatting and validation across all of `infra/`**

Run: `terraform fmt -check -recursive infra/`
Expected: no output. If it prints filenames, run `terraform fmt -recursive infra/` and re-check.

- [ ] **Step 3: Run Checkov**

Run: `checkov -d infra/ --compact`
Expected: no new HIGH/CRITICAL findings from `infra/modules/logging/` or the updated `infra/modules/app/`/`infra/envs/dev` files. Fix any that appear, or add a `#checkov:skip=<ID>:<justification>` comment in the established style (see Task 3's skips) and note it here.

- [ ] **Step 4: Run Trivy**

Run: `trivy config infra/ --severity HIGH,CRITICAL`
Expected: no new HIGH/CRITICAL findings. Same skip-and-document policy as Checkov.

- [ ] **Step 5: Write `docs/phase-2-observability.md`**

```markdown
# Phase 2 — Observability / SOC Data Plane (runbook)

Goal: turn the Phase 1 drop app's traffic into a queryable SOC data plane — app logs and API
Gateway access logs, correlated by `request_id`, landing in S3 via Firehose and queryable through
Athena. See `docs/superpowers/specs/2026-08-30-phase-2-observability-design.md` for the design.

## What this phase built

- `app/common/logging.py` now stamps every log line with `request_id`.
- `infra/modules/app/`: explicit per-function Lambda log groups; API Gateway access logs
  reformatted to the Phase 2 schema (`request_id, ts, source_ip, user_agent, route, method,
  status, latency_ms, integration_error`).
- `infra/modules/logging/`: S3 bucket (`botdef-logs-dev-<account_id>`), two Firehose delivery
  streams (`botdef-app-logs`, `botdef-apigw-logs`), CloudWatch subscription filters wiring both
  log sources into their stream, and two Glue/Athena tables (`app_logs`, `apigw_logs`) in the
  `botdef_logs_dev` database, queryable through the `botdef-analytics` Athena workgroup.

## Cost

Same guardrail as Phase 0 (`docs/phase-0-foundation.md`): everything here runs on the AWS
free-account plan and draws from signup credits, not cash. Firehose has no free tier but at this
lab's traffic volume the ingestion cost is pennies. S3 objects expire after 30 days via the
bucket's lifecycle rule to keep storage near-zero between sessions. `terraform destroy` between
sessions removes all of it.

## Deploying (first time — this also deploys Phase 1, which was never applied)

```powershell
cd infra/envs/dev
copy terraform.tfvars.example terraform.tfvars   # if not already done (see docs/phase-0-foundation.md)
terraform init -backend-config=backend.hcl
terraform plan
terraform apply
```

Note the `app_api_endpoint`, `app_admin_secret_param_name`, `logs_bucket_name`, and
`athena_workgroup` outputs.

Seed the admin secret and some products (see `docs/superpowers/specs/2026-06-03-phase-1-drop-app-design.md`
for the `/admin/reset` payload shape), then generate a little traffic:

```powershell
$endpoint = terraform output -raw app_api_endpoint
Invoke-RestMethod "$endpoint/products"
Invoke-RestMethod "$endpoint/products" -Method GET  # repeat a few times
```

## Verifying the pipeline (manual — do this after a real deploy)

1. Wait ~60-90 seconds for Firehose's buffer window.
2. Confirm objects landed in both prefixes:

```powershell
$bucket = terraform output -raw logs_bucket_name
aws s3 ls "s3://$bucket/app/" --recursive
aws s3 ls "s3://$bucket/apigw/" --recursive
```

3. In the Athena console (or CLI), select workgroup `botdef-analytics` and database
   `botdef_logs_dev`, then run:

```sql
MSCK REPAIR TABLE apigw_logs;
MSCK REPAIR TABLE app_logs;

SELECT a.route, a.source_ip, a.user_agent, a.status, l.session_id, l.outcome
FROM apigw_logs a JOIN app_logs l ON a.request_id = l.request_id
WHERE a.year = '<yyyy>' AND a.month = '<mm>' AND a.day = '<dd>';
```

   (`MSCK REPAIR TABLE` registers the Hive-style partitions Firehose created — run it once per
   table after new partitions appear, since there's no crawler doing this automatically.)

4. Confirm rows come back matching the traffic generated in the previous step (`request_id`s line
   up, `source_ip`/`session_id`/`outcome` values look right).

## Known simplifications (documented, not deferred silently)

- No CloudFront/WAF logs yet — Phase 3.
- No transform/normalization Lambda — Athena JOIN on `request_id` is sufficient at this scale.
- No Glue crawler — schema is static and defined directly in Terraform.
- 30-day log retention, no Glacier tiering — not needed for an actively destroyed dev environment.
```

- [ ] **Step 6: Update the spec status**

Edit `docs/superpowers/specs/2026-08-30-phase-2-observability-design.md` line 3 status line from `**Status:** draft` to:

```markdown
**Status:** implemented (static verification only — live end-to-end verification pending first real deploy; see docs/phase-2-observability.md)
```

- [ ] **Step 7: Commit**

```bash
git add docs/phase-2-observability.md docs/superpowers/specs/2026-08-30-phase-2-observability-design.md
git commit -m "docs: add Phase 2 observability runbook and mark spec implemented"
```
