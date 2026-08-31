# Phase 3 — Cloud-Native Bot Defense (WAF) (design)

**Status:** implemented (static verification only — live end-to-end verification pending first real deploy; see docs/phase-3-waf.md)
**Date:** 2026-08-31
**Phase:** 3 of the Cloud-Security Bot-Defense Lab (see `README.md`)

## Purpose

Put a CloudFront + WAF edge in front of the Phase 1 drop app, matching the README's architecture
diagram (`adversary/ ──► CloudFront + WAF ──► API Gateway ──► Lambda (drop app) ──► DynamoDB`).
This is the defensive perimeter that:

- Phase 4 (adversary + legit-traffic generator) will run traffic through and use to validate the
  Count-mode custom rules.
- Phase 5 (ML detection) will eventually consume WAF logs as an additional feature source
  alongside the Phase 2 app/API Gateway logs.
- Phase 6 (detection engineering & automated response) will extend this Web ACL with an
  auto-block rule driven by GuardDuty/Security Hub findings.

Phase 3 itself does **not** attempt to tune detection — no real bot traffic exists yet (that's
Phase 4). This phase's "done" bar is correct wiring and end-to-end log visibility.

## Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| Edge topology | Add CloudFront in front of the existing HTTP API; WAF Web ACL at `CLOUDFRONT` scope | Matches the README diagram. Also unlocks CloudFront access logs as a future signal source, and edge-level rate limiting/caching that a regional-only WAF-on-API-Gateway setup wouldn't give. |
| WAF region | `us-east-1` (the dev environment's existing default region) | CLOUDFRONT-scope WAF resources must live in `us-east-1`. `infra/envs/dev/variables.tf` already pins `region = "us-east-1"` for this exact reason (comment: "Keep us-east-1 for CloudFront/WAF compatibility") — no second provider/alias needed. |
| Bot Control managed rule group | **Excluded** | Bills ~$10/month + $1/million requests regardless of the free account plan — the first line item that would break the "near-zero cash spend" guarantee. Documented as a future enhancement instead. |
| Baseline managed rule groups | `AWSManagedRulesCommonRuleSet`, `AWSManagedRulesKnownBadInputsRuleSet`, `AWSManagedRulesAmazonIpReputationList` — all in **Block** mode | Pre-tuned by AWS with low false-positive rates; standard practice to deploy managed rule groups straight to Block. Billed per-WCU, not per-request — negligible at lab volume. IP reputation list is directly on-theme (blocks known bot/scanner source IPs). |
| Custom rules rollout | Rate-based rule + adversary-signature rule both start in **Count** mode | Untuned, lab-specific rules risk false positives with zero real traffic to validate against yet. Count mode logs matches without blocking, giving a clean checkpoint: flip to Block once Phase 4 generates real adversary traffic to confirm against. |
| Rate-based rule scope | `/checkout*` path, evaluating source IP, threshold 300 requests / 5 min | Checkout is the actual "drop" bottleneck bots target (limited-stock reservation), not general API traffic — scoping here avoids false-positives against normal `catalog`/`cart` browsing. |
| Custom signature rule | Byte-match rule flagging requests with a missing or empty `User-Agent` header | Cheap, concrete first signature. `adversary/` (repurposed `pokemon-monitor/`) already does fingerprint spoofing, so this rule is expected to need tuning once Phase 4 traffic runs — that's the point of Count-first rollout. |
| WAF logging destination | New Kinesis Firehose stream feeding into the **existing** Phase 2 logs bucket, new `waf/` prefix, new Glue table | Keeps all lab signal (app logs, API Gateway logs, now WAF logs) in one bucket/one Athena workgroup, joinable by IP/timestamp for the eventual ML detector. Avoids standing up a second logging stack. |
| Firehose naming constraint | WAF-logging Firehose must be named `aws-waf-logs-botdef-waf-dev` | AWS requires a Kinesis Data Firehose used as a direct WAF logging destination to have a name starting with the literal prefix `aws-waf-logs-` — this is an AWS-enforced constraint, not a project convention, so it breaks the `botdef-*`-prefix-first naming used elsewhere. |
| IAM | No changes needed to the CI deploy role | `infra/envs/dev/main.tf`'s `data.aws_iam_policy_document.deploy` already grants `cloudfront:*` and `wafv2:*` (added in Phase 0, anticipating this phase). |
| Cost | Non-zero but small: CloudFront (free-tier eligible: 1TB/10M requests for 12 months) + WAF Web ACL (~$5/mo base + $1/rule/mo + $0.60/million requests) | First genuinely non-negligible recurring line item in the project (Phases 0-2 were near-zero). Explicitly called out in the runbook rather than silently accepted. |

## Architecture

```
adversary/ ──► CloudFront distribution ──► API Gateway (HTTP API) ──► Lambda ──► DynamoDB
                    │
                 WAF Web ACL (CLOUDFRONT scope)
                    │  Block: CRS, KnownBadInputs, IpReputation
                    │  Count: rate-limit(/checkout*), missing-UA signature
                    │
                    └──► aws-waf-logs-botdef-waf-dev (Firehose) ──► S3 botdef-logs-dev/waf/...
                                                                            │
                                                                      Glue Catalog (waf_logs)
                                                                            │
                                                                         Athena (existing botdef-analytics-dev workgroup)
```

## New Terraform module: `infra/modules/waf/`

Composed into `infra/envs/dev/main.tf` alongside `app` and `logging` (same pattern as Phase 1/2).
Resources:

- **`aws_cloudfront_distribution` "app"** — single custom origin pointed at the API Gateway's
  invoke domain (see "Change to `infra/modules/app/`" below for the new output this needs),
  `origin_protocol_policy = "https-only"`, default cache behavior `viewer_protocol_policy =
  "redirect-to-https"`, `allowed_methods` covering `GET/HEAD/OPTIONS/PUT/POST/PATCH/DELETE` (the
  API needs POST/PUT for checkout/cart, not just GET), `cached_methods = ["GET", "HEAD"]`,
  `forwarded_values` passing all headers/cookies/query strings through (the app's session
  authorizer needs cookies/headers preserved — this is not a cacheable static-asset site).
- **`aws_wafv2_web_acl` "app"** — `scope = "CLOUDFRONT"`, default action `Allow`, with:
  - Rule 1 (priority 0): `AWSManagedRulesCommonRuleSet`, override to none (Block, as shipped),
    `visibility_config` with CloudWatch metrics + sampled requests enabled.
  - Rule 2 (priority 1): `AWSManagedRulesKnownBadInputsRuleSet`, same visibility config pattern.
  - Rule 3 (priority 2): `AWSManagedRulesAmazonIpReputationList`, same visibility config pattern.
  - Rule 4 (priority 3): custom rate-based rule `checkout-rate-limit`, `statement { rate_based_statement { limit = 300, aggregate_key_type = "IP", scope_down_statement { byte_match_statement { search_string = "/checkout", field_to_match { uri_path {} }, positional_constraint = "STARTS_WITH", text_transformation { priority = 0, type = "NONE" } } } } }`, `action { count {} }`.
  - Rule 5 (priority 4): custom rule `missing-user-agent`, `statement { size_constraint_statement { field_to_match { single_header { name = "user-agent" } }, comparison_operator = "EQ", size = 0, text_transformation { priority = 0, type = "NONE" } } }`, `action { count {} }`.
- **`aws_wafv2_web_acl_association`**: not used — CLOUDFRONT-scope Web ACLs associate via the
  distribution's `web_acl_id` argument directly, not a separate association resource (that
  resource is only for REGIONAL scope).
