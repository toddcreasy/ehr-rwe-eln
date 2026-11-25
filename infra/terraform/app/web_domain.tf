# The app at its own name, var.domain_name, through a CloudFront distribution in front of the
# Express Mode URL. Express Mode owns the load balancer and moves traffic between two target groups
# on every deploy, so a certificate or listener rule added there would be overwritten or left
# pointing at the old tasks. CloudFront sits outside it: no caching, every request passed on.
#
# The zone is made in project-template's ops/dns, delegated from the parent domain; this stack only
# adds records to it.
#
# Behind CloudFront the last X-Forwarded-For hop is a CloudFront server, not the visitor. CloudFront
# sends the visitor's address in CloudFront-Viewer-Address and a secret in X-Origin-Verify; the app
# trusts that address only when the secret matches (api/limits.py), so a direct call to the Express
# URL can't claim one.

data "aws_route53_zone" "web" {
  name = var.domain_name
}

resource "aws_acm_certificate" "web" {
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "web_validation" {
  for_each = {
    for o in aws_acm_certificate.web.domain_validation_options : o.domain_name => o
  }
  zone_id = data.aws_route53_zone.web.zone_id
  name    = each.value.resource_record_name
  type    = each.value.resource_record_type
  records = [each.value.resource_record_value]
  ttl     = 300
}

resource "aws_acm_certificate_validation" "web" {
  certificate_arn         = aws_acm_certificate.web.arn
  validation_record_fqdns = [for r in aws_route53_record.web_validation : r.fqdn]
}

# Proves a request came through CloudFront. ECS reads it out of Secrets Manager into
# ORIGIN_VERIFY_SECRET, the same way it reads the database secret.
resource "random_password" "origin_verify" {
  length  = 48
  special = false
}

# trivy:ignore:AVD-AWS-0098 The default AWS key is enough for a header value that only proves the request came through CloudFront.
resource "aws_secretsmanager_secret" "origin_verify" {
  name                    = "${local.name}/origin-verify"
  description             = "X-Origin-Verify header value CloudFront sends to the app."
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "origin_verify" {
  secret_id     = aws_secretsmanager_secret.origin_verify.id
  secret_string = random_password.origin_verify.result
}

data "aws_iam_policy_document" "read_origin_verify" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.origin_verify.arn]
  }
}

resource "aws_iam_role_policy" "execution_origin_verify" {
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.read_origin_verify.json
}

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

# Every viewer header but Host (the load balancer routes on the Express URL's own name), all
# cookies and query strings, and CloudFront's viewer location headers, CloudFront-Viewer-Address
# among them.
data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

locals {
  express_host = trimprefix(aws_ecs_express_gateway_service.app.ingress_paths[0].endpoint, "https://")
}

# trivy:ignore:AVD-AWS-0010 No access logs: the app logs each page view with the visitor's address already.
# trivy:ignore:AVD-AWS-0011 No WAF: about $6 a month before requests, against a $100 budget; /api/agent is bounded in the app.
resource "aws_cloudfront_distribution" "web" {
  enabled         = true
  comment         = "${local.name} web app"
  aliases         = [var.domain_name]
  is_ipv6_enabled = true
  http_version    = "http2and3"
  # North America and Europe edges only: the cheapest class
  price_class = "PriceClass_100"

  origin {
    origin_id   = "express"
    domain_name = local.express_host

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      # The longest /api/agent call in the 30 days to 2026-11-25 took 27 s, near the 30 s default.
      # 60 s is the most CloudFront allows without a quota increase, and the load balancer's idle
      # timeout is 60 s too.
      origin_read_timeout = 60
    }

    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_verify.result
    }
  }

  default_cache_behavior {
    target_origin_id         = "express"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.web.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

resource "aws_route53_record" "web" {
  for_each = toset(["A", "AAAA"])
  zone_id  = data.aws_route53_zone.web.zone_id
  name     = var.domain_name
  type     = each.key

  alias {
    name                   = aws_cloudfront_distribution.web.domain_name
    zone_id                = aws_cloudfront_distribution.web.hosted_zone_id
    evaluate_target_health = false
  }
}
