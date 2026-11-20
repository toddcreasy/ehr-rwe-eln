terraform {
  required_version = "~> 1.17"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.73"
    }
  }

  # Partial config: the bucket name holds the account ID, so it comes from
  # `terraform init -backend-config="bucket=..."` and stays out of the repo.
  backend "s3" {
    key          = "foundation/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = "us-east-1"

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

locals {
  name       = "ehr-rwe-eln"
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.region
}
