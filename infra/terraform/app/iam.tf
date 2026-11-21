# Who may do what. Containers get AWS permissions from roles, never from keys.
# - execution role: ECS itself, to pull the image, write logs, and read the database password
#   (which Express Mode still injects; see service.tf).
# - infrastructure role: ECS Express Mode, to build the load balancer, certificate, and scaling.
# - app task role: the web app's own AWS calls: Claude on Bedrock for /api/agent.
# - monitor task role: the daily privacy check, which reads OMOP from the lake through Redshift.
# - bastion task role: the on-demand tunnel to Aurora (ECS Exec over Systems Manager).

# Only ECS tasks in this account may take these roles (the confused-deputy guard).
data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:ecs:${local.region}:${local.account_id}:*"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "read_db_secret" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [local.foundation.aurora_master_secret_arn]
  }
}

resource "aws_iam_role_policy" "execution_db_secret" {
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.read_db_secret.json
}

# Sign in to Aurora as the app user with an IAM token.
data "aws_iam_policy_document" "aurora_connect" {
  statement {
    actions   = ["rds-db:connect"]
    resources = [local.aurora_app_user_arn]
  }
}

data "aws_iam_policy_document" "ecs_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "infrastructure" {
  name               = "${local.name}-express-infrastructure"
  assume_role_policy = data.aws_iam_policy_document.ecs_trust.json
}

resource "aws_iam_role_policy_attachment" "infrastructure" {
  role       = aws_iam_role.infrastructure.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
}

resource "aws_iam_role" "app" {
  name               = "${local.name}-app"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

# MODEL is a cross-region inference profile: a call goes to the profile, which routes it to the
# model in one of its regions, so both the profile and each region's model must be allowed.
# Every model call must go through the agent's guardrail at its pinned version: a call without
# it is denied, so a code change can't quietly drop it.
locals {
  guardrail_pinned = "${aws_bedrock_guardrail.agent.guardrail_arn}:${aws_bedrock_guardrail_version.agent.version}"
}

data "aws_iam_policy_document" "app_bedrock" {
  statement {
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = concat(
      ["arn:aws:bedrock:${local.region}:${local.account_id}:inference-profile/${var.model}"],
      [for r in var.model_regions : "arn:aws:bedrock:${r}::foundation-model/${trimprefix(var.model, "us.")}"],
    )
    condition {
      test     = "StringEquals"
      variable = "bedrock:GuardrailIdentifier"
      values   = [local.guardrail_pinned]
    }
  }
  # Checking a prompt before the model (guardrail_check), and the guardrail on each model call.
  statement {
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.agent.guardrail_arn]
  }
}

resource "aws_iam_role_policy" "app_bedrock" {
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app_bedrock.json
}

resource "aws_iam_role_policy" "app_aurora" {
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.aurora_connect.json
}

resource "aws_iam_role" "monitor" {
  name               = "${local.name}-monitor"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

# The Redshift Data API as the monitor's own IAM identity (Redshift user IAMR:ehr-rwe-eln-monitor),
# and the catalog and Lake Formation calls that reading lake tables makes.
data "aws_iam_policy_document" "monitor" {
  statement {
    actions   = ["redshift-data:ExecuteStatement", "redshift-serverless:GetCredentials"]
    resources = [local.foundation.redshift_workgroup_arn]
  }
  # These two take a statement ID, not a workgroup, so they can't be scoped by resource; the
  # condition limits them to statements this role ran.
  statement {
    actions   = ["redshift-data:DescribeStatement", "redshift-data:GetStatementResult"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "redshift-data:statement-owner-iam-userid"
      values   = ["$${aws:userid}"]
    }
  }
  statement {
    actions = [
      "glue:GetCatalog",
      "glue:GetCatalogs",
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
    ]
    resources = local.foundation.lake_glue_arns
  }
  # GetDataAccess has no resource-level permissions; Lake Formation grants decide what it returns.
  statement {
    actions   = ["lakeformation:GetDataAccess"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "monitor" {
  role   = aws_iam_role.monitor.id
  policy = data.aws_iam_policy_document.monitor.json
}

resource "aws_iam_role_policy" "monitor_aurora" {
  role   = aws_iam_role.monitor.id
  policy = data.aws_iam_policy_document.aurora_connect.json
}

resource "aws_iam_role" "bastion" {
  name               = "${local.name}-bastion"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

# ECS Exec: the Systems Manager channels a port-forwarding session runs over.
data "aws_iam_policy_document" "bastion" {
  statement {
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "bastion" {
  role   = aws_iam_role.bastion.id
  policy = data.aws_iam_policy_document.bastion.json
}
