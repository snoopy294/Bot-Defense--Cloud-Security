output "github_actions_role_arn" {
  description = "Set this as the AWS_ROLE_ARN variable in the GitHub repo (Settings → Variables)."
  value       = module.github_oidc.role_arn
}
