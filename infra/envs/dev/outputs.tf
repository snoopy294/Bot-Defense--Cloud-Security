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

output "logs_bucket_name" {
  description = "S3 bucket holding Phase 2 raw logs (app/ and apigw/ prefixes)."
  value       = module.logging.logs_bucket_name
}

output "athena_workgroup" {
  description = "Athena workgroup for querying Phase 2 logs. See docs/phase-2-observability.md for the join query."
  value       = module.logging.athena_workgroup
}
