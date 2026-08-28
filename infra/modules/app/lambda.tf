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

resource "aws_lambda_function" "authorizer" {
  function_name    = "botdef-fn-authorizer"
  role             = aws_iam_role.authorizer.arn
  handler          = "authorizer.handler.handler"
  runtime          = "python3.12"
  timeout          = 5
  filename         = data.archive_file.app.output_path
  source_code_hash = data.archive_file.app.output_base64sha256

  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "catalog" {
  function_name    = "botdef-fn-catalog"
  role             = aws_iam_role.catalog.arn
  handler          = "catalog.handler.handler"
  runtime          = "python3.12"
  timeout          = 5
  filename         = data.archive_file.app.output_path
  source_code_hash = data.archive_file.app.output_base64sha256

  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "cart" {
  function_name    = "botdef-fn-cart"
  role             = aws_iam_role.cart.arn
  handler          = "cart.handler.handler"
  runtime          = "python3.12"
  timeout          = 5
  filename         = data.archive_file.app.output_path
  source_code_hash = data.archive_file.app.output_base64sha256

  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "checkout" {
  function_name    = "botdef-fn-checkout"
  role             = aws_iam_role.checkout.arn
  handler          = "checkout.handler.handler"
  runtime          = "python3.12"
  timeout          = 5
  filename         = data.archive_file.app.output_path
  source_code_hash = data.archive_file.app.output_base64sha256

  environment {
    variables = local.common_env
  }
}

resource "aws_lambda_function" "admin" {
  function_name    = "botdef-fn-admin"
  role             = aws_iam_role.admin.arn
  handler          = "admin.handler.handler"
  runtime          = "python3.12"
  timeout          = 5
  filename         = data.archive_file.app.output_path
  source_code_hash = data.archive_file.app.output_base64sha256

  environment {
    variables = local.common_env
  }
}