- **Firehose delivery stream** `aws-waf-logs-botdef-waf-dev`, `destination = "extended_s3"`,
  writing to the existing `botdef-logs-<env>` bucket (passed in as a variable — see below) under
  `waf/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/`.
  Reuses the same buffering (1 MiB / 60s) as the Phase 2 streams. WAF's native Firehose
  integration delivers plain JSON directly (no CloudWatch Logs subscription filter hop, no
  gzip/decompression processors needed — that machinery in Phase 2's module was specifically for
  the CloudWatch Logs subscription path, which WAF logging doesn't use).
- **IAM role for this Firehose delivery stream**: separate from Phase 2's `firehose` role (new
  module, new role), scoped to `s3:PutObject`/`s3:GetBucketLocation`/`s3:ListBucket` on only the
  `botdef-logs-<env>` bucket ARN (passed in as a variable) under the `waf/*` prefix.
- **`aws_wafv2_web_acl_logging_configuration` "app"** — `resource_arn = web_acl.arn`,
  `log_destination_configs = [firehose delivery stream arn]`.

## Change to `infra/modules/app/`

Add one new output, `api_domain_name`, extracting just the hostname from the existing
`aws_apigatewayv2_stage.default.invoke_url` (via `replace(..., "https://", "")` — Terraform has no
built-in URL parser, and the invoke URL always has the `https://` scheme with no path since the
stage is `$default`). CloudFront's `origin { domain_name = ... }` requires a bare hostname, not a
full URL. No other changes to this module.

