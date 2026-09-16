# AWS portfolio lab: 2026-09-16

## Deployment and cleanup

Deployed `infra/envs/lab` in us-east-1 using Terraform: 45 managed resources,
including five Lambda functions, an HTTP API, four on-demand DynamoDB tables,
six CloudWatch log groups, IAM roles/policies, and an account cost budget.
The lab had no WAF, CloudFront, Firehose, Athena, customer-managed KMS key,
remote-state backend, or provisioned Lambda concurrency.

After collecting evidence, Terraform destroyed all 45 resources. `terraform state
list` returned no resources. AWS list calls confirmed no remaining `botdef-`
Lambda functions or tables, no `botdef-app` API, and no lab CloudWatch log groups.
Synthetic inventory, orders, sessions, and cloud logs were deleted; local reports
and experiment data remain. This lab is reproducible using the
[runbook](temporary-aws-lab.md).

AWS reported an active FREE account plan with $100 credits before the experiment
and $140 credits after teardown. These are reported balances, not a finalized
usage invoice; billing can lag. No paid-plan upgrade was performed.

## Live verification

`scripts/verify_lab.py` passed all checks against real AWS services:

- Secure session cookie issued by the API.
- Cart reservation and checkout succeeded.
- Repeated checkout returned the same order ID.
- The probe's API request ID appeared in CloudWatch access logs.

Local evidence: `artifacts/lab-verification-2026-09-16.json`.

## Traffic experiment

Four independent scripted runs, each with four actors (two browsing, two polling).
The generator made 122 requests at no more than one start per second and completed
within its 250-request / 600-second bounds. All requests succeeded: 106 HTTP 200
responses and 16 HTTP 201 responses, with no transport failures or HTTP errors.

Training used 12 actors from three runs. Evaluation held out one entire run with
four actors. Both the fixed-rule baseline and logistic regression classified the
two bots and two browsing actors correctly (TP=2, TN=2, FP=0, FN=0).
Both classes completed checkout in the held-out run: this deployment detected
behavior offline but did not block bots.

Do not present these four test cases as evidence of production accuracy. Only two
scripted behaviors were exercised, and whole-session classification does not
demonstrate early detection, unseen-strategy generalization, or WAF effectiveness.
The smoke-test probe was correlated with CloudWatch; the complete experiment was
not joined against server logs before those logs were removed during teardown.

Local evidence (gitignored):

- `adversary/runs/aws-lab-2026-09-16/`: manifest, requests, independent labels.
- `detection/reports/aws-lab-2026-09-16/`: metrics, model, and Markdown report.
- Request dataset SHA-256: `478ab22c8b7d2d0893f7427007fd24bea6a94558db5dcfd8395c7dcf30ad0fb5`.
- Label dataset SHA-256: `ebe1256fec558addbabd47a05a0b36373d119e718eb8f564b98cd334aaa96e5f`.

## Code verification

67 Python tests and 7 subtests passed across app, traffic generation, detection,
and deployment verification. Terraform validation and formatting checks passed.
Trivy reported no HIGH/CRITICAL findings in the minimal lab configuration.
Checkov was not installed locally and was not run during this session; its
GitHub Actions check remains configured. Changes have not been pushed to GitHub.

## Resume bullets supported by this experiment

- Deployed and tore down a Terraform-managed AWS security lab using Lambda,
  API Gateway, DynamoDB, IAM, and CloudWatch, with cost alerts and short log retention.
- Built a bounded Python traffic generator and offline bot classifier; collected
  122 live API requests across 16 scripted actors and evaluated on held-out runs.
- Validated secure session handling, transactional checkout, retry idempotency,
  and request-to-log correlation through automated tests and live AWS verification.
