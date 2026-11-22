# CodeBuild for the app image: builds the repository's Dockerfile on an ARM host (the app runs on
# ARM Fargate) and pushes it to the app's ECR repository, tagged with its git commit. The source is
# a zip of that commit (git archive) that scripts/build_app_image.py uploads under build/ in the
# genomics bucket, where objects expire after 30 days. Nothing builds on the laptop.

resource "aws_cloudwatch_log_group" "app_build" {
  name              = "/codebuild/${local.name}-app"
  retention_in_days = 30
}

resource "aws_iam_role" "app_build" {
  name               = "${local.name}-app-build"
  assume_role_policy = data.aws_iam_policy_document.codebuild_trust.json
}

data "aws_iam_policy_document" "app_build" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.app_build.arn}:*"]
  }
  statement {
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.gwas.arn}/build/app-*"]
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
    resources = [aws_ecr_repository.app.arn]
  }
}

resource "aws_iam_role_policy" "app_build" {
  role   = aws_iam_role.app_build.id
  policy = data.aws_iam_policy_document.app_build.json
}

resource "aws_codebuild_project" "app" {
  name          = "${local.name}-app"
  service_role  = aws_iam_role.app_build.arn
  build_timeout = 30

  # The runner sets the source to build/app-<commit>.zip and TAG to the commit for each build.
  source {
    type     = "S3"
    location = "${aws_s3_bucket.gwas.id}/build/app.zip"
    buildspec = yamlencode({
      version = "0.2"
      phases = {
        pre_build = {
          commands = ["aws ecr get-login-password | docker login --username AWS --password-stdin $${REPOSITORY%%/*}"]
        }
        build = {
          commands = [
            "DOCKER_BUILDKIT=1 docker build --platform linux/arm64 -t $REPOSITORY:$TAG .",
            "docker push $REPOSITORY:$TAG",
          ]
        }
      }
    })
  }

  artifacts {
    type = "NO_ARTIFACTS"
  }

  # The Next.js and uv builds want more memory than the small ARM host's 4 GB.
  environment {
    type            = "ARM_CONTAINER"
    compute_type    = "BUILD_GENERAL1_LARGE"
    image           = "aws/codebuild/amazonlinux-aarch64-standard:3.0"
    privileged_mode = true

    environment_variable {
      name  = "REPOSITORY"
      value = aws_ecr_repository.app.repository_url
    }
    environment_variable {
      name  = "TAG"
      value = "unset"
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.app_build.name
    }
  }
}
