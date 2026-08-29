data "archive_file" "app" {
  type        = "zip"
  source_dir  = "${path.module}/../../../app"
  output_path = "${path.module}/build/app.zip"
  excludes    = ["tests", "requirements.txt", "pytest.ini", "README.md"]
}

locals {
  common_env = {
    SESSIONS_TABLE     = aws_dynamodb_table.sessions.name
    PRODUCTS_TABLE     = aws_dynamodb_table.products.name
    RESERVATIONS_TABLE = aws_dynamodb_table.reservations.name
    ORDERS_TABLE       = aws_dynamodb_table.orders.name
    ADMIN_SECRET_PARAM = var.admin_secret_param_name
  }
}

# Lambda scan-finding tradeoffs accepted for all 5 functions below (authorizer, catalog, cart,
# checkout, admin) in this lab environment — each is a small, unauthenticated-transport-internal
# function invoked only via API Gateway, so these do not raise the lab's risk meaningfully:
#   CKV_AWS_272 (code signing)   — AWS Signer setup is out of scope for this lab-scale app.
#   CKV_AWS_116 (DLQ)            — no async/event-source invocations; API Gateway callers get
#                                   the error synchronously, so there is nothing for a DLQ to catch.
#   CKV_AWS_173 (env var KMS)    — env vars hold table/param names only, no secrets; default
#                                   AWS-managed encryption at rest already applies.
#   CKV_AWS_117 (VPC)            — these are public API-facing functions; placing them in a VPC
#                                   would require a NAT Gateway, conflicting with the Phase 0
#                                   zero-spend budget guardrail, for no security benefit here.
#   CKV_AWS_50  (X-Ray tracing)  — deferred; structured JSON app logs (see common/logging.py)
#                                   already give per-request tracing for Phase 2's data plane.
resource "aws_lambda_function" "authorizer" {
  function_name                  = "botdef-fn-authorizer"
  role                           = aws_iam_role.authorizer.arn
  handler                        = "authorizer.handler.handler"
  runtime                        = "python3.12"
  timeout                        = 5
  reserved_concurrent_executions = 20
  filename                       = data.archive_file.app.output_path
  source_code_hash               = data.archive_file.app.output_base64sha256

  #checkov:skip=CKV_AWS_272:Accepted — see note above.
  #checkov:skip=CKV_AWS_116:Accepted — see note above.
  #checkov:skip=CKV_AWS_173:Accepted — see note above.
  #checkov:skip=CKV_AWS_117:Accepted — see note above.
  #checkov:skip=CKV_AWS_50:Accepted — see note above.
  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "catalog" {
  function_name                  = "botdef-fn-catalog"
  role                           = aws_iam_role.catalog.arn
  handler                        = "catalog.handler.handler"
  runtime                        = "python3.12"
  timeout                        = 5
  reserved_concurrent_executions = 20
  filename                       = data.archive_file.app.output_path
  source_code_hash               = data.archive_file.app.output_base64sha256

  #checkov:skip=CKV_AWS_272:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_116:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_173:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_117:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_50:Accepted — see note above aws_lambda_function.authorizer.
  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "cart" {
  function_name                  = "botdef-fn-cart"
  role                           = aws_iam_role.cart.arn
  handler                        = "cart.handler.handler"
  runtime                        = "python3.12"
  timeout                        = 5
  reserved_concurrent_executions = 20
  filename                       = data.archive_file.app.output_path
  source_code_hash               = data.archive_file.app.output_base64sha256

  #checkov:skip=CKV_AWS_272:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_116:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_173:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_117:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_50:Accepted — see note above aws_lambda_function.authorizer.
  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "checkout" {
  function_name                  = "botdef-fn-checkout"
  role                           = aws_iam_role.checkout.arn
  handler                        = "checkout.handler.handler"
  runtime                        = "python3.12"
  timeout                        = 5
  reserved_concurrent_executions = 20
  filename                       = data.archive_file.app.output_path
  source_code_hash               = data.archive_file.app.output_base64sha256

  #checkov:skip=CKV_AWS_272:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_116:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_173:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_117:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_50:Accepted — see note above aws_lambda_function.authorizer.
  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "admin" {
  function_name                  = "botdef-fn-admin"
  role                           = aws_iam_role.admin.arn
  handler                        = "admin.handler.handler"
  runtime                        = "python3.12"
  timeout                        = 5
  reserved_concurrent_executions = 20
  filename                       = data.archive_file.app.output_path
  source_code_hash               = data.archive_file.app.output_base64sha256

  #checkov:skip=CKV_AWS_272:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_116:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_173:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_117:Accepted — see note above aws_lambda_function.authorizer.
  #checkov:skip=CKV_AWS_50:Accepted — see note above aws_lambda_function.authorizer.
  environment {
    variables = local.common_env
  }
}
