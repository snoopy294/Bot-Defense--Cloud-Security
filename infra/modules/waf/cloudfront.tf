resource "aws_cloudfront_distribution" "app" {
  #checkov:skip=CKV_AWS_86:Accepted — CloudFront access logging would duplicate the WAF request logging this module ships (see logging.tf); a second S3 log destination adds no detection signal at lab scale. Revisit if CloudFront-only signal (e.g. cache behavior) becomes relevant.
  #trivy:ignore:AWS-0010 Accepted — same rationale as CKV_AWS_86 above (WAF request logging already covers this signal); trivy flags the same missing CloudFront access-logging config.
  #checkov:skip=CKV_AWS_305:Accepted — this distribution fronts a pure API proxy (API Gateway origin), not a static site; there is no index document to serve as a default root object.
  #checkov:skip=CKV_AWS_310:Accepted — single-origin lab setup; an origin failover group needs a second origin to fail over to, which adds cost/complexity with no benefit at this lab's scale. Revisit if multi-region origin redundancy becomes a requirement.
  #checkov:skip=CKV_AWS_374:Accepted — geo_restriction type "none" is intentional (see docs/superpowers/specs/2026-08-31-phase-3-waf-design.md Global Constraints); this lab has no geographic access policy to enforce.
  #checkov:skip=CKV_AWS_174:Accepted — false positive: minimum_protocol_version is explicitly set to TLSv1.2_2021 in the viewer_certificate block below, but checkov's CKV_AWS_174 does not evaluate that setting when cloudfront_default_certificate = true. No custom ACM certificate for this lab (see CKV2_AWS_42 skip below).
  #checkov:skip=CKV2_AWS_42:Accepted — no custom domain/ACM certificate for this lab; uses the CloudFront default certificate (*.cloudfront.net). See docs/phase-3-waf.md Known simplifications.
  #checkov:skip=CKV2_AWS_32:Accepted — no response headers policy attached; this distribution proxies a JSON API consumed by app clients/curl, not a browser-rendered page, so browser security response headers (CSP, HSTS, etc.) provide no meaningful protection here. Revisit if a browser-facing frontend is ever served from this distribution.
  #checkov:skip=CKV2_AWS_47:Accepted — false positive: the attached Web ACL (aws_wafv2_web_acl.app in web_acl.tf) already includes AWSManagedRulesKnownBadInputsRuleSet, which covers Log4j-class exploits; checkov's CKV2_AWS_47 does not detect that managed rule group as satisfying its AMR/Log4j requirement.
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
    # static assets) + AllViewerExceptHostHeader (forwards every
    # cookie/query string through, which the app's session-cookie authorizer
    # requires, but excludes the Host header — API Gateway's execute-api
    # endpoint routes on Host, so forwarding the viewer's CloudFront Host
    # value instead of API Gateway's own hostname makes every request 403).
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # Managed-CachingDisabled
    origin_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # Managed-AllViewerExceptHostHeader
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
