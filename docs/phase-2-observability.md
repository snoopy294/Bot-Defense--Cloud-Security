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
  streams (`botdef-app-logs-dev`, `botdef-apigw-logs-dev`), CloudWatch subscription filters wiring
  both log sources into their stream, and two Glue/Athena tables (`app_logs`, `apigw_logs`) in the
  `botdef_logs_dev` database, queryable through the `botdef-analytics-dev` Athena workgroup. Each
  Firehose stream's `processing_configuration` runs Firehose's native `Decompression` +
  `CloudWatchLogProcessing` processors to unwrap the gzip-compressed CloudWatch Logs subscription
  envelope and extract the raw log line before it lands in S3 — this is the "no transform Lambda"
  mechanism referenced below; it's a built-in Firehose feature, not custom code.

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

3. In the Athena console (or CLI), select workgroup `botdef-analytics-dev` and database
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
  Firehose's own native Decompression + CloudWatchLogProcessing processors (configured in
  `processing_configuration`) handle unwrapping the CloudWatch Logs envelope; that's Firehose
  built-in functionality, not a custom transform.
- No Glue crawler — schema is static and defined directly in Terraform.
- 30-day log retention, no Glacier tiering — not needed for an actively destroyed dev environment.
