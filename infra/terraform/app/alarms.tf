# The daily token alarm, as in glia-nav: Cost Explorer lags a day, so this is the fast warning.
# Each /api/agent call logs an "agent run" line with total_tokens; a metric filter turns that into
# a CloudWatch metric, and the alarm emails when a UTC day's total passes 80% of the daily limit.
# (The app's limit counts US Eastern days, so the two windows are offset by a few hours.)

# trivy:ignore:AWS-0095 SNS encryption needs a customer managed key ($1/month) that CloudWatch may use; the topic carries only alarm text.
resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

# AWS emails a confirmation link; the alarm reaches you only after you click it.
resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_log_metric_filter" "agent_tokens" {
  name           = "${local.name}-agent-tokens"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.message = \"agent run\" }"

  metric_transformation {
    name          = "AgentTokens"
    namespace     = local.name
    value         = "$.total_tokens"
    default_value = 0
    unit          = "Count"
  }
}

resource "aws_cloudwatch_metric_alarm" "agent_tokens_daily" {
  alarm_name          = "${local.name}-agent-tokens-daily"
  alarm_description   = "/api/agent used more than 80% of its daily token limit in a day"
  namespace           = local.name
  metric_name         = "AgentTokens"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = var.daily_token_limit * 0.8
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
