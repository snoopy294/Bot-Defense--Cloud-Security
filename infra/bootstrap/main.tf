# ---------------------------------------------------------------------------
# Bootstrap: create the remote Terraform state backend.
#
# Run ONCE, before any other Terraform. It uses LOCAL state (you can't store
# the state bucket's own state inside itself). After `apply`, copy the outputs
# into infra/envs/dev/backend.hcl so every other config uses remote state.
#
#   cd infra/bootstrap
#   terraform init && terraform apply
# ---------------------------------------------------------------------------

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "bot-defense-lab"
      ManagedBy = "terraform"
      Component = "bootstrap"
    }
  }
}

# Account ID is appended to the bucket name to keep it globally unique.
data "aws_caller_identity" "current" {}

locals {
  bucket_name = "${var.state_bucket_prefix}-${data.aws_caller_identity.current.account_id}"
}

# --- Customer-managed KMS key for state-at-rest -----------------------------
# The state bucket can contain secrets, so we encrypt it (and the lock table)
# with a CMK we control: automatic annual rotation + an explicit key policy.
# Cost note: a CMK is ~$1/mo, drawn from free-plan credits (not cash). To stay
# strictly $0 instead, delete this key and switch SSE back to "aws:kms" with no
# key_id (AWS-managed key) — then add #checkov:skip for CKV_AWS_119/AWS-0132.
resource "aws_kms_key" "state" {
  description             = "CMK for Terraform state bucket + lock table"
  enable_key_rotation     = true
  deletion_window_in_days = 7

  # Explicit key policy: delegate administration to the account root (the AWS
  # default), so IAM policies in this account govern usage. Without the root
  # grant a CMK can become unmanageable ("locked out").
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "EnableAccountRootAdmin"
      Effect    = "Allow"
      Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
      Action    = "kms:*"
      Resource  = "*"
    }]
  })
}

resource "aws_kms_alias" "state" {
  name          = "alias/botdef-tfstate"
  target_key_id = aws_kms_key.state.key_id
}

# --- S3 bucket that stores Terraform state ---------------------------------
resource "aws_s3_bucket" "state" {
  bucket = local.bucket_name

  #checkov:skip=CKV_AWS_18:Access logging needs a second bucket + recurring cost; not justified for a single-user lab state bucket. Revisit if multi-user.
  #checkov:skip=CKV_AWS_144:Cross-region replication is out of scope (YAGNI, doubles cost) for a personal lab.
  #checkov:skip=CKV2_AWS_62:Event notifications add no value for a Terraform state bucket.
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled" # keep history so a bad apply can be rolled back
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.state.arn # CMK, not the AWS-managed key
    }
    bucket_key_enabled = true # reduces KMS API calls (and cost) on every object op
  }
}

# Expire old state versions so the versioned bucket doesn't grow unbounded.
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "expire-noncurrent-state"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Refuse any non-TLS request to the state bucket.
resource "aws_s3_bucket_policy" "state_tls_only" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.state.arn,
        "${aws_s3_bucket.state.arn}/*",
      ]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

# --- DynamoDB table for state locking --------------------------------------
resource "aws_dynamodb_table" "lock" {
  name         = var.lock_table_name
  billing_mode = "PAY_PER_REQUEST" # always-free-tier friendly; no idle cost
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.state.arn # CMK, satisfies CKV_AWS_119
  }
}
