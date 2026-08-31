output "api_endpoint" {
  description = "Invoke URL for the drop app HTTP API."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "admin_secret_param_name" {
  description = "SSM parameter name to populate out-of-band: aws ssm put-parameter --name <this> --type SecureString --value <secret>."
  value       = var.admin_secret_param_name
}

output "app_log_group_names" {
  description = "CloudWatch Logs group names for the 5 app Lambda functions, consumed by Phase 2's logging module for subscription filters."
  value = [
    aws_cloudwatch_log_group.authorizer.name,
    aws_cloudwatch_log_group.catalog.name,
    aws_cloudwatch_log_group.cart.name,
    aws_cloudwatch_log_group.checkout.name,
    aws_cloudwatch_log_group.admin.name,
  ]
}

output "app_log_group_arns" {
  description = "ARNs of the 5 app Lambda log groups, consumed by Phase 2's logging module IAM policy for subscription filters."
  value = [
    aws_cloudwatch_log_group.authorizer.arn,
    aws_cloudwatch_log_group.catalog.arn,
    aws_cloudwatch_log_group.cart.arn,
    aws_cloudwatch_log_group.checkout.arn,
    aws_cloudwatch_log_group.admin.arn,
  ]
}

output "access_log_group_name" {
  description = "CloudWatch Logs group name for API Gateway access logs, consumed by Phase 2's logging module for its subscription filter."
  value       = aws_cloudwatch_log_group.access_logs.name
}

output "access_log_group_arn" {
  description = "ARN of the API Gateway access log group, consumed by Phase 2's logging module IAM policy for its subscription filter."
  value       = aws_cloudwatch_log_group.access_logs.arn
}

output "api_domain_name" {
  description = "Bare hostname (no scheme) of the drop app's API Gateway invoke URL, consumed by Phase 3's waf module as the CloudFront origin domain."
  value       = replace(aws_apigatewayv2_stage.default.invoke_url, "https://", "")
}
