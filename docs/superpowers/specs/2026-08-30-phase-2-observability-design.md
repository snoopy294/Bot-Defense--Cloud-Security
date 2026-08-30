# Phase 2 — Observability / SOC Data Plane (design)

**Status:** draft
**Date:** 2026-08-30
**Phase:** 2 of the Cloud-Security Bot-Defense Lab (see `README.md`)

## Purpose

Turn the Phase 1 drop app's request traffic into a queryable SOC data plane: capture both the
app's business-level logs and the API Gateway edge-level access logs, land them in S3, and make
them queryable via Athena. This is the data foundation that:

- Phase 3 (WAF) will extend with WAF/CloudFront logs.
- Phase 4 (adversary + legit-traffic generator) will populate at volume, producing labeled
  bot/human traffic.
- Phase 5 (ML detection) will train a classifier against.

Phase 1's spec already commits to this: "all functions ─► structured JSON logs ─► CloudWatch
(Phase 2 wires Firehose→S3→Athena)."

## Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| Log sources | App Lambda logs **and** API Gateway access logs | App logs carry business context (session_id, route, outcome); API Gateway access logs carry edge signal (source IP, User-Agent) that only exists at the edge. Waiting for Phase 3 (CloudFront) to get this signal would block Phase 5 unnecessarily. |
| Ingestion pattern | CloudWatch Logs subscription filter → Kinesis Firehose → S3 | Standard, low-maintenance AWS log pipeline. No custom polling/export Lambda to maintain. |
| Cost | Accepted — draws from AWS free-account signup credits, not cash | Same guardrail as Phase 0 (`docs/phase-0-foundation.md`). At lab-scale traffic volume, Firehose ingestion cost is negligible. |
| S3 layout | One bucket, two prefixes (`app/`, `apigw/`), each Hive-partitioned by `year/month/day/hour` | Simpler IAM/lifecycle policy than multiple buckets; partitioning keeps Athena scans cheap. |
| Partitioning mechanism | Firehose dynamic partitioning by ingestion time | No custom transform Lambda needed to compute partitions. |
| Athena schema | Two separate tables (`app_logs`, `apigw_logs`), joined by `request_id` at query time | Matches the two independent log sources/pipelines; avoids a merge/transform Lambda. |
| Schema definition | Static, Terraform-defined `aws_glue_catalog_table` (JSON SerDe) | No Glue crawler — schema is known upfront and stable; keeps the module simple. |
| Correlation key | `request_id`, added to the app's structured log output | API Gateway's `$context.requestId` is already available to every Lambda handler via the event's `requestContext`; timestamp-only correlation is too loose. |
| Verification | Generate real traffic against the deployed dev app and confirm an Athena join query returns matching rows | Phase 4 (traffic generators) doesn't exist yet, so Phase 2 proves itself with ad-hoc traffic rather than deferring verification. |

## Architecture

```
API Gateway (access logs) ──┐
                             ├──► CloudWatch Logs ──► subscription filter ──► Firehose "botdef-apigw-logs" ──► S3 (botdef-logs-<env>/apigw/...)
5 Lambdas (app logs)   ──────┘                    ↑ subscription filter ──► Firehose "botdef-app-logs"   ──► S3 (botdef-logs-<env>/app/...)
                                                                                                                    │
                                                                                                              Glue Catalog
                                                                                                          (app_logs, apigw_logs)
                                                                                                                    │
                                                                                                                 Athena
```

Two independent CloudWatch→Firehose→S3 pipelines, one per log source, landing in one bucket under
separate prefixes. No transform/normalization Lambda in the pipeline — each source keeps its
native schema, joined at query time in Athena.

## New Terraform module: `infra/modules/logging/`

Composed into `infra/envs/dev/main.tf` alongside the existing `app/` module (same pattern as
Phase 1). Resources:

- **S3 bucket** `botdef-logs-<env>` — versioned, SSE-encrypted (SSE-S3, matching the existing
  bucket in `infra/bootstrap`), public access blocked, lifecycle rule expiring objects after 30
  days.
- **2 Kinesis Firehose delivery streams**: `botdef-app-logs`, `botdef-apigw-logs`. Each buffers at
  Firehose's practical minimums (60s / 1 MiB) before writing to its S3 prefix, using Firehose
  dynamic partitioning (by ingestion time) to write under `year=YYYY/month=MM/day=DD/hour=HH/`.
