# Temporary AWS portfolio lab

Use `infra/envs/lab` for a short deploy, experiment, and teardown session.
It reuses the app module with Lambda, HTTP API Gateway, four on-demand DynamoDB
tables, one-day CloudWatch logs, and a $1 account cost alert excluding credits.
No CloudFront, WAF, Firehose, Athena, custom KMS key, remote state bucket, or CI
deployment role is created. The existing `infra/envs/dev` remains the optional
full security lab. Do not deploy both: their app resource names overlap.

## Cost and limitations

Target $0 out of pocket through eligible account credits/free allowances, not a
guarantee of free usage. Check Billing > Credits and the account plan first.
Budget alerts are delayed notifications, not spending limits. API throttling
(2 requests/second, burst 5) is best effort, not a billing cap. No provisioned
concurrency is purchased. Functions share account concurrency because new AWS
accounts may not have enough quota to reserve any. Disposable synthetic tables
have point-in-time recovery disabled. Destroy everything at the end of a session.

Direct API access is explicitly enabled in this root; sessions still work, but
this deployment does not demonstrate WAF enforcement or origin-bypass protection.
Keep the endpoint private to your experiment and use synthetic data only.
The full dev root keeps its CloudFront origin check and longer retention defaults.

## Deploy (PowerShell, repository root)

1. Run `aws login --profile botdef --region us-east-1`.
2. Copy `infra/envs/lab/terraform.tfvars.example` to `terraform.tfvars` in that same
   directory and set the alert email, unless a local file already exists.
3. Run:

```powershell
./scripts/lab.ps1 init
./scripts/lab.ps1 plan
```

Review the plan. A fresh lab should only add resources. Stop for unexpected
changes/deletions or name collisions; do not import unrelated resources.

```powershell
./scripts/lab.ps1 apply
./scripts/lab.ps1 output
```

The helper exports temporary login credentials into process memory for compatibility
with the pinned AWS provider. It restores the previous environment afterward.
State and plan files are local and gitignored. Keep state until teardown is verified;
losing it makes cleanup harder. Do not run the old bootstrap plan for this lab.

## Verify and collect evidence

Install the existing development dependencies if needed:
`python -m pip install --require-hashes -r requirements-dev.lock`.

```powershell
python scripts/verify_lab.py --acknowledge-owned-target --output artifacts/lab-verification.json
```

This reads the lab's Terraform outputs, creates a unique synthetic product with
200 units using your CLI credentials, and verifies a secure cookie, cart, repeated
checkout returning the same order, and a matching API request in CloudWatch.
It does not create an SSM admin token or reset other products. It consumes one
unit; the item remains until teardown. Log delivery can take a couple of minutes.
Do not confuse this verifier with `verify_deployment.py`, which requires the full
CloudFront/WAF/Athena stack.

```powershell
$labEndpoint = terraform -chdir=infra/envs/lab output -raw app_api_endpoint
$labHost = ([uri]$labEndpoint).Host
python -m adversary.generate --target $labEndpoint --allow-host $labHost --acknowledge-owned-target --output adversary/runs/lab-01 --runs 4 --sessions-per-run 6 --max-requests 400 --rate 1 --timeout 10 --max-seconds 600
python -m detection.evaluate --input adversary/runs/lab-01 --output detection/reports/lab-01
```

Use fresh output directories on subsequent runs. Save the verification report,
detection report, request counts, and screenshots of Lambda/API/DynamoDB/CloudWatch
as portfolio evidence. Model scores describe scripted traffic, not production bot
detection. Evaluate diverse and unseen scenarios before making effectiveness claims.

## Teardown (including after failed deployment or verification)

```powershell
./scripts/lab.ps1 destroy
terraform -chdir=infra/envs/lab state list
```

Review the destroy prompt and confirm. It removes only resources tracked in this
lab's state, including synthetic inventory, orders, logs, and the lab budget.
An empty state after a successful destroy is the Terraform cleanup check; also
check the AWS console for this lab's functions, tables, API, and log groups.
Billing may update later. Keep evidence locally; do not delete state before cleanup.

GitHub pushes now run checks only. Full dev deployment requires manually running
`deploy-dev` with its `apply` input enabled; that workflow does not deploy this lab.
