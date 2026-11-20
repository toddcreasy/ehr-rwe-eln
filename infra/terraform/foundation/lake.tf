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

# Lake Formation admins can grant, not read. These let each admin see the cdm database and query
# its tables (through Redshift or Athena). The app's role gets its own grant in step 4.
locals {
  omop_catalog_id = "${local.account_id}:s3tablescatalog/${aws_s3tables_table_bucket.omop.name}"
}

resource "aws_lakeformation_permissions" "cdm_database" {
  for_each    = toset(var.lake_admin_arns)
  principal   = each.value
  permissions = ["DESCRIBE"]

  database {
    catalog_id = local.omop_catalog_id
    name       = aws_s3tables_namespace.cdm.namespace
  }

  depends_on = [aws_glue_catalog.s3tables]
}

resource "aws_lakeformation_permissions" "cdm_tables" {
  for_each    = toset(var.lake_admin_arns)
  principal   = each.value
  permissions = ["SELECT", "DESCRIBE"]

  table {
    catalog_id    = local.omop_catalog_id
    database_name = aws_s3tables_namespace.cdm.namespace
    wildcard      = true
  }

  depends_on = [aws_glue_catalog.s3tables]
}

# Redshift's auto-mounted awsdatacatalog only walks the default Glue catalog, so it reaches the
# lake through this resource link: awsdatacatalog.omop_cdm.<table> in Redshift.
resource "aws_glue_catalog_database" "omop_cdm_link" {
  name = "omop_cdm"

  target_database {
    catalog_id    = local.omop_catalog_id
    database_name = aws_s3tables_namespace.cdm.namespace
    region        = local.region
  }

  # AWS fills these in on a link to an S3 Tables catalog; removing them could break the link.
  lifecycle {
    ignore_changes = [parameters, federated_database]
  }

  depends_on = [aws_glue_catalog.s3tables]
}

# No grant on the link for the lake admins: Lake Formation gives whoever creates a database every
# permission on it, and an explicit DESCRIBE grant here drifted against that on every plan. Other
# roles that read through the link (the app's) get their own grant in their stack.
