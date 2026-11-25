terraform {
  required_version = "~> 1.17"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.73"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }

  # Partial config: the bucket name holds the account ID, so it comes from
  # `terraform init -backend-config="bucket=..."` and stays out of the repo.
  backend "s3" {
    key          = "app/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

# The account ID is the state bucket's suffix; Terraform refuses to touch any other account.
provider "aws" {
  region              = "us-east-1"
  allowed_account_ids = [trimprefix(var.state_bucket, "ehr-rwe-eln-tfstate-")]

  default_tags {
    tags = {
      project    = "ehr-rwe-eln"
      env        = "dev"
      managed-by = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# The network, databases, and lake, from the foundation stack's state.
data "terraform_remote_state" "foundation" {
  backend = "s3"
  config = {
    bucket = var.state_bucket
    key    = "foundation/terraform.tfstate"
    region = "us-east-1"
  }
}

locals {
  name       = "ehr-rwe-eln"
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.region
  foundation = data.terraform_remote_state.foundation.outputs
  image      = "${aws_ecr_repository.app.repository_url}:${var.image_tag}"

  # Settings every container gets; see .env.example for what each means.
  database_env = {
    DB_HOST     = local.foundation.aurora_endpoint
    DB_PORT     = "5432"
    DB_NAME     = "ehr_rwe_eln"
    DB_USER     = "app"
    DB_IAM_AUTH = "true"
  }
  lake_env = {
    OMOP_SOURCE           = "lake"
    LAKE_TABLE_BUCKET_ARN = local.foundation.omop_table_bucket_arn
    AWS_REGION            = local.region
    REDSHIFT_WORKGROUP    = local.foundation.redshift_workgroup
  }
  # ECS reads the Aurora password out of its Secrets Manager secret (JSON) into DB_PASSWORD.
  db_credential_ref = "${local.foundation.aurora_master_secret_arn}:password::"
  # The one Aurora user the app and monitor may sign in as with an IAM token.
  aurora_app_user_arn = "arn:aws:rds-db:${local.region}:${local.account_id}:dbuser:${local.foundation.aurora_cluster_resource_id}/app"
}
