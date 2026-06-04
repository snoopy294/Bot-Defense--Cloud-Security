output "role_arn" {
  description = "ARN of the role GitHub Actions assumes. Set as the AWS_ROLE_ARN repo variable."
  value       = aws_iam_role.github_deploy.arn
}

output "oidc_provider_arn" {
  description = "ARN of the GitHub OIDC provider."
  value       = aws_iam_openid_connect_provider.github.arn
}
