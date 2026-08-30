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
  name               = "botdef-firehose-delivery"
  assume_role_policy = data.aws_iam_policy_document.firehose_trust.json
}

resource "aws_iam_role_policy" "firehose" {
  name = "botdef-firehose-delivery-policy"
  role = aws_iam_role.firehose.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:PutObject",
        "s3:GetBucketLocation",
        "s3:ListBucket",
      ]
      Resource = [
        aws_s3_bucket.logs.arn,
        "${aws_s3_bucket.logs.arn}/*",
      ]
    }]
  })
}

resource "aws_cloudwatch_log_group" "firehose_errors" {
  #checkov:skip=CKV_AWS_158:Accepted — see infra/modules/app/api_gateway.tf access_logs group; same lab-scale tradeoff.
  name              = "/aws/firehose/botdef-delivery-errors"
  retention_in_days = 365
}

# Hive-style time partitioning via Firehose's built-in prefix expressions
# (delivery-time based) — no custom partitioning Lambda needed.
resource "aws_kinesis_firehose_delivery_stream" "app_logs" {
  #checkov:skip=CKV_AWS_240:Accepted — data lands SSE-S3-encrypted at rest in the destination bucket (see infra/modules/logging/s3.tf); no CMK for this lab's synthetic traffic logs, same tradeoff as the bucket itself.
  #checkov:skip=CKV_AWS_241:Accepted — see CKV_AWS_240 above; a customer-managed KMS key adds cost with no meaningful risk reduction here.
  name        = "botdef-app-logs"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn            = aws_iam_role.firehose.arn
    bucket_arn          = aws_s3_bucket.logs.arn
    prefix              = "app/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    error_output_prefix = "app-errors/!{firehose:error-output-type}/"
    buffering_size      = 1
    buffering_interval  = 60

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose_errors.name
      log_stream_name = "app-logs"
    }
  }
}

resource "aws_kinesis_firehose_delivery_stream" "apigw_logs" {
  #checkov:skip=CKV_AWS_240:Accepted — see aws_kinesis_firehose_delivery_stream.app_logs above; same tradeoff.
  #checkov:skip=CKV_AWS_241:Accepted — see aws_kinesis_firehose_delivery_stream.app_logs above; same tradeoff.
  name        = "botdef-apigw-logs"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn            = aws_iam_role.firehose.arn
    bucket_arn          = aws_s3_bucket.logs.arn
    prefix              = "apigw/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    error_output_prefix = "apigw-errors/!{firehose:error-output-type}/"
    buffering_size      = 1
    buffering_interval  = 60

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose_errors.name
      log_stream_name = "apigw-logs"
    }
  }
}
