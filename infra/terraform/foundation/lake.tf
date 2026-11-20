# The lake: OMOP tables as Apache Iceberg in an S3 table bucket, registered with Lake Formation and
# exposed through the Glue Data Catalog as `s3tablescatalog`, so Redshift and Athena can query them.

resource "aws_s3tables_table_bucket" "omop" {
  name = "${local.name}-omop"
}

resource "aws_s3tables_namespace" "cdm" {
  namespace        = "cdm"
  table_bucket_arn = aws_s3tables_table_bucket.omop.arn
}

# Account-wide: this list replaces any existing Lake Formation admins (there were none on 2026-11-19).
resource "aws_lakeformation_data_lake_settings" "main" {
  admins = var.lake_admin_arns
}

# The role Lake Formation assumes to read and write the table buckets on a caller's behalf.
data "aws_iam_policy_document" "lakeformation_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:SetContext", "sts:SetSourceIdentity"]
    principals {
      type        = "Service"
      identifiers = ["lakeformation.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "lakeformation_s3tables" {
  name               = "${local.name}-lakeformation-s3tables"
  assume_role_policy = data.aws_iam_policy_document.lakeformation_trust.json
}

locals {
  table_buckets_arn = "arn:aws:s3tables:${local.region}:${local.account_id}:bucket/*"
}

data "aws_iam_policy_document" "lakeformation_s3tables" {
  statement {
    actions = [
      "s3tables:ListTableBuckets",
      "s3tables:GetTableBucket",
      "s3tables:CreateNamespace",
      "s3tables:GetNamespace",
      "s3tables:ListNamespaces",
      "s3tables:DeleteNamespace",
      "s3tables:CreateTable",
      "s3tables:DeleteTable",
      "s3tables:GetTable",
      "s3tables:ListTables",
      "s3tables:RenameTable",
      "s3tables:UpdateTableMetadataLocation",
      "s3tables:GetTableMetadataLocation",
      "s3tables:GetTableData",
      "s3tables:PutTableData",
    ]
    resources = [local.table_buckets_arn]
  }
}

resource "aws_iam_role_policy" "lakeformation_s3tables" {
  role   = aws_iam_role.lakeformation_s3tables.id
  policy = data.aws_iam_policy_document.lakeformation_s3tables.json
}

resource "aws_lakeformation_resource" "s3tables" {
  arn             = local.table_buckets_arn
  role_arn        = aws_iam_role.lakeformation_s3tables.arn
  with_federation = true

  depends_on = [aws_lakeformation_data_lake_settings.main, aws_iam_role_policy.lakeformation_s3tables]
}

resource "aws_glue_catalog" "s3tables" {
  name                                  = "s3tablescatalog"
  allow_full_table_external_data_access = "True"

  federated_catalog {
    identifier      = local.table_buckets_arn
    connection_name = "aws:s3tables"
  }

  depends_on = [aws_lakeformation_resource.s3tables]
}
