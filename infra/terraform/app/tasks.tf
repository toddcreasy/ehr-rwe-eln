# Task definitions that run on demand or on a schedule, never as standing services.

# The bastion: started only when someone needs Aurora from a laptop (migrations, data copies),
# with ECS Exec on, then tunnelled through with Systems Manager. It stops itself after an hour.
resource "aws_ecs_task_definition" "bastion" {
  family                   = "${local.name}-bastion"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.bastion.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "bastion"
    image     = local.image
    command   = ["sleep", "3600"]
    essential = true
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = local.region
        awslogs-stream-prefix = "bastion"
      }
    }
  }])
}

# The daily privacy check on every synthetic release (python -m ehr_rwe_eln.synth.monitor --once),
# reading its sources from the lake through Redshift and writing to Aurora.
resource "aws_ecs_task_definition" "monitor" {
  family                   = "${local.name}-monitor"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.monitor.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "monitor"
    image     = local.image
    command   = ["python", "-m", "ehr_rwe_eln.synth.monitor", "--once"]
    essential = true
    environment = [
      for k, v in merge(local.database_env, local.lake_env, { LOG_LEVEL = "INFO" }) :
      { name = k, value = v }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = local.region
        awslogs-stream-prefix = "monitor"
      }
    }
  }])
}

# EventBridge Scheduler starts the monitor once a day. It needs a role that may run the task and
# hand it its two roles.
data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["ecs:RunTask"]
    resources = [aws_ecs_task_definition.monitor.arn_without_revision, "${aws_ecs_task_definition.monitor.arn_without_revision}:*"]
  }
  statement {
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.execution.arn, aws_iam_role.monitor.arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "monitor" {
  name                         = "${local.name}-monitor"
  schedule_expression          = "cron(0 11 * * ? *)"
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.monitor.arn_without_revision
      launch_type         = "FARGATE"

      network_configuration {
        subnets          = local.foundation.public_subnet_ids
        security_groups  = [local.foundation.app_security_group_id]
        assign_public_ip = true
      }
    }

    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}
