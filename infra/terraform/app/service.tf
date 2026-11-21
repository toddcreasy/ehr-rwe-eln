# The public web app: one ECS Express Mode service. Express Mode builds the internet-facing load
# balancer, an HTTPS certificate on an AWS-provided URL, and autoscaling; given public subnets it
# also gives the task a public IP, which is how it reaches ECR and AWS APIs without a NAT gateway.
# No sign-in: PUBLIC_DEMO blocks curator decisions, and /api/agent is bounded by the daily token
# and per-address limits (src/ehr_rwe_eln/api/limits.py).

resource "aws_ecs_cluster" "main" {
  name = local.name
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name}"
  retention_in_days = 30
}

resource "aws_ecs_express_gateway_service" "app" {
  service_name            = local.name
  cluster                 = aws_ecs_cluster.main.name
  execution_role_arn      = aws_iam_role.execution.arn
  infrastructure_role_arn = aws_iam_role.infrastructure.arn
  task_role_arn           = aws_iam_role.app.arn
  cpu                     = "512"
  memory                  = "1024"
  cpu_architecture        = "ARM64"
  health_check_path       = "/api/health"

  network_configuration = [{
    subnets         = local.foundation.public_subnet_ids
    security_groups = [local.foundation.app_security_group_id]
  }]

  # One task, always: a cost ceiling, and the per-address limit is held in that task's memory.
  scaling_target = [{
    min_task_count            = 1
    max_task_count            = 1
    auto_scaling_metric       = "AVERAGE_CPU"
    auto_scaling_target_value = 70
  }]

  primary_container {
    image          = local.image
    container_port = 8000

    aws_logs_configuration = [{
      log_group         = aws_cloudwatch_log_group.app.name
      log_stream_prefix = "app"
    }]

    dynamic "environment" {
      for_each = merge(local.database_env, {
        PUBLIC_DEMO       = "true"
        LOG_LEVEL         = "INFO"
        DAILY_TOKEN_LIMIT = tostring(var.daily_token_limit)
        AGENT_ENABLED     = tostring(var.agent_enabled)
        MODEL             = var.model
        AWS_REGION        = local.region
      })
      content {
        name  = environment.key
        value = environment.value
      }
    }

    secret {
      name       = "DB_PASSWORD"
      value_from = local.db_credential_ref
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.infrastructure,
    aws_iam_role_policy_attachment.execution,
    aws_iam_role_policy.execution_db_secret,
    aws_iam_role_policy.app_bedrock,
  ]
}
