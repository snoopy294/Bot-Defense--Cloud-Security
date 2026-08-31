data "aws_iam_policy_document" "firehose_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }
  }
}

# One delivery role for both streams, scoped to only this bucket.
resource "aws_iam_role" "firehose" {
  name               = "botdef-firehose-delivery-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.firehose_trust.json
}

resource "aws_iam_role_policy" "firehose" {
  name = "botdef-firehose-delivery-policy-${var.environment}"
  role = aws_iam_role.firehose.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetBucketLocation",
          "s3:ListBucket",
          "s3:AbortMultipartUpload",
          "s3:ListBucketMultipartUploads",
          "s3:GetObject",
          "s3:PutObjectAcl",
        ]
        Resource = [
          aws_s3_bucket.logs.arn,
          "${aws_s3_bucket.logs.arn}/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:PutLogEvents",
          "logs:CreateLogStream",
        ]
        Resource = [
          aws_cloudwatch_log_group.firehose_errors.arn,
          "${aws_cloudwatch_log_group.firehose_errors.arn}:*",
        ]
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "firehose_errors" {
  #checkov:skip=CKV_AWS_158:Accepted — see infra/modules/app/api_gateway.tf access_logs group; same lab-scale tradeoff.
  name              = "/aws/firehose/botdef-delivery-errors-${var.environment}"
  retention_in_days = 365
}

# Terraform/API-created Firehose streams do not auto-create the log streams
# referenced by cloudwatch_logging_options below (unlike the console), so we
# create them explicitly here.
resource "aws_cloudwatch_log_stream" "firehose_errors_app_logs" {
  name           = "app-logs"
  log_group_name = aws_cloudwatch_log_group.firehose_errors.name
}

resource "aws_cloudwatch_log_stream" "firehose_errors_apigw_logs" {
  name           = "apigw-logs"
  log_group_name = aws_cloudwatch_log_group.firehose_errors.name
}

# Hive-style time partitioning via Firehose's built-in prefix expressions
# (delivery-time based) — no custom partitioning Lambda needed.
resource "aws_kinesis_firehose_delivery_stream" "app_logs" {
  #checkov:skip=CKV_AWS_240:Accepted — data lands SSE-S3-encrypted at rest in the destination bucket (see infra/modules/logging/s3.tf); no CMK for this lab's synthetic traffic logs, same tradeoff as the bucket itself.
  #checkov:skip=CKV_AWS_241:Accepted — see CKV_AWS_240 above; a customer-managed KMS key adds cost with no meaningful risk reduction here.
  name        = "botdef-app-logs-${var.environment}"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn            = aws_iam_role.firehose.arn
    bucket_arn          = aws_s3_bucket.logs.arn
    prefix              = "app/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    error_output_prefix = "app-errors/!{firehose:error-output-type}/"
    buffering_size      = 1
    buffering_interval  = 60

    # CloudWatch Logs subscription filters deliver a gzip-compressed JSON
    # envelope, not the raw log line. These are Firehose's own native
    # processors (not a custom transform Lambda) that decompress the
    # envelope and extract just the log message so Athena can parse it.
    processing_configuration {
      enabled = true
      processors {
        type = "Decompression"
        parameters {
          parameter_name  = "CompressionFormat"
          parameter_value = "GZIP"
        }
      }
      processors {
        type = "CloudWatchLogProcessing"
        parameters {
          parameter_name  = "DataMessageExtraction"
          parameter_value = "true"
        }
      }
    }

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose_errors.name
      log_stream_name = "app-logs"
    }
  }

  depends_on = [aws_cloudwatch_log_stream.firehose_errors_app_logs]
}

resource "aws_kinesis_firehose_delivery_stream" "apigw_logs" {
  #checkov:skip=CKV_AWS_240:Accepted — see aws_kinesis_firehose_delivery_stream.app_logs above; same tradeoff.
  #checkov:skip=CKV_AWS_241:Accepted — see aws_kinesis_firehose_delivery_stream.app_logs above; same tradeoff.
  name        = "botdef-apigw-logs-${var.environment}"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn            = aws_iam_role.firehose.arn
    bucket_arn          = aws_s3_bucket.logs.arn
    prefix              = "apigw/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    error_output_prefix = "apigw-errors/!{firehose:error-output-type}/"
    buffering_size      = 1
    buffering_interval  = 60

    # See aws_kinesis_firehose_delivery_stream.app_logs above — same native
    # Firehose decompression/extraction, no custom transform Lambda.
    processing_configuration {
      enabled = true
      processors {
        type = "Decompression"
        parameters {
          parameter_name  = "CompressionFormat"
          parameter_value = "GZIP"
        }
      }
      processors {
        type = "CloudWatchLogProcessing"
        parameters {
          parameter_name  = "DataMessageExtraction"
          parameter_value = "true"
        }
      }
    }

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose_errors.name
      log_stream_name = "apigw-logs"
    }
  }

  depends_on = [aws_cloudwatch_log_stream.firehose_errors_apigw_logs]
}
