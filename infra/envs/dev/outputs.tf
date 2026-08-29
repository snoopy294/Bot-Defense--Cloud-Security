output "github_actions_role_arn" {
  description = "Set this as the AWS_ROLE_ARN variable in the GitHub repo (Settings → Variables)."
  value       = module.github_oidc.role_arn
}

output "app_api_endpoint" {
  description = "Invoke URL for the Phase 1 drop app. GET <this>/products to smoke-test."
  value       = module.app.api_endpoint
}

output "app_admin_secret_param_name" {
  description = "Populate this SSM parameter out-of-band before calling POST /admin/reset: aws ssm put-parameter --name <this> --type SecureString --value <secret>."
  value       = module.app.admin_secret_param_name
}
