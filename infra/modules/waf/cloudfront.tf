resource "aws_cloudfront_distribution" "app" {
  #checkov:skip=CKV_AWS_86:Accepted — CloudFront access logging would duplicate the WAF request logging this module ships (see logging.tf); a second S3 log destination adds no detection signal at lab scale. Revisit if CloudFront-only signal (e.g. cache behavior) becomes relevant.
  enabled         = true
  comment         = "botdef drop app edge (Phase 3)"
  is_ipv6_enabled = true
  # Cheapest price class (US/Canada/Europe edge locations only) — this is a
  # personal lab with no global audience to serve from every edge location.
  price_class = "PriceClass_100"

  origin {
    domain_name = var.api_domain_name
    origin_id   = "app-api-gateway"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "app-api-gateway"
    viewer_protocol_policy = "redirect-to-https"

    # AWS-managed policies instead of the legacy forwarded_values block:
    # CachingDisabled (this proxies a dynamic, session-authenticated API, not
    # static assets) + AllViewer (forwards every header/cookie/query string
    # through, which the app's session-cookie authorizer requires).
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # Managed-CachingDisabled
    origin_request_policy_id = "216adef6-5c7f-47e4-b989-5492eafa07d3" # Managed-AllViewer
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
    minimum_protocol_version       = "TLSv1.2_2021"
  }

  web_acl_id = aws_wafv2_web_acl.app.arn
}