## Change to `infra/modules/logging/`

None. The Phase 2 logging module stays app/API-Gateway-only; WAF gets its own Firehose→S3→Glue
wiring inside the new `waf` module, writing into the *same bucket* (passed in as a variable) but
otherwise independent — this avoids coupling the `waf` module's plan/apply to `logging` module
changes, and keeps each module's resource set aligned with the phase that owns it (same pattern as
Phase 2 not touching Phase 1's `app` module, beyond consuming its outputs).

## `infra/envs/dev/main.tf` wiring

```hcl
module "waf" {
  source            = "../../modules/waf"
  environment       = "dev"
  api_domain_name   = module.app.api_domain_name
  logs_bucket_name  = module.logging.logs_bucket_name
  logs_bucket_arn   = module.logging.logs_bucket_arn # new output needed on logging module — see below
}
```

`infra/modules/logging/outputs.tf` needs one new output, `logs_bucket_arn` (currently only
`logs_bucket_name` is exposed), so the `waf` module's Firehose IAM policy can scope to the bucket
ARN without re-deriving it.

## Validation approach

No live adversary traffic exists yet (Phase 4). This phase proves wiring, not detection tuning:

1. `terraform fmt -check -recursive infra/` and `terraform validate` (in `infra/envs/dev/`) pass.
2. `checkov -d infra/` and `trivy config infra/` pass, or findings are triaged/justified with
   inline skip comments (same precedent as Phases 0-2).
3. After `terraform apply`, `curl` the CloudFront distribution domain (`terraform output` it) and
   confirm the existing drop-app routes (`/products`, `/cart`, `/checkout`) still respond
   correctly through the new edge layer — i.e. no functional regression from adding CloudFront.
4. Trigger at least one WAF log record (any request through the distribution) and confirm it lands
   in `s3://botdef-logs-dev/waf/...` and is queryable via
   `SELECT * FROM botdef_logs_dev.waf_logs LIMIT 10` in the `botdef-analytics-dev` Athena
   workgroup.
5. Confirm in the WAF console (or via `aws wafv2 get-web-acl`) that all 5 rules are present with
   the correct action (Block for the 3 managed groups, Count for the 2 custom rules).

## Known tradeoffs (carried into the runbook)

- **Cost breaks the near-zero streak.** Phases 0-2 ran at effectively $0 cash (free-tier or
  pay-per-request at negligible lab volume). WAF's ~$5-10/month base charge is the first
  real recurring cost. Acceptable for a portfolio project; call it out explicitly so it isn't a
  surprise on a bill.
- **Count-mode rules provide no actual blocking yet.** Until Phase 4 traffic validates them and a
  follow-up change flips them to Block, the rate-limit and missing-UA rules are observability-only.
  This is intentional (see "Custom rules rollout" above), not an oversight.
- **CloudFront adds propagation latency to `terraform apply`/`destroy`.** Distribution changes take
  several minutes to propagate globally, unlike the Lambda/DynamoDB/API Gateway resources in
  Phases 1-2 which apply near-instantly. Budget extra time in the runbook for this phase's
  apply/destroy cycle.

## Phase 3 done when

- [ ] `terraform fmt -check -recursive infra/` passes
- [ ] `terraform validate` passes in `infra/envs/dev/`
- [ ] `checkov -d infra/` and `trivy config infra/` pass (or findings triaged/justified)
- [ ] `terraform apply` succeeds; CloudFront distribution, WAF Web ACL, and WAF logging Firehose
      all exist
- [ ] the drop app's existing routes work end-to-end through the CloudFront domain
- [ ] a WAF log record is confirmed queryable in Athena
- [ ] all 5 WAF rules present with correct actions (3× Block, 2× Count)
