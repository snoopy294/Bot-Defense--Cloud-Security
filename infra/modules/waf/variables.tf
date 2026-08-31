variable "environment" {
  description = "Environment name (e.g. dev), used only for tagging via the caller's default_tags and in resource names."
  type        = string
}

variable "api_domain_name" {
  description = "Bare hostname of the app's API Gateway invoke URL (module.app.api_domain_name), used as the CloudFront origin domain."
  type        = string
}

variable "logs_bucket_name" {
  description = "Name of the Phase 2 logs bucket (module.logging.logs_bucket_name), used as the WAF log Firehose destination and Glue table location."
  type        = string
}

variable "logs_bucket_arn" {
  description = "ARN of the Phase 2 logs bucket (module.logging.logs_bucket_arn), used to scope the WAF Firehose delivery IAM policy."
  type        = string
}

variable "glue_database" {
  description = "Name of the Phase 2 Glue Catalog database (module.logging.glue_database), used as the parent database for the new waf_logs table."
  type        = string
}
