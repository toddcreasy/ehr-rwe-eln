# The GWAS on AWS (module 5, step 6e): PLINK 2 and REGENIE in an x86 image, which CodeBuild builds
# on x86 and an on-demand Fargate task runs. REGENIE ships no ARM build, so nothing here runs on
# the laptop. scripts/run_regenie.py uploads the study, builds the image if its tag is missing,
# runs the task, and downloads the results.
#
# The image tag is a hash of the two files that make the image, computed the same way in
# run_regenie.py, so a change to either gives a new immutable tag and this task definition follows.

locals {
  gwas_files     = ["gwas.Dockerfile", "gwas_task.py"]
  gwas_image_tag = substr(sha256(join("", [for f in local.gwas_files : filesha256("${path.module}/../../../docker/${f}")])), 0, 12)
}

# Study files in (studies/<id>/input/), results out (studies/<id>/output/), the images' build
# contexts (build/), and Exomiser's data bundle (reference/exomiser/<release>/, exomiser.tf).
# Synthetic data and public reference data only; private, TLS only. Studies and build contexts
# expire after 30 days; the reference data stays until a release is replaced.
resource "aws_s3_bucket" "gwas" {
  bucket = "${local.name}-genomics-${local.account_id}"
}

resource "aws_s3_bucket_public_access_block" "gwas" {
  bucket                  = aws_s3_bucket.gwas.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "gwas" {
  bucket = aws_s3_bucket.gwas.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# trivy:ignore:AWS-0132 SSE-S3 rather than a customer managed key ($1/month); synthetic and public reference data, private, TLS only.
resource "aws_s3_bucket_server_side_encryption_configuration" "gwas" {
  bucket = aws_s3_bucket.gwas.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "gwas" {
  bucket = aws_s3_bucket.gwas.id
  dynamic "rule" {
    for_each = ["studies/", "build/"]
    content {
      id     = "expire-${trimsuffix(rule.value, "/")}-after-30-days"
      status = "Enabled"
      filter {
        prefix = rule.value
      }
      expiration {
        days = 30
      }
    }
  }
}

data "aws_iam_policy_document" "gwas_bucket" {
  statement {
    sid       = "TLSOnly"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.gwas.arn, "${aws_s3_bucket.gwas.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "gwas" {
  bucket = aws_s3_bucket.gwas.id
  policy = data.aws_iam_policy_document.gwas_bucket.json
}

resource "aws_ecr_repository" "gwas" {
  name                 = "${local.name}-gwas"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "gwas" {
  repository = aws_ecr_repository.gwas.name
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

# CodeBuild: builds an image from a zip under build/ on an x86 host and pushes it. By default the
# gwas image from build/gwas-<tag>.zip; scripts/run_exomiser.py and scripts/run_bias.py override
# the source, DOCKERFILE, REPOSITORY, and TAG to build their images. Privileged mode is what lets
# a CodeBuild container run docker build.
resource "aws_cloudwatch_log_group" "gwas_build" {
  name              = "/codebuild/${local.name}-gwas"
  retention_in_days = 30
}

data "aws_iam_policy_document" "codebuild_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "gwas_build" {
  name               = "${local.name}-gwas-build"
  assume_role_policy = data.aws_iam_policy_document.codebuild_trust.json
}

data "aws_iam_policy_document" "gwas_build" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.gwas_build.arn}:*"]
  }
  statement {
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.gwas.arn}/build/*"]
  }
  statement {
    actions   = ["s3:GetBucketAcl", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.gwas.arn]
  }
  # GetAuthorizationToken has no resource-level permissions; the push is limited to this repository.
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [aws_ecr_repository.gwas.arn, aws_ecr_repository.exomiser.arn, aws_ecr_repository.bias.arn, aws_ecr_repository.synth.arn]
  }
}

resource "aws_iam_role_policy" "gwas_build" {
  role   = aws_iam_role.gwas_build.id
  policy = data.aws_iam_policy_document.gwas_build.json
}

resource "aws_codebuild_project" "gwas" {
  name          = "${local.name}-gwas"
  service_role  = aws_iam_role.gwas_build.arn
  build_timeout = 30

  source {
    type     = "S3"
    location = "${aws_s3_bucket.gwas.id}/build/gwas-${local.gwas_image_tag}.zip"
    buildspec = yamlencode({
      version = "0.2"
      phases = {
        pre_build = {
          commands = ["aws ecr get-login-password | docker login --username AWS --password-stdin $${REPOSITORY%%/*}"]
        }
        build = {
          commands = [
            "docker build --platform linux/amd64 -f $DOCKERFILE -t $REPOSITORY:$TAG .",
            "docker push $REPOSITORY:$TAG",
          ]
        }
      }
    })
  }

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    type            = "LINUX_CONTAINER"
    compute_type    = "BUILD_GENERAL1_SMALL"
    image           = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
    privileged_mode = true

    environment_variable {
      name  = "DOCKERFILE"
      value = "gwas.Dockerfile"
    }
    environment_variable {
      name  = "REPOSITORY"
      value = aws_ecr_repository.gwas.repository_url
    }
    environment_variable {
      name  = "TAG"
      value = local.gwas_image_tag
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.gwas_build.name
    }
  }
}

# The task: reads and writes the bucket's studies/ prefix, nothing else.
resource "aws_iam_role" "gwas" {
  name               = "${local.name}-gwas"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

data "aws_iam_policy_document" "gwas" {
  statement {
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${aws_s3_bucket.gwas.arn}/studies/*"]
  }
}

resource "aws_iam_role_policy" "gwas" {
  role   = aws_iam_role.gwas.id
  policy = data.aws_iam_policy_document.gwas.json
}

resource "aws_ecs_task_definition" "gwas" {
  family                   = "${local.name}-gwas"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "2048"
  memory                   = "8192"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.gwas.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name        = "gwas"
    image       = "${aws_ecr_repository.gwas.repository_url}:${local.gwas_image_tag}"
    essential   = true
    environment = [{ name = "GWAS_BUCKET", value = aws_s3_bucket.gwas.id }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = local.region
        awslogs-stream-prefix = "gwas"
      }
    }
  }])
}
