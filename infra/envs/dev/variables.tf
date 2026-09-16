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

variable "state_kms_key_arn" {
  description = "Bootstrap state KMS key ARN, used to grant the deploy role access to encrypted state."
  type        = string
  validation {
    condition     = can(regex("^arn:aws:kms:us-east-1:[0-9]{12}:key/", var.state_kms_key_arn))
    error_message = "Use the bootstrap state KMS key ARN in us-east-1."
  }
}
