# Phase 1 — Serverless Drop Target App (design)

**Status:** implemented
**Date:** 2026-06-03
**Phase:** 1 of the Cloud-Security Bot-Defense Lab (see `README.md`)

## Purpose

Build the serverless "drop" application that the rest of the lab is built around:

- The **adversary** (Phase 4, repurposed `pokemon-monitor`) attacks it to generate the *bot*
  traffic class.
- A **legit-traffic generator** (Phase 4) drives it to generate the *human* class.
- **Phase 2** turns its request logs into a SOC data plane (Firehose → S3 → Athena).
- **Phase 3** wraps it in CloudFront + WAF.
- **Phase 5** trains an ML bot-vs-human classifier on the traffic it produces.

The app must therefore be a realistic, contention-driven retail "drop": limited inventory that
clients race to grab the instant a drop opens. Contention is what makes bot behavior detectable.

## Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| Interaction scope | Browse → cart → checkout against finite inventory | The real scalper battleground; richest detector signal |
| Identity model | Anonymous + session token (no passwords) | Session-velocity / fresh-session-per-hit is the strongest cheap bot signal, minimal attack surface |
| Compute | Python, one Lambda per route group, one IAM role each | Per-function least privilege is the "cloud security" headline; Python keeps the repo single-language (adversary + detector are Python) |
| Drop mechanic | Scheduled drops (`drop_at`) + protected admin reset | Models pre-drop polling storm *and* at-drop grab race; reset enables repeatable labeled-data runs |
| API Gateway | HTTP API (not REST API) | Cheaper, lower latency, native authorizer, sits cleanly behind Phase 3 CloudFront+WAF |
| DynamoDB layout | Multi-table | Per-table IAM scoping reads more legibly than single-table-design here |
| Reservation expiry | Documented simplification: admin reset reclaims leaked stock | Keeps Phase 1 bounded; Streams "reaper" Lambda is the documented next step |

## Architecture

```
                    (Phase 3 adds: CloudFront + WAF in front)
client ─► API Gateway HTTP API ─► Lambda authorizer (session) ─┐
                                                               ├─► catalog-fn   (read-only)   ─► Products
                                                               ├─► cart-fn      (reserve)     ─► Products(atomic), Reservations
                                                               ├─► checkout-fn  (purchase)    ─► Reservations, Orders
                                                               └─► admin-fn     (reset/seed)  ─► Products, Reservations, Orders
        all functions ─► structured JSON logs ─► CloudWatch  (Phase 2 wires Firehose→S3→Athena)
```

- A lightweight **Lambda authorizer** mints/validates the anonymous session token and passes
  `session_id` to handlers, centralizing identity logging.
- **Four handler Lambdas, four IAM roles** (`botdef-fn-catalog`, `-cart`, `-checkout`, `-admin`),
  each scoped to only the tables/actions it needs.
- Code lives in a new `app/` tree (Python handlers). Infrastructure lives in a new
  `infra/modules/app/` Terraform module, composed into `infra/envs/dev/main.tf` alongside the
  existing OIDC deploy role and budget alarm.

## Data model (DynamoDB, multi-table)

| Table | Key | Written by | Attributes |
|---|---|---|---|
| `Products` | PK `product_id` | admin-fn (seed), cart-fn (atomic `stock--`) | `title`, `price`, `stock`, `drop_at` (epoch s), `total_units` |
| `Reservations` | PK `reservation_id` | cart-fn | `product_id`, `session_id`, `ttl` (epoch s, ~5 min), `status` |
| `Orders` | PK `order_id` | checkout-fn | `reservation_id`, `product_id`, `session_id`, `created_at` |
| `Sessions` | PK `session_id` | authorizer | `created_at`, `ttl`, `request_count` (velocity signal) |

**Stock integrity.** Reserve performs a conditional `UpdateItem` on `Products`
(`stock > 0` → `stock = stock - 1`), then writes a `Reservation` with a TTL. Checkout converts a
valid Reservation into an Order. If a reservation expires unused, its unit is **not** auto-returned
in Phase 1 — the admin reset reseeds inventory and reclaims any leaked stock. A DynamoDB-Streams
reaper Lambda that increments stock on TTL delete is the documented next step.

## API surface

All responses are JSON, shaped recognizably like a retail product API so the Phase 4 adversary can
be repointed with minimal changes.

