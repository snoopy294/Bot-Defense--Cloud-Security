resource "aws_glue_catalog_database" "logs" {
  name = "botdef_logs_${var.environment}"
}

resource "aws_glue_catalog_table" "apigw_logs" {
  name          = "apigw_logs"
  database_name = aws_glue_catalog_database.logs.name
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
    location      = "s3://${aws_s3_bucket.logs.id}/apigw/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "request_id"
      type = "string"
    }
    columns {
      name = "ts"
      type = "bigint"
    }
    columns {
      name = "source_ip"
      type = "string"
    }
    columns {
      name = "user_agent"
      type = "string"
    }
    columns {
      name = "route"
      type = "string"
    }
    columns {
      name = "method"
      type = "string"
    }
    columns {
      name = "status"
      type = "string"
    }
    columns {
      name = "latency_ms"
      type = "string"
    }
    columns {
      name = "integration_error"
      type = "string"
    }
  }
}

resource "aws_glue_catalog_table" "app_logs" {
  name          = "app_logs"
  database_name = aws_glue_catalog_database.logs.name
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
    location      = "s3://${aws_s3_bucket.logs.id}/app/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name = "ts"
      type = "double"
    }
    columns {
      name = "request_id"
      type = "string"
    }
    columns {
      name = "session_id"
      type = "string"
    }
    columns {
      name = "route"
      type = "string"
    }
    columns {
      name = "method"
      type = "string"
    }
    columns {
      name = "status"
      type = "int"
    }
    columns {
      name = "latency_ms"
      type = "double"
    }
    columns {
      name = "product_id"
      type = "string"
    }
    columns {
      name = "outcome"
      type = "string"
    }
  }
}

resource "aws_athena_workgroup" "analytics" {
  name = "botdef-analytics"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = false

    result_configuration {
      output_location = "s3://${aws_s3_bucket.logs.id}/athena-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
