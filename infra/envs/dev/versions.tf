terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state. Partial config — supply values at init time:
  #   terraform init -backend-config=backend.hcl
  backend "s3" {}
}
