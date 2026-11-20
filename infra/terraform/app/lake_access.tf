# The monitor reads OMOP from the lake as its own IAM role, so Lake Formation has to let it see the
# cdm database and read its tables, and see the omop_cdm resource link Redshift reads through.
# The Redshift side (GRANT USAGE ON DATABASE awsdatacatalog) is in infra/redshift/grants.sql.

locals {
  omop_catalog_id = "${local.account_id}:s3tablescatalog/${local.name}-omop"
}

resource "aws_lakeformation_permissions" "monitor_cdm_database" {
  principal   = aws_iam_role.monitor.arn
  permissions = ["DESCRIBE"]

  database {
    catalog_id = local.omop_catalog_id
    name       = "cdm"
  }
}

resource "aws_lakeformation_permissions" "monitor_cdm_tables" {
  principal   = aws_iam_role.monitor.arn
  permissions = ["SELECT", "DESCRIBE"]

  table {
    catalog_id    = local.omop_catalog_id
    database_name = "cdm"
    wildcard      = true
  }
}

resource "aws_lakeformation_permissions" "monitor_link" {
  principal   = aws_iam_role.monitor.arn
  permissions = ["DESCRIBE"]

  database {
    name = "omop_cdm"
  }
}