| Method · Route | Function | Auth | Behavior |
|---|---|---|---|
| `GET /products` | catalog | session | List products. Pre-`drop_at`: `status: upcoming` + `drop_at`, stock hidden. Post-drop: live availability. The pre-drop polling target. |
| `GET /products/{id}` | catalog | session | Single product detail + live availability once dropped. |
| `POST /cart` `{product_id}` | cart | session | If `now >= drop_at` and `stock > 0`: atomic decrement, create Reservation (5-min TTL), return `reservation_id`. Else `409 sold_out` or `425 too_early`. The grab race. |
| `POST /checkout` `{reservation_id}` | checkout | session | Validate reservation is owned by this session and not expired → create Order, mark reservation consumed → return `order_id`. |
| `POST /admin/reset` `{products[]}` | admin | admin secret | Reseed inventory + set new `drop_at`; clear Reservations/Orders. Repeatable-experiment control. |

**Session token.** First request with no token → authorizer mints a `session_id` and returns it via
`Set-Cookie` + JSON body; subsequent requests echo it back. Missing/invalid token on `cart`/`checkout`
→ `401`.

## Security & IAM (the headline)

- **Per-function least privilege:**
  - authorizer: `PutItem`/`UpdateItem` on `Sessions` only (mint session + increment `request_count`).
  - catalog: `dynamodb:GetItem`, `Query` on `Products` only.
  - cart: `UpdateItem` on `Products` + `PutItem` on `Reservations`.
  - checkout: `GetItem`/`UpdateItem` on `Reservations` + `PutItem` on `Orders`.
  - admin: write on `Products` + delete on `Reservations`/`Orders`.
  - No function may touch a table it does not need.
- **Admin auth:** admin secret stored in **SSM Parameter Store (SecureString)**, never in code or
  tfvars. admin-fn reads it at runtime and compares against an `X-Admin-Token` header.
- **Phase 3 hook:** the HTTP API stays internal; CloudFront + WAF wraps it later. Nothing in Phase 1
  blocks that.
- **Scanning gate:** the new `infra/modules/app/` must pass the existing Checkov + Trivy CI gates
  clean, or carry justified inline skips in the style of the Phase 0 deploy role.

## Observability hooks

- Every handler emits a **structured JSON log line** per request:
  `ts, session_id, route, method, status, latency_ms, product_id, outcome`. Phase 2 turns these (plus
  API Gateway access logs) into the Firehose → S3 → Athena data plane and, eventually, the ML feature
  set. Phase 1 guarantees the fields exist and are consistent.
- **API Gateway access logging** enabled at the stage now (JSON format), so Phase 2 has a clean
  source from day one.

## Testing

- **Unit tests** (pytest) per handler with `moto` mocking DynamoDB and SSM:
  - drop-time gating (too-early vs open),
  - atomic-decrement sold-out behavior,
  - reservation ownership and expiry on checkout,
  - admin reset reseed + clear.
- **Race test:** concurrent `POST /cart` against `stock: 1` asserts exactly one `201` and the rest
  `409` — proves the conditional write prevents oversell.
- **TDD:** tests are written before each handler.

## Out of scope for Phase 1

- CloudFront + WAF (Phase 3).
- Firehose / S3 / Athena data plane (Phase 2).
- The adversary and legit-traffic generator (Phase 4).
- The ML classifier (Phase 5).
- Credential auth / accounts, real payment processing, reservation auto-return reaper.

## Definition of done

- [x] `app/` Python handlers (authorizer, catalog, cart, checkout, admin) implemented with TDD.
- [x] `infra/modules/app/` Terraform: HTTP API, authorizer + 4 handler Lambdas, 5 least-privilege
      roles, 4 DynamoDB tables, SSM admin-secret param, stage access logging.
- [x] Module composed into `infra/envs/dev/main.tf`.
- [x] `pytest` green, including the concurrent oversell race test. (22/22, including the added
      authorizer structured-logging tests from the Task 9 verification pass.)
- [x] `terraform fmt -check`, `checkov -d infra/`, `trivy config infra/` pass (or justified skips).
      Checkov: 157 passed / 0 failed / 46 skipped (justified inline `#checkov:skip` comments in
      `infra/modules/app/{lambda,dynamodb,iam,api_gateway}.tf`, documented in the Task 9 report).
      Trivy: 0 HIGH/CRITICAL misconfigurations.
- [x] Structured per-request JSON logging present and consistent across all handlers. (Task 9
      found the authorizer handler was missing its `log_request` call — fixed forward; all 5
      handlers now import `log_request` from `common.logging` and call it on every exit path.)
