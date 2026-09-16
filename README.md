# Cloud-Security Bot-Defense Lab

For the personal portfolio demonstration, start with the
[temporary AWS lab](docs/temporary-aws-lab.md): deploy a minimal serverless app,
collect evidence, then destroy it. The full architecture below is optional;
live ML scoring and automated blocking remain future work. Ordinary GitHub pushes
run checks only and do not deploy infrastructure.

Completed a live deploy, verification, traffic experiment, and teardown on
2026-09-16. See the [experiment results](docs/aws-lab-results-2026-09-16.md).

A personal security lab combining a Terraform-managed AWS shopping API, a bounded
traffic generator, and an offline behavioral bot classifier. The minimal AWS app
can be deployed for an experiment and removed afterward; the classifier runs locally.

> **Origin:** This project evolved from a Pokemon TCG stock monitor (`pokemon-monitor/`). That bot
> inspired the lab. The separate `adversary/` generator uses scripted browsing and
> polling against a target we own. It does not reuse retailer adapters or browser evasion.

## The three acts

| Act | Lives in | Proves |
|-----|----------|--------|
| **Traffic** | `adversary/` | bounded experiments and independent labels |
| **Detector** (ML)  | `detection/` | security data science |
| **Cloud** (defense)| `infra/`, `app/` | cloud security engineering ← the headline |

## Architecture

The diagram below is the full design, not the temporary lab's deployed scope.
Server-log ingestion into ML, GuardDuty/Security Hub integration, and automatic
blocking remain future work. The temporary lab uses API Gateway, Lambda,
DynamoDB, and CloudWatch; detection consumes client observations locally.

```
 adversary/  ──►  CloudFront + WAF  ──►  API Gateway ──► Lambda (drop app) ──► DynamoDB
                       │                        │
                       └── access logs ─────────┴──► Firehose ──► S3 ──► Athena
                                                                   │
 detection/ (ML classifier: bot vs human)  ◄───────────────────────┘
                       │
 GuardDuty + Security Hub  ·  CloudWatch Alarm ──► SNS ──► auto-block Lambda (WAF)
```

## Repository layout

```
infra/        Terraform — the cloud-security core
  bootstrap/    one-time: creates the remote-state S3 bucket + lock table (local state)
  modules/      reusable modules (iam-oidc, waf, app, logging)
  envs/dev/     the composable, fully destroyable dev environment
  envs/lab/     minimal temporary lab with local state; no bootstrap required
app/          the "drop" target app (Lambda handlers: products, checkout)
detection/    offline logistic regression and fixed-rule baseline
adversary/    owned-target scripted browsing and polling generator
docs/         threat model, architecture diagram, detection report, runbooks
.github/      CI: IaC security scanning + keyless (OIDC) deploy
```

## Cost model

The temporary lab targets $0 out of pocket using eligible free allowances and account
credits. Confirm the plan and credit balance in AWS Billing before deployment.
Usage can consume credits; a budget alert is not a spending cap. Destroy the lab
after collecting evidence. The optional full dev stack has additional costs.
See [the temporary lab runbook](docs/temporary-aws-lab.md).

## Build phases

Each phase is a self-contained, resume-worthy increment. See the plan file and `docs/` for detail.

0. **Foundation & guardrails** — Terraform backend, OIDC CI, IaC scanning, budget alarm
1. Target "drop" app (serverless)
2. Observability / SOC data plane
3. Cloud-native bot defense (WAF)
4. Adversary + labeled datasets
5. ML detection
6. Detection engineering & automated response
7. Writeup (threat model, detection report, resume bullets)
