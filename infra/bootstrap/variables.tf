variable "region" {
  description = "AWS region for the state backend. Use us-east-1 — CloudFront/WAF require it later."
  type        = string
  default     = "us-east-1"
}

variable "state_bucket_prefix" {
  description = "Prefix for the state bucket; the account ID is appended for global uniqueness."
  type        = string
  default     = "botdef-tfstate"
}

variable "lock_table_name" {
  description = "DynamoDB table name used for Terraform state locking."
  type        = string
  default     = "botdef-tflock"
}
