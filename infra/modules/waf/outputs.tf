output "cloudfront_domain_name" {
  description = "CloudFront distribution domain name — the drop app's new public entry point after Phase 3."
  value       = aws_cloudfront_distribution.app.domain_name
}

output "web_acl_arn" {
  description = "ARN of the WAF Web ACL protecting the CloudFront distribution."
  value       = aws_wafv2_web_acl.app.arn
}
