# Exomiser on AWS (module 6, step 6f): ranks each study subject's panel genes by how well their
# variants and HPO terms fit. Its data bundle is 33 GB zipped and about 100 GB unpacked, so it never
# goes to the laptop: a one-off task fetches a release into the genomics bucket
# (reference/exomiser/<release>/), and each run copies it to the task's own disk. The image builds
# on the gwas CodeBuild project (gwas.tf) with its source and Dockerfile overridden.
# scripts/run_exomiser.py does all of it.
#
# The image tag is a hash of the two files that make the image, computed the same way in
# run_exomiser.py.

locals {
  exomiser_files     = ["exomiser.Dockerfile", "exomiser_task.py"]
  exomiser_image_tag = substr(sha256(join("", [for f in local.exomiser_files : filesha256("${path.module}/../../../docker/${f}")])), 0, 12)
}

resource "aws_ecr_repository" "exomiser" {
  name                 = "${local.name}-exomiser"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "exomiser" {
  repository = aws_ecr_repository.exomiser.name
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

# The task: reads and writes the bucket's studies/ and reference/exomiser/ prefixes, nothing else.
# The fetch reaches the data host through the task's public IP, like every task here.
resource "aws_iam_role" "exomiser" {
  name               = "${local.name}-exomiser"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

data "aws_iam_policy_document" "exomiser" {
  statement {
    actions = ["s3:GetObject", "s3:PutObject"]
    resources = [
      "${aws_s3_bucket.gwas.arn}/studies/*",
      "${aws_s3_bucket.gwas.arn}/reference/exomiser/*",
    ]
  }
}

resource "aws_iam_role_policy" "exomiser" {
  role   = aws_iam_role.exomiser.id
  policy = data.aws_iam_policy_document.exomiser.json
}

# 16 GB is Exomiser's recommendation; 200 GiB of disk (Fargate's maximum) holds a zip and the
# unpacked bundle at once.
resource "aws_ecs_task_definition" "exomiser" {
  family                   = "${local.name}-exomiser"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "4096"
  memory                   = "16384"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.exomiser.arn

  ephemeral_storage {
    size_in_gib = 200
  }

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "exomiser"
    image     = "${aws_ecr_repository.exomiser.repository_url}:${local.exomiser_image_tag}"
    essential = true
    environment = [
      { name = "EXOMISER_BUCKET", value = aws_s3_bucket.gwas.id },
      { name = "EXOMISER_HEAP_GB", value = "12" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = local.region
        awslogs-stream-prefix = "exomiser"
      }
    }
  }])
}

# Fargate vCPU running at once, account-wide: the full Exomiser run is 50 tasks of 4 vCPU
# (scripts/run_exomiser.py --tasks 50), plus the app and the occasional bastion or monitor task.
# AWS approves the increase; destroying this resource does not lower the quota again.
resource "aws_servicequotas_service_quota" "fargate_vcpu" {
  service_code = "fargate"
  quota_code   = "L-3032A538"
  value        = 210
}
