# Temporary single-operator lab. Local state avoids a persistent paid backend.
# Do not deploy alongside envs/dev: both reuse the same app resource names.
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.8"
    }
  }
}

provider "aws" {
  region = "us-east-1"
  default_tags {
    tags = {
      Project   = "bot-defense-lab"
      ManagedBy = "terraform"
      Env       = "temporary-lab"
    }
  }
}

variable "budget_alert_email" {
  type        = string
  description = "Recipient for the lab's $1 cost alert. Alerts do not cap spending."
}

module "app" {
  source                        = "../../modules/app"
  environment                   = "temporary-lab"
  origin_secret                 = ""
  direct_lab_access             = true
  log_retention_days            = 1
  enable_point_in_time_recovery = false
  reserved_concurrency          = -1
  api_rate_limit                = 2
  api_burst_limit               = 5
}

resource "aws_budgets_budget" "lab" {
  name         = "botdef-temporary-lab"
  budget_type  = "COST"
  limit_amount = "1"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_types {
    include_credit = false
    include_refund = false
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 1
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_alert_email]
  }
}

output "app_api_endpoint" {
  value = module.app.api_endpoint
}

output "products_table_name" {
  value = module.app.products_table_name
}

output "access_log_group_name" {
  value = module.app.access_log_group_name
}
