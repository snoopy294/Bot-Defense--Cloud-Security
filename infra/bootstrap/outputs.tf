# After `terraform apply`, paste these values into infra/envs/dev/backend.hcl.

output "state_bucket" {
  description = "Name of the S3 bucket holding remote Terraform state."
  value       = aws_s3_bucket.state.id
}

output "state_kms_key_arn" {
  description = "Pass as state_kms_key_arn in dev Terraform and TF_STATE_KMS_KEY_ARN in GitHub variables."
  value       = aws_kms_key.state.arn
}

output "lock_table" {
  description = "Name of the DynamoDB table used for state locking."
  value       = aws_dynamodb_table.lock.name
}

output "region" {
  description = "Region the backend lives in."
  value       = var.region
}

output "backend_hcl" {
  description = "Copy-paste block for infra/envs/dev/backend.hcl."
  value       = <<-EOT
    bucket         = "${aws_s3_bucket.state.id}"
    key            = "envs/dev/terraform.tfstate"
    region         = "${var.region}"
    dynamodb_table = "${aws_dynamodb_table.lock.name}"
    encrypt        = true
  EOT
}
