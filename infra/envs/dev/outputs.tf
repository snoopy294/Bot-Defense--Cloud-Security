output "github_actions_role_arn" {
  description = "Set this as the AWS_ROLE_ARN variable in the GitHub repo (Settings → Variables)."
  value       = module.github_oidc.role_arn
}

output "app_api_endpoint" {
  description = "Origin URL for negative smoke tests. Direct requests must be rejected; use cloudfront_domain_name for the app."
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

output "cloudfront_domain_name" {
  description = "Public entry point for the drop app after Phase 3 (CloudFront + WAF). GET <this>/products to smoke-test through the new edge layer."
  value       = module.waf.cloudfront_domain_name
}

output "waf_web_acl_arn" {
  description = "ARN of the Phase 3 WAF Web ACL protecting the CloudFront distribution."
  value       = module.waf.web_acl_arn
}
