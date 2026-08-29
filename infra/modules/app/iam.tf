data "aws_iam_policy_document" "lambda_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

locals {
  # Resource="*" here mirrors AWS's own managed AWSLambdaBasicExecutionRole: the log group name
  # is derived from the function name at invoke time and doesn't exist yet at policy-authoring
  # time, so it cannot be scoped to a specific ARN up front. This is what triggers CKV_AWS_355 /
  # CKV_AWS_290 on every role_policy below — accepted, logging-only, not a data-plane action.
  logs_statement = {
    Effect   = "Allow"
    Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    Resource = "*"
  }
}

# --- authorizer: PutItem/UpdateItem/GetItem on Sessions only ---
resource "aws_iam_role" "authorizer" {
  name               = "botdef-fn-authorizer"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy" "authorizer" {
  name = "botdef-fn-authorizer-policy"
  role = aws_iam_role.authorizer.id
  #checkov:skip=CKV_AWS_355:Accepted — wildcard is only on the shared logs_statement (see locals above), not the DynamoDB actions.
  #checkov:skip=CKV_AWS_290:Accepted — see note above; log-creation write access is unconstrained by design, matching AWS's managed basic-execution role.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.sessions.arn
      },
      local.logs_statement,
    ]
  })
}

# --- catalog: GetItem/Query on Products (+ its GSI) only ---
resource "aws_iam_role" "catalog" {
  name               = "botdef-fn-catalog"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy" "catalog" {
  name = "botdef-fn-catalog-policy"
  role = aws_iam_role.catalog.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["dynamodb:GetItem", "dynamodb:Query"]
        Resource = [
          aws_dynamodb_table.products.arn,
          "${aws_dynamodb_table.products.arn}/index/*",
        ]
      },
      local.logs_statement,
    ]
  })
}

# --- cart: GetItem/UpdateItem on Products + PutItem on Reservations ---
resource "aws_iam_role" "cart" {
  name               = "botdef-fn-cart"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy" "cart" {
  name = "botdef-fn-cart-policy"
  role = aws_iam_role.cart.id
  #checkov:skip=CKV_AWS_355:Accepted — see note on aws_iam_role_policy.authorizer above.
  #checkov:skip=CKV_AWS_290:Accepted — see note on aws_iam_role_policy.authorizer above.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.products.arn
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.reservations.arn
      },
      local.logs_statement,
    ]
  })
}

# --- checkout: GetItem/UpdateItem on Reservations + PutItem on Orders ---
resource "aws_iam_role" "checkout" {
  name               = "botdef-fn-checkout"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy" "checkout" {
  name = "botdef-fn-checkout-policy"
  role = aws_iam_role.checkout.id
  #checkov:skip=CKV_AWS_355:Accepted — see note on aws_iam_role_policy.authorizer above.
  #checkov:skip=CKV_AWS_290:Accepted — see note on aws_iam_role_policy.authorizer above.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.reservations.arn
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.orders.arn
      },
      local.logs_statement,
    ]
  })
}

# --- admin: write Products, delete/scan Reservations+Orders, read the admin secret ---
resource "aws_iam_role" "admin" {
  name               = "botdef-fn-admin"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

resource "aws_iam_role_policy" "admin" {
  name = "botdef-fn-admin-policy"
  role = aws_iam_role.admin.id
  #checkov:skip=CKV_AWS_355:Accepted — see note on aws_iam_role_policy.authorizer above.
  #checkov:skip=CKV_AWS_290:Accepted — see note on aws_iam_role_policy.authorizer above.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem"]
        Resource = aws_dynamodb_table.products.arn
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:Scan", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem"]
        Resource = [aws_dynamodb_table.reservations.arn, aws_dynamodb_table.orders.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = "arn:aws:ssm:*:*:parameter${var.admin_secret_param_name}"
      },
      local.logs_statement,
    ]
  })
}
