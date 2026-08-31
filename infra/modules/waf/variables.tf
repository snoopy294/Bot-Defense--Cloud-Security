variable "environment" {
  description = "Environment name (e.g. dev), used only for tagging via the caller's default_tags and in resource names."
  type        = string
}

variable "api_domain_name" {
  description = "Bare hostname of the app's API Gateway invoke URL (module.app.api_domain_name), used as the CloudFront origin domain."
  type        = string
}
