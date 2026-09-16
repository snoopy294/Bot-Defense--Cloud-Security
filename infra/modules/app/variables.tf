variable "environment" {
  description = "Environment name (e.g. dev), used only for tagging via the caller's default_tags."
  type        = string
}

variable "origin_secret" {
  description = "CloudFront origin authentication secret. Stored in encrypted Terraform state."
  type        = string
  sensitive   = true
}

variable "direct_lab_access" {
  description = "Explicit opt-in for the temporary lab without CloudFront; omit the origin header check."
  type        = bool
  default     = false
}

variable "log_retention_days" {
  type    = number
  default = 365
}

variable "enable_point_in_time_recovery" {
  type    = bool
  default = true
}

variable "reserved_concurrency" {
  description = "Per-function reserved concurrency; -1 uses the account pool for small new accounts."
  type        = number
  default     = 20
}

variable "api_rate_limit" {
  type    = number
  default = 10
}

variable "api_burst_limit" {
  type    = number
  default = 20
}

variable "admin_secret_param_name" {
  description = "SSM Parameter Store path for the admin secret. Terraform declares the name only — the value is put out-of-band (never in tfvars/state): aws ssm put-parameter --name <this> --type SecureString --value <secret>."
  type        = string
  default     = "/botdef/admin-secret"
}
