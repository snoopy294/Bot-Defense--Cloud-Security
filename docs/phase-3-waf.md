# Phase 3 — Cloud-Native Bot Defense / WAF (runbook)

Goal: put CloudFront + AWS WAF in front of the Phase 1 drop app, matching the README's
architecture diagram, with WAF request logs flowing into the Phase 2 SOC data plane. See
`docs/superpowers/specs/2026-08-31-phase-3-waf-design.md` for the design.

## What this phase built

- `infra/modules/app/`: new `api_domain_name` output (bare hostname for the CloudFront origin).
- `infra/modules/logging/`: new `logs_bucket_arn` output (consumed by the WAF Firehose IAM policy).
- `infra/modules/waf/`: a CloudFront distribution fronting the API Gateway (caching disabled,
  `PriceClass_100`), a WAF Web ACL (`botdef-waf-dev`) with 3 AWS managed rule groups in Block mode
  (Core Rule Set, Known Bad Inputs, IP Reputation List) and 2 custom rules in Count mode
  (`checkout-rate-limit`: 300 req/5min/IP on `/checkout*`; `missing-user-agent`: flags empty
  `User-Agent` headers), and a WAF logging pipeline (Firehose `aws-waf-logs-botdef-waf-dev` → the
  existing `botdef-logs-dev` bucket's new `waf/` prefix → new `waf_logs` Glue table in the
  existing `botdef_logs_dev` database).

## Cost

Unlike Phases 0-2 (near-zero cash cost), this phase adds the project's first real recurring
charge: CloudFront (free-tier eligible: 1TB egress + 10M requests/month for 12 months) and the WAF
Web ACL (~$5/month base + $1/rule/month + $0.60/million requests — roughly $10/month for this
Web ACL's 5 rules at lab traffic volume). `terraform destroy` between sessions removes all of it
(the Web ACL and distribution stop billing once destroyed).

## Deploying

```powershell
cd infra/envs/dev
terraform init -backend-config=backend.hcl
terraform plan
terraform apply
```

Note the new `cloudfront_domain_name` and `waf_web_acl_arn` outputs. CloudFront distribution
changes take several minutes to propagate globally — expect `apply`/`destroy` to run noticeably
longer than Phases 1-2.

## Verifying (manual — do this after a real deploy)

1. Smoke-test the app through the new edge layer:

```powershell
$domain = terraform output -raw cloudfront_domain_name
Invoke-RestMethod "https://$domain/products"
```

   Confirm this returns the same result as `Invoke-RestMethod "$(terraform output -raw app_api_endpoint)/products"` — no functional regression from adding CloudFront.

2. Confirm all 5 WAF rules are present with the correct action:

```powershell
aws wafv2 get-web-acl --name botdef-waf-dev --scope CLOUDFRONT --id <id-from-console-or-list-web-acls>
```

   Expect 3 rules with `OverrideAction: {None: {}}` (managed groups, effectively Block) and 2
   rules with `Action: {Count: {}}` (`checkout-rate-limit`, `missing-user-agent`).

3. Generate at least one request through the CloudFront domain, wait ~60-90 seconds for Firehose's
   buffer window, then confirm a WAF log object landed:

```powershell
$bucket = terraform output -raw logs_bucket_name
aws s3 ls "s3://$bucket/waf/" --recursive
```

4. In the Athena console (workgroup `botdef-analytics-dev`, database `botdef_logs_dev`):

```sql
MSCK REPAIR TABLE waf_logs;

SELECT "timestamp", action, terminatingruleid, httprequest.clientip, httprequest.uri
FROM waf_logs
WHERE year = '<yyyy>' AND month = '<mm>' AND day = '<dd>'
LIMIT 10;
```

   (`"timestamp"` is double-quoted because it's a reserved word in Athena's SQL dialect.) Confirm
   rows come back matching the request generated in step 3.

## Known simplifications (documented, not deferred silently)

- No AWS WAF Bot Control — recurring cash cost outside the free-tier guarantee. Documented as a
  future enhancement.
- Custom rules (`checkout-rate-limit`, `missing-user-agent`) run in Count mode only — no traffic is
  actually blocked by them yet. Flipping to Block is a follow-up change once Phase 4's adversary
  traffic validates them.
- No CloudFront access logging (separate from WAF logging) — would duplicate the WAF request log
  signal for no added detection value at this lab's scale.
- No custom domain/ACM certificate — uses the CloudFront default certificate (`*.cloudfront.net`).
- No enforcement that traffic goes through CloudFront — the API Gateway invoke URL
  (`app_api_endpoint`) stays publicly reachable, so the WAF can be bypassed by hitting the origin
  directly. A lab-grade mitigation (CloudFront custom-header shared secret validated by the
  authorizer, or an API Gateway resource policy) is out of scope for this phase. Phase 4's traffic
  generator must be pointed at the CloudFront domain by convention, not enforcement.

## Static verification

Run from the repo root:

```bash
terraform fmt -check -recursive infra/
cd infra/envs/dev && terraform init -backend=false && terraform validate
checkov -d infra/ --compact
trivy config infra/ --severity HIGH,CRITICAL
```

`terraform fmt` and `terraform validate` are clean. `checkov` and `trivy` reported no new
HIGH/CRITICAL findings from this phase's files after adding skip comments to
`infra/modules/waf/cloudfront.tf` (257 passed / 0 failed / 71 skipped overall). Findings resolved
by skip comment rather than code change, and why:

- **CKV_AWS_305** (no default root object) — this distribution fronts a pure API proxy (API
  Gateway origin), not a static site; there is no index document to serve.
- **CKV_AWS_310** (no origin failover group) — single-origin lab setup; failover needs a second
  origin, which adds cost/complexity with no benefit at this lab's scale.
- **CKV_AWS_374** (geo restriction disabled) — `geo_restriction { restriction_type = "none" }` is
  intentional per the design spec's Global Constraints, not an oversight.
- **CKV_AWS_174** (TLS version check) — false positive: `minimum_protocol_version` is already
  pinned to `TLSv1.2_2021`, but checkov doesn't evaluate that setting when
  `cloudfront_default_certificate = true`.
- **CKV2_AWS_42** (no custom SSL certificate) — no custom domain/ACM certificate for this lab;
  uses the CloudFront default certificate.
- **CKV2_AWS_32** (no response headers policy) — this distribution proxies a JSON API, not a
  browser-rendered page, so browser security response headers add no meaningful protection here.
- **CKV2_AWS_47** (WAF AMR/Log4j managed rule check) — false positive: the attached Web ACL
  already includes `AWSManagedRulesKnownBadInputsRuleSet`, which covers Log4j-class exploits;
  checkov doesn't recognize that rule group as satisfying this check.
- **trivy AWS-0010** (CloudFront access logging) — same underlying finding as the already-accepted
  `CKV_AWS_86` skip (WAF request logging already covers this signal); added the matching
  `#trivy:ignore:AWS-0010` comment next to it.

Two findings the initial review flagged as possible gaps turned out to already be covered by the
existing implementation and needed no skip: `CKV2_AWS_31` (WAF logging configuration — present
since Task 4's `aws_wafv2_web_acl_logging_configuration.app`) and the Log4j coverage question
itself (the managed rule group is present; only checkov's CloudFront-side detection of it is a
false positive, handled above via `CKV2_AWS_47`).
