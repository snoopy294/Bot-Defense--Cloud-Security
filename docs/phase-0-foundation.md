# Phase 0 — Cloud Foundation & Guardrails (runbook)

Goal: a reproducible, security-scanned IaC pipeline and a keyless deploy path — **before** any
app or AWS spend. Everything here either costs nothing or runs inside the free account plan.

## 0. Install the toolchain (free, one-time)

On Windows with winget:

```powershell
winget install --id Hashicorp.Terraform -e
winget install --id Amazon.AWSCLI -e
winget install --id Python.Python.3.12 -e   # if you prefer 3.12; 3.14 is already present
pip install checkov
winget install --id AquaSecurity.Trivy -e
```

Verify: `terraform -version`, `aws --version`, `checkov --version`, `trivy --version`.

## 1. Create the AWS account (free account plan)

1. Sign up at https://aws.amazon.com/free/ and choose the **free account plan** (it cannot incur
   cash charges until you manually upgrade; gives ~$100 credits). A card is required for identity
   only.
2. Do **not** use the root user for daily work. Create an IAM admin user (or IAM Identity Center
   user), enable MFA on both root and that user.
3. Configure the CLI locally: `aws configure` (or `aws configure sso`). Confirm with
   `aws sts get-caller-identity`.

## 2. Bootstrap the remote state backend (one-time)

```powershell
cd infra/bootstrap
terraform init
terraform apply          # creates the encrypted, versioned state bucket + lock table
terraform output backend_hcl
```

Copy that output into `infra/envs/dev/backend.hcl` (use `backend.hcl.example` as the template).

## 3. Stand up the dev environment

```powershell
cd ../envs/dev
copy terraform.tfvars.example terraform.tfvars   # then edit github_repo + email
terraform init -backend-config=backend.hcl
terraform plan
terraform apply          # creates the GitHub OIDC deploy role + zero-spend budget
terraform output github_actions_role_arn
```

## 4. Wire up GitHub (keyless CI)

1. Create the GitHub repo (matching `github_repo` in tfvars) and push this code.
2. In the repo: **Settings → Secrets and variables → Actions → Variables**, add a repository
   variable `AWS_ROLE_ARN` = the `github_actions_role_arn` output.
3. Push to `main`. The `iac-security-scan` workflow runs with no credentials; `deploy-dev` assumes
   the role via OIDC — confirm there are **zero** access keys stored anywhere.

## 5. Tear down between sessions (conserve credits)

```powershell
cd infra/envs/dev
terraform destroy
```

The bootstrap backend (S3 + DynamoDB) can stay — it costs effectively nothing (pay-per-request +
a tiny encrypted bucket) and is needed to track state.

## Known tradeoffs (be ready to explain these in an interview)

- **Deploy role breadth:** the CI role manages the whole dev stack, so it grants broad service
  actions with narrow IAM (`botdef-*` roles only). The right next step is per-service ARN/tag
  scoping; left wide on purpose early to avoid churn while the architecture moves.
- **State bucket = crown jewels:** it is KMS-encrypted, versioned, TLS-only, and fully
  public-access-blocked. Anyone with read on it can read secrets in state — treat accordingly.
- **`.terraform.lock.hcl` is gitignored for now;** commit it (remove the ignore line) once provider
  versions should be pinned for reproducible CI.

## Phase 0 done when

- [ ] `terraform fmt -check -recursive infra/` passes
- [ ] `checkov -d infra/` and `trivy config infra/` pass (or findings are triaged/justified)
- [ ] `aws sts get-caller-identity` works locally
- [ ] bootstrap applied; dev applied; OIDC role ARN output exists
- [ ] a push to `main` runs the scan workflow green and the deploy workflow assumes the role
- [ ] AWS Budgets shows the zero-spend guard active
