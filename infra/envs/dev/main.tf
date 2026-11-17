# ---------------------------------------------------------------------------
# Dev environment root. Phase 0 provisions only:
#   - the GitHub Actions OIDC deploy role (keyless CI)
#   - a zero-spend budget alarm (cost guardrail)
# Later phases add app/, logging/, waf/, detection/, response/ modules here.
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  deploy_role_name = "botdef-github-actions-deploy"
  deploy_role_arn  = "arn:aws:iam::${local.account_id}:role/${local.deploy_role_name}"

  # Built as a string (not aws_iam_policy.boundary.arn) so the policy documents
  # below can reference it without a dependency cycle.
  boundary_policy_name = "botdef-permissions-boundary"
  boundary_policy_arn  = "arn:aws:iam::${local.account_id}:policy/${local.boundary_policy_name}"

  project_roles_arn = "arn:aws:iam::${local.account_id}:role/botdef-*"

  # Bootstrap defaults: state_bucket_prefix = "botdef-tfstate", lock_table_name = "botdef-tflock".
  state_bucket_arn = "arn:aws:s3:::botdef-tfstate-${local.account_id}"
}

# ---------------------------------------------------------------------------
# CI deploy role permissions (identity policy).
#
# Data-plane services with stable botdef-* names are scoped to ARNs. Services
# whose Terraform calls need account-level List/Describe actions (API Gateway,
# CloudFront, WAF, CloudWatch Logs, Athena, Glue) stay service-wide for now; the
# permissions boundary below caps them and blocks IAM self-escalation.
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "deploy" {
  #checkov:skip=CKV_AWS_111:Accepted — remaining write access on "*" is for API Gateway/CloudFront/WAF/Logs/Athena/Glue, whose Terraform calls need account-level actions; capped by the botdef permissions boundary.
  #checkov:skip=CKV_AWS_356:Accepted — same services as above; ARN-scope them per phase.
  #checkov:skip=CKV_AWS_109:Accepted — logs/wafv2/apigateway resource-policy actions on "*" (HTTP API access-log delivery needs them); IAM itself is boundary-capped and botdef-* scoped.
  statement {
    sid    = "AccountScopedStackServices"
    effect = "Allow"
    actions = [
      "apigateway:*",
      "cloudfront:*",
      "wafv2:*",
      "logs:*",
      "athena:*",
    ]
    resources = ["*"]
  }

  # Athena schema catalog: database/table/partition management only (no dev
  # endpoints, jobs, or resource policies).
  statement {
    sid = "GlueCatalog"
    actions = [
      "glue:*Database", "glue:*Databases",
      "glue:*Table", "glue:*Tables", "glue:*TableVersion", "glue:*TableVersions",
      "glue:*Partition", "glue:*Partitions", "glue:GetPartitionIndexes",
      "glue:GetTags", "glue:TagResource", "glue:UntagResource",
    ]
    resources = [
      "arn:aws:glue:${var.region}:${local.account_id}:catalog",
      "arn:aws:glue:${var.region}:${local.account_id}:database/botdef_*",
      "arn:aws:glue:${var.region}:${local.account_id}:table/botdef_*/*",
    ]
  }

  statement {
    sid       = "ProjectBuckets"
    actions   = ["s3:*"]
    resources = ["arn:aws:s3:::botdef-logs-*", "arn:aws:s3:::botdef-logs-*/*"]
  }

  # Remote state: object read/write only — no bucket config or deletion.
  statement {
    sid       = "StateBucketList"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [local.state_bucket_arn]
  }

  statement {
    sid       = "StateObjects"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.state_bucket_arn}/*"]
  }

  # App tables + the botdef-tflock state lock table (and their indexes).
  statement {
    sid       = "ProjectTables"
    actions   = ["dynamodb:*"]
    resources = ["arn:aws:dynamodb:${var.region}:${local.account_id}:table/botdef-*"]
  }

  statement {
    sid       = "ProjectFunctions"
    actions   = ["lambda:*"]
    resources = ["arn:aws:lambda:${var.region}:${local.account_id}:function:botdef-*"]
  }

  statement {
    sid     = "ProjectDeliveryStreams"
    actions = ["firehose:*"]
    resources = [
      "arn:aws:firehose:${var.region}:${local.account_id}:deliverystream/botdef-*",
      "arn:aws:firehose:${var.region}:${local.account_id}:deliverystream/aws-waf-logs-botdef-*",
    ]
  }

  statement {
    sid       = "ProjectBudgets"
    actions   = ["budgets:*"]
    resources = ["arn:aws:budgets::${local.account_id}:budget/botdef-*"]
  }

  # IAM is granted narrowly: only roles under this project's name prefix.
  # No AttachRolePolicy: every project role uses inline policies.
  statement {
    sid    = "ProjectIamRoles"
    effect = "Allow"
    actions = [
      "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:UntagRole",
      "iam:DetachRolePolicy",
      "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy",
      "iam:PassRole", "iam:UpdateAssumeRolePolicy", "iam:UpdateRole",
      "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListInstanceProfilesForRole",
    ]
    resources = [local.project_roles_arn]
  }

  # New roles (and boundary changes on existing ones) must carry the boundary.
  statement {
    sid       = "CreateProjectRolesWithBoundary"
    actions   = ["iam:CreateRole", "iam:PutRolePermissionsBoundary"]
    resources = [local.project_roles_arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [local.boundary_policy_arn]
    }
  }

  # Read-only on the boundary so CI can refresh it; changes are admin-applied.
  statement {
    sid       = "ReadPermissionsBoundary"
    actions   = ["iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicyVersions", "iam:ListPolicyTags"]
    resources = [local.boundary_policy_arn]
  }

  statement {
    sid       = "EncryptedStateAccess"
    actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [var.state_kms_key_arn]
  }

  statement {
    sid = "GithubOidcProviderManagement"
    actions = [
      "iam:GetOpenIDConnectProvider", "iam:CreateOpenIDConnectProvider",
      "iam:DeleteOpenIDConnectProvider", "iam:UpdateOpenIDConnectProviderThumbprint",
      "iam:AddClientIDToOpenIDConnectProvider", "iam:RemoveClientIDFromOpenIDConnectProvider",
      "iam:TagOpenIDConnectProvider", "iam:UntagOpenIDConnectProvider", "iam:ListOpenIDConnectProviderTags",
    ]
    resources = ["arn:aws:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com"]
  }

  # WAF logging can create its delivery service-linked role on first deploy.
  statement {
    sid       = "WafLoggingServiceRole"
    actions   = ["iam:CreateServiceLinkedRole"]
    resources = ["arn:aws:iam::${local.account_id}:role/aws-service-role/wafv2.amazonaws.com/AWSServiceRoleForWAFV2Logging"]
    condition {
      test     = "StringEquals"
      variable = "iam:AWSServiceName"
      values   = ["wafv2.amazonaws.com"]
    }
  }
}

# Runtime needs of the workload roles (Lambda, Firehose, CWL subscription) that
# the deploy statements above don't already cover.
data "aws_iam_policy_document" "workload_runtime" {
  statement {
    sid       = "AppAdminSecretRead"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.region}:${local.account_id}:parameter/botdef/*"]
  }

  statement {
    sid       = "AppAdminSecretDecrypt"
    actions   = ["kms:Decrypt"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.region}.amazonaws.com"]
    }
  }
}

# ---------------------------------------------------------------------------
# Permissions boundary: the ceiling for the deploy role AND every botdef-* role
# it creates. Allows = deploy + workload needs; explicit denies close the
# self-escalation paths (editing the deploy role, editing/removing the boundary,
# creating unbounded roles). Changes to this policy or to the deploy role must
# be applied by an admin locally — CI is denied by design.
# ---------------------------------------------------------------------------
#trivy:ignore:AWS-0345 s3:* is inherited from the deploy policy and resource-scoped to botdef-logs-* buckets only.
data "aws_iam_policy_document" "boundary" {
  source_policy_documents = [
    data.aws_iam_policy_document.deploy.json,
    data.aws_iam_policy_document.workload_runtime.json,
  ]

  statement {
    sid    = "DenyBoundaryPolicyChanges"
    effect = "Deny"
    actions = [
      "iam:CreatePolicy", "iam:CreatePolicyVersion", "iam:DeletePolicy", "iam:DeletePolicyVersion",
      "iam:SetDefaultPolicyVersion", "iam:TagPolicy", "iam:UntagPolicy",
    ]
    resources = [local.boundary_policy_arn]
  }

  statement {
    sid    = "DenyDeployRoleSelfModification"
    effect = "Deny"
    actions = [
      "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:AttachRolePolicy", "iam:DetachRolePolicy",
      "iam:PutRolePermissionsBoundary", "iam:DeleteRolePermissionsBoundary",
      "iam:UpdateAssumeRolePolicy", "iam:UpdateRole", "iam:DeleteRole",
      "iam:TagRole", "iam:UntagRole", "iam:PassRole",
    ]
    resources = [local.deploy_role_arn]
  }

  statement {
    sid       = "DenyBoundaryRemoval"
    effect    = "Deny"
    actions   = ["iam:DeleteRolePermissionsBoundary"]
    resources = [local.project_roles_arn]
  }

  statement {
    sid       = "DenyRolesWithoutThisBoundary"
    effect    = "Deny"
    actions   = ["iam:CreateRole", "iam:PutRolePermissionsBoundary"]
    resources = ["*"]
    condition {
      test     = "StringNotEquals"
      variable = "iam:PermissionsBoundary"
      values   = [local.boundary_policy_arn]
    }
  }
}

resource "aws_iam_policy" "boundary" {
  name        = local.boundary_policy_name
  description = "Permissions boundary for the CI deploy role and all botdef-* roles it creates."
  policy      = data.aws_iam_policy_document.boundary.json
}

module "github_oidc" {
  source                   = "../../modules/iam-oidc"
  github_repo              = var.github_repo
  role_name                = local.deploy_role_name
  permissions_policy_json  = data.aws_iam_policy_document.deploy.json
  permissions_boundary_arn = aws_iam_policy.boundary.arn
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
resource "random_password" "origin" {
  length  = 64
  special = false
}

module "app" {
  source                   = "../../modules/app"
  environment              = "dev"
  permissions_boundary_arn = aws_iam_policy.boundary.arn
  origin_secret            = random_password.origin.result
}

# ---------------------------------------------------------------------------
# Phase 2: observability / SOC data plane — Firehose -> S3 -> Athena for both
# the app's structured logs and API Gateway access logs, correlated by
# request_id.
# ---------------------------------------------------------------------------
module "logging" {
  source                   = "../../modules/logging"
  environment              = "dev"
  permissions_boundary_arn = aws_iam_policy.boundary.arn
  app_log_group_names      = module.app.app_log_group_names
  apigw_log_group_name     = module.app.access_log_group_name
}

# ---------------------------------------------------------------------------
# Phase 3: cloud-native bot defense — CloudFront + WAF in front of the app's
# API Gateway, with WAF request logs flowing into the Phase 2 logs bucket.
# ---------------------------------------------------------------------------
module "waf" {
  source                   = "../../modules/waf"
  environment              = "dev"
  permissions_boundary_arn = aws_iam_policy.boundary.arn
  api_domain_name          = module.app.api_domain_name
  logs_bucket_name         = module.logging.logs_bucket_name
  logs_bucket_arn          = module.logging.logs_bucket_arn
  glue_database            = module.logging.glue_database
  origin_secret            = random_password.origin.result
}
