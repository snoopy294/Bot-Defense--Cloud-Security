# ---------------------------------------------------------------------------
# GitHub Actions OIDC: lets CI assume an AWS role using a short-lived OIDC
# token instead of long-lived access keys stored as GitHub secrets.
#
# This is the "no static credentials" best practice worth showcasing.
# ---------------------------------------------------------------------------

# GitHub's OIDC identity provider. The thumbprint is no longer validated by AWS
# for this well-known provider, but a value is still required by the API.
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

data "aws_iam_policy_document" "trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    # Audience must be the AWS STS audience.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Restrict to THIS repo, and only the branches/refs we allow.
    # e.g. "repo:my-org/bot-defense-lab:ref:refs/heads/main"
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [for ref in var.allowed_refs : "repo:${var.github_repo}:${ref}"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = var.role_name
  assume_role_policy = data.aws_iam_policy_document.trust.json
  description        = "Assumed by GitHub Actions via OIDC to deploy the bot-defense lab."
}

# Permissions are intentionally passed in so the caller can scope them per use.
# Phase 0 starts narrow; later phases widen as new services are introduced.
resource "aws_iam_role_policy" "deploy_permissions" {
  name   = "${var.role_name}-permissions"
  role   = aws_iam_role.github_deploy.id
  policy = var.permissions_policy_json
}
