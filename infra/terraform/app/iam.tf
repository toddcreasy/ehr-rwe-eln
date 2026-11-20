# Who may do what. Containers get AWS permissions from roles, never from keys.
# - execution role: ECS itself, to pull the image, write logs, and read the database password.
# - infrastructure role: ECS Express Mode, to build the load balancer, certificate, and scaling.
# - app task role: the web app's own AWS calls (none yet; Bedrock arrives in step 5).
# - monitor task role: the daily privacy check, which reads OMOP from the lake through Redshift.
# - bastion task role: the on-demand tunnel to Aurora (ECS Exec over Systems Manager).

data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
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

resource "aws_iam_role" "monitor" {
  name               = "${local.name}-monitor"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

# The Redshift Data API as the monitor's own IAM identity (Redshift user IAMR:ehr-rwe-eln-monitor),
# and the catalog and Lake Formation calls that reading lake tables makes.
data "aws_iam_policy_document" "monitor" {
  statement {
    actions = [
      "redshift-data:ExecuteStatement",
      "redshift-data:DescribeStatement",
      "redshift-data:GetStatementResult",
    ]
    resources = ["*"]
  }
  statement {
    actions   = ["redshift-serverless:GetCredentials"]
    resources = ["arn:aws:redshift-serverless:${local.region}:${local.account_id}:workgroup/*"]
  }
  statement {
    actions = [
      "glue:GetCatalog",
      "glue:GetCatalogs",
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "lakeformation:GetDataAccess",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "monitor" {
  role   = aws_iam_role.monitor.id
  policy = data.aws_iam_policy_document.monitor.json
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
