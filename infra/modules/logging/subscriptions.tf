data "aws_iam_policy_document" "cwl_to_firehose_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["logs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cwl_to_firehose" {
  name               = "botdef-cwl-to-firehose-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.cwl_to_firehose_trust.json
}

resource "aws_iam_role_policy" "cwl_to_firehose" {
  name = "botdef-cwl-to-firehose-policy-${var.environment}"
  role = aws_iam_role.cwl_to_firehose.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["firehose:PutRecord", "firehose:PutRecordBatch"]
      Resource = [
        aws_kinesis_firehose_delivery_stream.app_logs.arn,
        aws_kinesis_firehose_delivery_stream.apigw_logs.arn,
      ]
    }]
  })
}

# One subscription filter per app Lambda log group (AWS requires the filter
# to attach directly to each source log group), all feeding the same stream.
resource "aws_cloudwatch_log_subscription_filter" "app_logs" {
  for_each       = toset(var.app_log_group_names)
  name           = "botdef-app-logs-to-firehose-${var.environment}"
  log_group_name = each.value
  # Lambda platform lines (START/END/REPORT, tracebacks) aren't JSON and lack
  # a request_id field, so they're excluded here rather than shipped into the
  # app/ prefix where they'd break Athena's JSON parsing of app_logs.
  filter_pattern  = "{ $.request_id = * }"
  destination_arn = aws_kinesis_firehose_delivery_stream.app_logs.arn
  role_arn        = aws_iam_role.cwl_to_firehose.arn
}

resource "aws_cloudwatch_log_subscription_filter" "apigw_logs" {
  name           = "botdef-apigw-logs-to-firehose-${var.environment}"
  log_group_name = var.apigw_log_group_name
  # API Gateway access logs are always the structured format, so there's no
  # platform noise to exclude here (unlike the app_logs filter above).
  filter_pattern  = ""
  destination_arn = aws_kinesis_firehose_delivery_stream.apigw_logs.arn
  role_arn        = aws_iam_role.cwl_to_firehose.arn
}
