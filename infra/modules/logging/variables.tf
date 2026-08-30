variable "environment" {
  description = "Environment name (e.g. dev), used only for tagging via the caller's default_tags."
  type        = string
}

variable "app_log_group_names" {
  description = "CloudWatch Logs group names for the app Lambda functions (module.app.app_log_group_names), subscribed into the app-logs Firehose stream."
  type        = list(string)
}

variable "apigw_log_group_name" {
  description = "CloudWatch Logs group name for API Gateway access logs (module.app.access_log_group_name), subscribed into the apigw-logs Firehose stream."
  type        = string
}
