variable "region" {
  description = "AWS region for the dev environment. Keep us-east-1 for CloudFront/WAF compatibility."
  type        = string
  default     = "us-east-1"
}

variable "github_repo" {
  description = "GitHub repo in 'owner/name' form that CI deploys from."
  type        = string
}

variable "budget_alert_email" {
  description = "Email to notify if any spend appears (defense-in-depth on the free plan)."
  type        = string
}
