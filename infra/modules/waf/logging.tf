data "aws_iam_policy_document" "waf_firehose_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "waf_firehose" {
  name               = "botdef-waf-firehose-delivery-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.waf_firehose_trust.json
}

resource "aws_iam_role_policy" "waf_firehose" {
  name = "botdef-waf-firehose-delivery-policy-${var.environment}"
  role = aws_iam_role.waf_firehose.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Bucket-level actions have no meaningful per-prefix scoping in IAM
        # (GetBucketLocation/ListBucket/ListBucketMultipartUploads target the
        # bucket itself, not an object) — accepted since they're read-only /
        # metadata actions.
        Effect = "Allow"
        Action = [
          "s3:GetBucketLocation",
          "s3:ListBucket",
          "s3:ListBucketMultipartUploads",
        ]
        Resource = [
          var.logs_bucket_arn,
        ]
      },
      {
        # Object-level actions are scoped to this module's own Firehose data
        # and error-output prefixes only ("waf/*", "waf-errors/*") — not the
        # whole logs bucket, which also holds Phase 1/2's app/ and apigw/
        # prefixes.
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:AbortMultipartUpload",
          "s3:GetObject",
        ]
        Resource = [
          "${var.logs_bucket_arn}/waf/*",
          "${var.logs_bucket_arn}/waf-errors/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:PutLogEvents",
          "logs:CreateLogStream",
        ]
        Resource = [
          aws_cloudwatch_log_group.waf_firehose_errors.arn,
          "${aws_cloudwatch_log_group.waf_firehose_errors.arn}:*",
        ]
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "waf_firehose_errors" {
  #checkov:skip=CKV_AWS_158:Accepted — see infra/modules/logging/firehose.tf aws_cloudwatch_log_group.firehose_errors; same lab-scale tradeoff (default AWS-managed encryption, no CMK).
  name              = "/aws/firehose/botdef-waf-delivery-errors-${var.environment}"
  retention_in_days = 365
}

resource "aws_cloudwatch_log_stream" "waf_firehose_errors" {
  name           = "waf-logs"
  log_group_name = aws_cloudwatch_log_group.waf_firehose_errors.name
}

# AWS requires a Kinesis Data Firehose used as a *direct* WAF logging
# destination to be named with the literal prefix "aws-waf-logs-" — this is
# an AWS-enforced constraint, not a deviation from the botdef- convention
# used everywhere else in this project.
resource "aws_kinesis_firehose_delivery_stream" "waf_logs" {
  #checkov:skip=CKV_AWS_240:Accepted — see infra/modules/logging/firehose.tf; data lands SSE-S3-encrypted at rest in the destination bucket, no CMK for this lab's synthetic traffic logs.
  #checkov:skip=CKV_AWS_241:Accepted — see CKV_AWS_240 above.
  name        = "aws-waf-logs-botdef-waf-${var.environment}"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn            = aws_iam_role.waf_firehose.arn
    bucket_arn          = var.logs_bucket_arn
    prefix              = "waf/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    error_output_prefix = "waf-errors/!{firehose:error-output-type}/"
    buffering_size      = 1
    buffering_interval  = 60

    # WAF's native Firehose logging integration delivers plain JSON directly
    # — unlike Phase 2's CloudWatch Logs subscription filter path (see
    # infra/modules/logging/firehose.tf), there is no gzip envelope to
    # decompress, so no processing_configuration block is needed here.
    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.waf_firehose_errors.name
      log_stream_name = "waf-logs"
    }
  }

  depends_on = [aws_cloudwatch_log_stream.waf_firehose_errors]
}

resource "aws_wafv2_web_acl_logging_configuration" "app" {
  resource_arn            = aws_wafv2_web_acl.app.arn
  log_destination_configs = [aws_kinesis_firehose_delivery_stream.waf_logs.arn]

  # The app authenticates via a session cookie (identity_sources =
  # ["$request.header.Cookie"] in infra/modules/app/api_gateway.tf) — without
  # redaction, every WAF log entry would write the live session cookie value
  # to S3. Redact Cookie and Authorization headers at the source.
  redacted_fields {
    single_header {
      name = "cookie"
    }
  }
  redacted_fields {
    single_header {
      name = "authorization"
    }
  }
}

# New table in the *existing* Phase 2 Glue database (module.logging.glue_database) —
# infra/modules/logging/ itself is not modified. Column names are lowercase
# because org.openx.data.jsonserde.JsonSerDe matches JSON keys
# case-insensitively by default, so lowercase Glue columns still match WAF's
# camelCase log field names (e.g. "httpRequest").
resource "aws_glue_catalog_table" "waf_logs" {
  name          = "waf_logs"
  database_name = var.glue_database
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    classification = "json"
  }

  partition_keys {
    name = "year"
    type = "string"
  }
  partition_keys {
    name = "month"
    type = "string"
  }
  partition_keys {
    name = "day"
    type = "string"
  }
  partition_keys {
    name = "hour"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${var.logs_bucket_name}/waf/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "timestamp"
      type = "bigint"
    }
    columns {
      name = "action"
      type = "string"
    }
    columns {
      name = "terminatingruleid"
      type = "string"
    }
    columns {
      name = "terminatingruletype"
      type = "string"
    }
    columns {
      name = "httpsourcename"
      type = "string"
    }
    columns {
      name = "httprequest"
      type = "struct<clientip:string,country:string,uri:string,httpmethod:string,httpversion:string,requestid:string>"
    }
    # A Count-mode rule match (checkout-rate-limit, missing-user-agent) never
    # populates terminatingRuleId/action — it only appears in
    # nonTerminatingMatchingRules. Without this column JsonSerDe silently
    # drops it and Count-mode hits are invisible in Athena.
    columns {
      name = "nonterminatingmatchingrules"
      type = "array<struct<ruleid:string,action:string>>"
    }
    columns {
      name = "webaclid"
      type = "string"
    }
    columns {
      name = "labels"
      type = "array<struct<name:string>>"
    }
  }
}
