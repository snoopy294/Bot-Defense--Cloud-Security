variable "environment" {
  description = "Environment name (e.g. dev), used only for tagging via the caller's default_tags."
  type        = string
}

variable "admin_secret_param_name" {
  description = "SSM Parameter Store path for the admin secret. Terraform declares the name only — the value is put out-of-band (never in tfvars/state): aws ssm put-parameter --name <this> --type SecureString --value <secret>."
  type        = string
  default     = "/botdef/admin-secret"
}
