resource "aws_apigatewayv2_api" "app" {
  name          = "botdef-app"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_authorizer" "session" {
  api_id                            = aws_apigatewayv2_api.app.id
  name                              = "botdef-session-authorizer"
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = aws_lambda_function.authorizer.invoke_arn
  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
  identity_sources                  = ["$request.header.Cookie"]
  authorizer_result_ttl_in_seconds  = 0
}

resource "aws_lambda_permission" "authorizer_invoke" {
  statement_id  = "AllowAPIGatewayInvokeAuthorizer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.authorizer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.app.execution_arn}/*/*"
}

locals {
  routes = {
    catalog_list   = { key = "GET /products", fn = aws_lambda_function.catalog }
    catalog_detail = { key = "GET /products/{id}", fn = aws_lambda_function.catalog }
    cart           = { key = "POST /cart", fn = aws_lambda_function.cart }
    checkout       = { key = "POST /checkout", fn = aws_lambda_function.checkout }
    admin_reset    = { key = "POST /admin/reset", fn = aws_lambda_function.admin }
  }
}

resource "aws_apigatewayv2_integration" "fn" {
  for_each               = local.routes
  api_id                 = aws_apigatewayv2_api.app.id
  integration_type       = "AWS_PROXY"
  integration_uri        = each.value.fn.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "fn" {
  for_each           = local.routes
  api_id             = aws_apigatewayv2_api.app.id
  route_key          = each.value.key
  target             = "integrations/${aws_apigatewayv2_integration.fn[each.key].id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.session.id
}

resource "aws_lambda_permission" "fn_invoke" {
  for_each      = local.routes
  statement_id  = "AllowAPIGatewayInvoke${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = each.value.fn.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.app.execution_arn}/*/*"
}

resource "aws_cloudwatch_log_group" "access_logs" {
  #checkov:skip=CKV_AWS_158:Accepted — default AWS-managed encryption on CloudWatch Logs is
  #sufficient for this lab's access logs; a customer-managed KMS key adds a new resource with
  #no meaningful risk reduction for non-sensitive access-log data. Revisit if PII enters logs.
  name              = "/botdef/app/access-logs"
  retention_in_days = 365 # CKV_AWS_338: retain at least 1 year
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.app.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access_logs.arn
    format = jsonencode({
      requestId       = "$context.requestId"
      ip              = "$context.identity.sourceIp"
      requestTime     = "$context.requestTime"
      httpMethod      = "$context.httpMethod"
      routeKey        = "$context.routeKey"
      status          = "$context.status"
      responseLatency = "$context.responseLatency"
    })
  }
}
