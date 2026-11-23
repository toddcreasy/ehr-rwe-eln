# BIAS-2015 on AWS (module 6, step 6f): an open automated ACMG classifier, run as a baseline on
# the Evidence Repository variants. It needs Ensembl VEP 115 annotations, whose GRCh38 cache is
# 25 GB, so it never runs on the laptop: a one-off task fetches the cache, the genome FASTA, and
# BIAS's own tables into the genomics bucket (reference/vep/115/, reference/bias/2026.03.01/),
# and each run copies them to the task's disk. The image builds on the gwas CodeBuild project
# (gwas.tf) with its source and Dockerfile overridden. scripts/run_bias.py does all of it.
#
# The image tag is a hash of the two files that make the image, computed the same way in
# run_bias.py.

locals {
  bias_files     = ["bias.Dockerfile", "bias_task.py"]
  bias_image_tag = substr(sha256(join("", [for f in local.bias_files : filesha256("${path.module}/../../../docker/${f}")])), 0, 12)
}

resource "aws_ecr_repository" "bias" {
  name                 = "${local.name}-bias"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "bias" {
  repository = aws_ecr_repository.bias.name
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

# The task: reads and writes the bucket's studies/ and its own reference/ prefixes, and lists
# those reference prefixes, nothing else. It reaches Ensembl, Bitscopic's public bucket, and
# gnomAD's public bucket through the task's public IP, like every task here.
resource "aws_iam_role" "bias" {
  name               = "${local.name}-bias"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

data "aws_iam_policy_document" "bias" {
  statement {
    actions = ["s3:GetObject", "s3:PutObject"]
    resources = [
      "${aws_s3_bucket.gwas.arn}/studies/*",
      "${aws_s3_bucket.gwas.arn}/reference/vep/*",
      "${aws_s3_bucket.gwas.arn}/reference/bias/*",
    ]
  }
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.gwas.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["reference/vep/*", "reference/bias/*"]
    }
  }
}

resource "aws_iam_role_policy" "bias" {
  role   = aws_iam_role.bias.id
  policy = data.aws_iam_policy_document.bias.json
}

# VEP with --fork 4 and BIAS's tables (about 5 GB in memory) fit in 16 GB; 200 GiB of disk holds
# the cache archive and its unpacked copy at once.
resource "aws_ecs_task_definition" "bias" {
  family                   = "${local.name}-bias"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "4096"
  memory                   = "16384"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.bias.arn

  ephemeral_storage {
    size_in_gib = 200
  }

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name        = "bias"
    image       = "${aws_ecr_repository.bias.repository_url}:${local.bias_image_tag}"
    essential   = true
    environment = [{ name = "BIAS_BUCKET", value = aws_s3_bucket.gwas.id }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = local.region
        awslogs-stream-prefix = "bias"
      }
    }
  }])
}
