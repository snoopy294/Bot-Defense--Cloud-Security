# CLOUDFRONT-scope Web ACLs must be created in us-east-1 — the dev
# environment's pinned default region (infra/envs/dev/variables.tf), so no
# separate provider alias is needed here.
resource "aws_wafv2_web_acl" "app" {
  name        = "botdef-waf-${var.environment}"
  description = "Edge WAF for the drop app's CloudFront distribution."
  scope       = "CLOUDFRONT"

  default_action {
    allow {}
  }

  # Managed rule groups: pre-tuned by AWS, deployed straight to Block (see
  # docs/superpowers/specs/2026-08-31-phase-3-waf-design.md "Baseline managed
  # rule groups"). No AWSManagedRulesBotControlRuleSet — it bills a recurring
  # cash charge outside this lab's free-tier guarantee.
  rule {
    name     = "aws-common-rule-set"
    priority = 0

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "botdef-common-rule-set"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "aws-known-bad-inputs"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "botdef-known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "aws-ip-reputation"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesAmazonIpReputationList"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "botdef-ip-reputation"
      sampled_requests_enabled   = true
    }
  }

  # Custom rules: untuned, lab-specific, start in Count mode. Flip to Block
  # only after Phase 4 generates real adversary traffic to validate against
  # (see spec "Custom rules rollout").
  rule {
    name     = "checkout-rate-limit"
    priority = 3

    action {
      count {}
    }

    statement {
      rate_based_statement {
        limit              = 300
        aggregate_key_type = "IP"

        scope_down_statement {
          byte_match_statement {
            search_string         = "/checkout"
            positional_constraint = "STARTS_WITH"

            field_to_match {
              uri_path {}
            }

            text_transformation {
              priority = 0
              type     = "NONE"
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "botdef-checkout-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "missing-user-agent"
    priority = 4

    action {
      count {}
    }

    statement {
      size_constraint_statement {
        comparison_operator = "EQ"
        size                = 0

        field_to_match {
          single_header {
            name = "user-agent"
          }
        }

        text_transformation {
          priority = 0
          type     = "NONE"
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "botdef-missing-user-agent"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "botdef-waf-${var.environment}"
    sampled_requests_enabled   = true
  }
}
