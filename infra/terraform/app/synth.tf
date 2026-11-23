# Synthetic data releases on AWS (module 7): scripts/synthesize.py and scripts/evaluate_synth.py
# run as an on-demand task, reading OMOP from the lake through Redshift and writing releases and
# reports straight to Aurora, so nothing heavy runs on the laptop and nothing is copied after.
# The image holds the locked dependencies only; each run fetches one commit's code from the
# genomics bucket (docker/synth_task.py). It builds on the gwas CodeBuild project (gwas.tf) with
# its source and Dockerfile overridden. scripts/run_synth.py does all of it.
#
# The image tag is a hash of the files that make the image, computed the same way in
# run_synth.py: a dependency change makes a new tag, so plan and apply app/ after one.

locals {
  synth_files     = ["docker/synth.Dockerfile", "docker/synth_task.py", "pyproject.toml", "uv.lock"]
  synth_image_tag = substr(sha256(join("", [for f in local.synth_files : filesha256("${path.module}/../../../${f}")])), 0, 12)
}

resource "aws_ecr_repository" "synth" {
  name                 = "${local.name}-synth"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "synth" {
  repository = aws_ecr_repository.synth.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the 5 newest images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}

# The task's role: what the monitor may do (the Redshift Data API as itself, the catalog, Lake
# Formation, and Aurora as the app user), plus reading the uploaded source. Its own role, so its
# Redshift user (IAMR:ehr-rwe-eln-synth, infra/redshift/grants.sql) and lake grants are its own.
resource "aws_iam_role" "synth" {
  name               = "${local.name}-synth"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

resource "aws_iam_role_policy" "synth_lake" {
  role   = aws_iam_role.synth.id
  policy = data.aws_iam_policy_document.monitor.json
}

resource "aws_iam_role_policy" "synth_aurora" {
  role   = aws_iam_role.synth.id
  policy = data.aws_iam_policy_document.aurora_connect.json
}

data "aws_iam_policy_document" "synth_source" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.gwas.arn}/build/source-*"]
  }
}

resource "aws_iam_role_policy" "synth_source" {
  role   = aws_iam_role.synth.id
  policy = data.aws_iam_policy_document.synth_source.json
}

resource "aws_lakeformation_permissions" "synth_cdm_database" {
  principal   = aws_iam_role.synth.arn
  permissions = ["DESCRIBE"]

  database {
    catalog_id = local.omop_catalog_id
    name       = "cdm"
  }
}

resource "aws_lakeformation_permissions" "synth_cdm_tables" {
  principal   = aws_iam_role.synth.arn
  permissions = ["SELECT", "DESCRIBE"]

  table {
    catalog_id    = local.omop_catalog_id
    database_name = "cdm"
    wildcard      = true
  }
}

resource "aws_lakeformation_permissions" "synth_link" {
  principal   = aws_iam_role.synth.arn
  permissions = ["DESCRIBE"]

  database {
    name = "omop_cdm"
  }
}

# 4 vCPU and 30 GB, the most Fargate gives 4 vCPUs: AIM on the person summary ran out of 16 GB
# (its model grows each round; aim.py logs the peak per round).
resource "aws_ecs_task_definition" "synth" {
  family                   = "${local.name}-synth"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "4096"
  memory                   = "30720"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.synth.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "synth"
    image     = "${aws_ecr_repository.synth.repository_url}:${local.synth_image_tag}"
    essential = true
    environment = [
      for k, v in merge(local.database_env, local.lake_env, { SYNTH_BUCKET = aws_s3_bucket.gwas.id }) :
      { name = k, value = v }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = local.region
        awslogs-stream-prefix = "synth"
      }
    }
  }])
}
