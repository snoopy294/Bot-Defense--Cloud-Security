# bootstrap

One-time, **local-state** Terraform that creates the remote backend (S3 state bucket + DynamoDB
lock table) used by every other config. Run it first. See `docs/phase-0-foundation.md` §2.

```powershell
terraform init && terraform apply
terraform output backend_hcl   # paste into ../envs/dev/backend.hcl
```

Leave this stack applied between sessions — it costs effectively nothing and holds your state.
