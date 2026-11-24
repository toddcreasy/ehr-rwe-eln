# LIRICAL on AWS (module 6): ranks diseases by how well each study subject's HPO terms fit,
# phenotype only. Its data is in the image (docker/lirical.Dockerfile), so there is no fetch
# step. The image builds on the gwas CodeBuild project (gwas.tf) with its source and Dockerfile
# overridden. scripts/run_lirical.py does all of it.
#
# The image tag is a hash of the two files that make the image, computed the same way in
# run_lirical.py.

locals {
  lirical_files     = ["lirical.Dockerfile", "lirical_task.py"]
  lirical_image_tag = substr(sha256(join("", [for f in local.lirical_files : filesha256("${path.module}/../../../docker/${f}")])), 0, 12)
}

resource "aws_ecr_repository" "lirical" {
  name                 = "${local.name}-lirical"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "lirical" {
  repository = aws_ecr_repository.lirical.name
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

# The task: reads and writes the bucket's studies/ prefix, nothing else.
resource "aws_iam_role" "lirical" {
  name               = "${local.name}-lirical"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

data "aws_iam_policy_document" "lirical" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.gwas.arn}/studies/*"]
  }
}

resource "aws_iam_role_policy" "lirical" {
  role   = aws_iam_role.lirical.id
  policy = data.aws_iam_policy_document.lirical.json
}

# LIRICAL runs one Java process per person; four at a time with a 3 GB heap each fill 4 vCPUs
# and leave room in 16 GB.
resource "aws_ecs_task_definition" "lirical" {
  family                   = "${local.name}-lirical"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "4096"
  memory                   = "16384"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.lirical.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "lirical"
    image     = "${aws_ecr_repository.lirical.repository_url}:${local.lirical_image_tag}"
    essential = true
    environment = [
      { name = "LIRICAL_BUCKET", value = aws_s3_bucket.gwas.id },
      { name = "LIRICAL_WORKERS", value = "4" },
      { name = "LIRICAL_HEAP_GB", value = "3" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = local.region
        awslogs-stream-prefix = "lirical"
      }
    }
  }])
}
