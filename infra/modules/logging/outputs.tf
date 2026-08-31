output "logs_bucket_name" {
  description = "S3 bucket holding raw app + API Gateway logs."
  value       = aws_s3_bucket.logs.id
}

output "athena_workgroup" {
  description = "Athena workgroup name to run queries against (see docs/phase-2-observability.md for the example join query)."
  value       = aws_athena_workgroup.analytics.name
}

output "glue_database" {
  description = "Glue Catalog database name containing the app_logs and apigw_logs tables."
  value       = aws_glue_catalog_database.logs.name
}

output "logs_bucket_arn" {
  description = "ARN of the Phase 2 logs bucket, consumed by Phase 3's waf module to scope its Firehose delivery IAM policy."
  value       = aws_s3_bucket.logs.arn
}
