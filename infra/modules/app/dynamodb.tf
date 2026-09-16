resource "aws_dynamodb_table" "sessions" {
  name         = "botdef-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"

  attribute {
    name = "session_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  # checkov:skip=CKV_AWS_119:Accepted — DynamoDB's default AWS-owned encryption at rest is used
  # for all 4 app tables in this lab; a customer-managed KMS key adds cost/complexity with no
  # meaningful risk reduction for synthetic drop-app data. Revisit if real PII is ever stored.
  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }
}

# catalog_pk is a constant ("PRODUCT") on every item so GET /products can
# Query the catalog-index GSI instead of Scan — catalog-fn's IAM policy
# grants Query but not Scan (see spec Security section + plan Task 3).
resource "aws_dynamodb_table" "products" {
  name         = "botdef-products"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "product_id"

  attribute {
    name = "product_id"
    type = "S"
  }

  attribute {
    name = "catalog_pk"
    type = "S"
  }

  global_secondary_index {
    name            = "catalog-index"
    hash_key        = "catalog_pk"
    projection_type = "ALL"
  }

  # checkov:skip=CKV_AWS_119:Accepted — see sessions table above; same lab-scale tradeoff.
  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }
}

resource "aws_dynamodb_table" "reservations" {
  name         = "botdef-reservations"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "reservation_id"

  attribute {
    name = "reservation_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  # checkov:skip=CKV_AWS_119:Accepted — see sessions table above; same lab-scale tradeoff.
  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }
}

resource "aws_dynamodb_table" "orders" {
  name         = "botdef-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "order_id"

  attribute {
    name = "order_id"
    type = "S"
  }

  # checkov:skip=CKV_AWS_119:Accepted — see sessions table above; same lab-scale tradeoff.
  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }
}
