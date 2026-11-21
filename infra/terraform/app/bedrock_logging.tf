# Bedrock model invocation logging: every request and response, with the caller's identity, so a
# reported misuse of /api/agent can be looked up. Off by default in AWS.
# One setting per account and Region: this logs every Bedrock call in us-east-1, including other
# projects in the account, evals, and ELN extraction. Prompts and responses are kept as text
# (what public visitors type included) for 30 days; image, embedding, and video data are not.

resource "aws_cloudwatch_log_group" "bedrock" {
  name              = "/bedrock/invocations"
  retention_in_days = 30
}

data "aws_iam_policy_document" "bedrock_logging_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bedrock:${local.region}:${local.account_id}:*"]
    }
  }
}

resource "aws_iam_role" "bedrock_logging" {
  name               = "${local.name}-bedrock-logging"
  assume_role_policy = data.aws_iam_policy_document.bedrock_logging_trust.json
}

data "aws_iam_policy_document" "bedrock_logging" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.bedrock.arn}:*"]
  }
}

resource "aws_iam_role_policy" "bedrock_logging" {
  role   = aws_iam_role.bedrock_logging.id
  policy = data.aws_iam_policy_document.bedrock_logging.json
}

resource "aws_bedrock_model_invocation_logging_configuration" "main" {
  logging_config {
    text_data_delivery_enabled      = true
    image_data_delivery_enabled     = false
    embedding_data_delivery_enabled = false
    video_data_delivery_enabled     = false

    cloudwatch_config {
      log_group_name = aws_cloudwatch_log_group.bedrock.name
      role_arn       = aws_iam_role.bedrock_logging.arn
    }
  }

  depends_on = [aws_iam_role_policy.bedrock_logging]
}
