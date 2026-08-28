output "api_endpoint" {
  description = "Invoke URL for the drop app HTTP API."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "admin_secret_param_name" {
  description = "SSM parameter name to populate out-of-band: aws ssm put-parameter --name <this> --type SecureString --value <secret>."
  value       = var.admin_secret_param_name
}
