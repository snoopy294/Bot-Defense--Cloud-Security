# ---------------------------------------------------------------------------
# Dev environment root. Phase 0 provisions only:
#   - the GitHub Actions OIDC deploy role (keyless CI)
#   - a zero-spend budget alarm (cost guardrail)
# Later phases add app/, logging/, waf/, detection/, response/ modules here.
# ---------------------------------------------------------------------------

# Permissions for the CI deploy role. Scoped to the services this lab uses.
# NOTE: this is a deploy role that manages the whole dev stack, so it is broad
# by necessity. Tighten per-service as phases stabilize (e.g. resource ARNs,
# tag conditions). Documented as a known tradeoff in docs/phase-0-foundation.md.
# trivy:ignore:aws-0345 Broad deploy role accepted during active development (see skips below).
data "aws_iam_policy_document" "deploy" {
  # ACCEPTED RISK — broad CI deploy role. Mitigations: (1) the OIDC trust policy
  # restricts assumption to THIS repo + chosen branches only; (2) IAM actions are
  # already scoped to botdef-* ARNs. Remediation roadmap: tighten each service to
  # resource ARNs / tag conditions as that phase's resources stabilize, and add a
  # permissions boundary. Tracked in docs/phase-0-foundation.md "Known tradeoffs".
  #checkov:skip=CKV_AWS_108:Accepted — see roadmap note above. No s3:Get*+network egress combo intended; deploy-only.
  #checkov:skip=CKV_AWS_109:Accepted — permissions-management actions are inherent to a Terraform deploy role.
  #checkov:skip=CKV_AWS_110:Accepted — IAM scoped to botdef-* roles; OIDC trust is repo-scoped. Tighten per phase.
  #checkov:skip=CKV_AWS_111:Accepted — write access is the job of a deploy role; constrained by repo-scoped OIDC.
  #checkov:skip=CKV_AWS_356:Accepted — service-level wildcards on "*" pending per-phase ARN scoping.
  statement {
    sid    = "CoreStackServices"
    effect = "Allow"
    actions = [
      "s3:*",
      "dynamodb:*",
      "lambda:*",
      "apigateway:*",
      "cloudfront:*",
      "wafv2:*",
      "logs:*",
      "firehose:*",
      "cloudwatch:*",
      "sns:*",
      "athena:*",
      "glue:*", # Athena schema catalog
      "budgets:*",
      "guardduty:*",
      "securityhub:*",
    ]
    resources = ["*"] # most of these services are region/account scoped, not ARN-filterable here
  }

  # IAM is granted narrowly: only roles/policies under this project's path.
  statement {
    sid    = "ProjectIamOnly"
    effect = "Allow"
    actions = [
      "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole",
      "iam:AttachRolePolicy", "iam:DetachRolePolicy",
      "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy",
      "iam:PassRole",
    ]
    resources = ["arn:aws:iam::*:role/botdef-*"]
  }
}

module "github_oidc" {
  source                  = "../../modules/iam-oidc"
  github_repo             = var.github_repo
  role_name               = "botdef-github-actions-deploy"
  permissions_policy_json = data.aws_iam_policy_document.deploy.json
}

# ---------------------------------------------------------------------------
# Cost guardrail: alert if monthly spend exceeds $1. On the free account plan
# this should never fire, but it is defense-in-depth and a good habit to show.
# ---------------------------------------------------------------------------
resource "aws_budgets_budget" "zero_spend" {
  name         = "botdef-zero-spend-guard"
  budget_type  = "COST"
  limit_amount = "1.0"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 1
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}

# ---------------------------------------------------------------------------
# Phase 1: the "drop" target app that later phases attack, log, and defend.
# ---------------------------------------------------------------------------
module "app" {
  source      = "../../modules/app"
  environment = "dev"
}

# ---------------------------------------------------------------------------
# Phase 2: observability / SOC data plane — Firehose -> S3 -> Athena for both
# the app's structured logs and API Gateway access logs, correlated by
# request_id.
# ---------------------------------------------------------------------------
module "logging" {
  source               = "../../modules/logging"
  environment          = "dev"
  app_log_group_names  = module.app.app_log_group_names
  apigw_log_group_name = module.app.access_log_group_name
}