- **2 CloudWatch Logs subscription filters**: one on the existing app Lambda log group(s)
  (catalog/cart/checkout/admin/authorizer share the same JSON log shape from
  `app/common/logging.py`), one on the new API Gateway HTTP API access log group. Both use a
  match-all filter pattern (`""`) and target their respective Firehose stream.
- **IAM**:
  - One Firehose delivery role scoped to `s3:PutObject`/`s3:PutObjectAcl`/`s3:GetBucketLocation`
    on only `botdef-logs-<env>` and its prefixes (no wildcard bucket access).
  - CloudWatch Logs needs a resource policy / role granting `firehose:PutRecord` /
    `firehose:PutRecordBatch` to invoke each Firehose stream from the subscription filter.
- **2 `aws_glue_catalog_table` resources** (`app_logs`, `apigw_logs`) — JSON SerDe
  (`org.openx.data.jsonserde.JsonSerDe`), partitioned by `year, month, day, hour` (all `string`),
  pointed at their respective S3 prefixes. No Glue crawler.
- **Athena workgroup** `botdef-analytics` with a dedicated results prefix
  (`s3://botdef-logs-<env>/athena-results/`) so query results don't mix with raw log data.

### API Gateway access log format

Enabled on the existing HTTP API stage (`infra/modules/app/api_gateway.tf`), using API Gateway's
`$context` variables, JSON-formatted:

```json
{
  "request_id": "$context.requestId",
  "ts": "$context.requestTimeEpoch",
  "source_ip": "$context.identity.sourceIp",
  "user_agent": "$context.identity.userAgent",
  "route": "$context.routeKey",
  "method": "$context.httpMethod",
  "status": "$context.status",
  "latency_ms": "$context.responseLatency",
  "integration_error": "$context.integrationErrorMessage"
}
```

Delivered to a new dedicated CloudWatch log group (e.g. `/aws/apigateway/botdef-<env>-access`),
which the `apigw` subscription filter reads from.

### App log format change

`app/common/logging.py::log_request` gains a `request_id` field, sourced from
`event["requestContext"]["requestId"]` (already present on every API Gateway HTTP API Lambda
event; no new IAM permission or dependency required). Every one of the five existing handlers
(authorizer, catalog, cart, checkout, admin) that calls `log_request` passes it through.

Resulting app log shape:

```json
{
  "ts": ...,
  "request_id": ...,
  "session_id": ...,
  "route": ...,
  "method": ...,
  "status": ...,
  "latency_ms": ...,
  "product_id": ...,
  "outcome": ...
}
```

### Athena tables

Both partitioned by `year (string), month (string), day (string), hour (string)`:

- **`apigw_logs`**: `request_id, ts, source_ip, user_agent, route, method, status, latency_ms, integration_error`
- **`app_logs`**: `ts, request_id, session_id, route, method, status, latency_ms, product_id, outcome`

Example join query (goes in the Phase 2 runbook):

```sql
SELECT a.route, a.source_ip, a.user_agent, a.status, l.session_id, l.outcome
FROM apigw_logs a JOIN app_logs l ON a.request_id = l.request_id
WHERE a.year='2026' AND a.month='08' AND a.day='30';
```

## Testing / verification (definition of done)

1. `terraform apply` succeeds against `infra/envs/dev`; `checkov` scan clean (same bar as
   Phase 0/1 — skips documented with rationale where unavoidable).
2. Generate real traffic against the deployed dev API: a handful of `GET /products` and
   `POST /cart` calls (manual `curl`/PowerShell loop is sufficient — Phase 4's generators don't
   exist yet).
3. Wait for the Firehose buffer window (~60s) and confirm objects land under both
   `s3://botdef-logs-<env>/app/...` and `.../apigw/...` at the expected partition path.
4. Run the documented join query in the Athena console/CLI against workgroup `botdef-analytics`
   and confirm it returns rows matching the generated requests (matching `request_id`s, correct
   `source_ip`/`session_id`/`outcome` values).
5. Add `docs/phase-2-observability.md` (mirrors `phase-0-foundation.md`'s style: setup steps,
   verification steps, cost notes) and flip this spec's status to "implemented" once verification
   passes.

## Out of scope (documented, not deferred silently)

- CloudFront/WAF logs — Phase 3.
- Any transform/normalization Lambda merging the two log sources into one schema — YAGNI; Athena
  JOIN is sufficient at this scale and for Phase 5's needs.
- Glue crawler / schema auto-discovery — schema is static and known upfront.
- Log retention beyond 30 days, or moving cold data to Glacier — not needed for an actively
  destroyed dev environment.
