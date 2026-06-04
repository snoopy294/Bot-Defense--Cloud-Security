# Cloud-Security Bot-Defense Lab

A portfolio-grade security project that proves **offense + ML detection + cloud security** in one
repository. An ML-powered bot-detection system is deployed and hardened on **AWS** (Terraform IaC),
and a repurposed retail-stock bot acts as the live adversary that generates attack traffic so the
defenses can be measured.

> **Origin:** This project evolved from a Pokemon TCG stock monitor (`pokemon-monitor/`). That bot
> already implements real evasion tradecraft (fingerprint spoofing, headless-browser stealth,
> request rotation), so it is reused as the *attacker* against a target app **we own** — never
> against third-party retailers.

## The three acts

| Act | Lives in | Proves |
|-----|----------|--------|
| **Attacker** (red) | `adversary/` | recon & evasion tradecraft |
| **Detector** (ML)  | `detection/` | security data science |
| **Cloud** (defense)| `infra/`, `app/` | cloud security engineering ← the headline |

## Architecture

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
  modules/      reusable modules (iam-oidc, waf, app, logging, detection, response)
  envs/dev/     the composable, fully destroyable dev environment
app/          the "drop" target app (Lambda handlers: products, checkout)
detection/    ML classifier (reuses Log-Anomaly-Detector patterns)
adversary/    the attacker (repurposed pokemon-monitor) + a legit-traffic generator
docs/         threat model, architecture diagram, detection report, runbooks
.github/      CI: IaC security scanning + keyless (OIDC) deploy
```

## Cost model

Runs on the **AWS Free Tier "free account plan"**: $100 signup credits, and the plan *cannot incur
cash charges* until you manually upgrade to a paid plan. WAF/GuardDuty draw down credits, not cash.
`terraform destroy` between sessions keeps consumption near zero. See `docs/phase-0-foundation.md`.

## Build phases

Each phase is a self-contained, resume-worthy increment. See the plan file and `docs/` for detail.

0. **Foundation & guardrails** — Terraform backend, OIDC CI, IaC scanning, budget alarm ← *you are here*
1. Target "drop" app (serverless)
2. Observability / SOC data plane
3. Cloud-native bot defense (WAF)
4. Adversary + labeled datasets
5. ML detection
6. Detection engineering & automated response
7. Writeup (threat model, detection report, resume bullets)
```
