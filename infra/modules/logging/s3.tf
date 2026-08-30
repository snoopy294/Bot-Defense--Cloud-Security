data "aws_caller_identity" "current" {}

# Account ID is appended to keep the bucket name globally unique, matching
# infra/bootstrap's state-bucket convention.
resource "aws_s3_bucket" "logs" {
  bucket = "botdef-logs-${var.environment}-${data.aws_caller_identity.current.account_id}"

  #checkov:skip=CKV_AWS_18:Accepted — access logging needs a second bucket + recurring cost; not justified for a single-user lab logs bucket. Revisit if multi-user.
  #checkov:skip=CKV_AWS_144:Accepted — cross-region replication is out of scope (YAGNI, doubles cost) for a personal lab.
  #checkov:skip=CKV2_AWS_62:Accepted — event notifications add no value for a log-landing bucket.
}

resource "aws_s3_bucket_versioning" "logs" {
  bucket = aws_s3_bucket.logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    apply_server_side_encryption_by_default {
      # checkov:skip=CKV_AWS_145:Accepted — SSE-S3 (AES256) default encryption, matching the
      # accepted tradeoff on the 4 app DynamoDB tables (infra/modules/app/dynamodb.tf). A
      # customer-managed KMS key adds ~$1/mo with no meaningful risk reduction for this lab's
      # synthetic traffic logs. Revisit if real PII ever enters the pipeline.
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# Keep the actively-destroyed dev environment cheap: raw logs expire after 30
# days rather than accumulating indefinitely.
resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    id     = "expire-old-logs"
    status = "Enabled"
    filter {}
    expiration {
      days = 30
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket                  = aws_s3_bucket.logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "logs_tls_only" {
  bucket = aws_s3_bucket.logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.logs.arn,
        "${aws_s3_bucket.logs.arn}/*",
      ]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}
