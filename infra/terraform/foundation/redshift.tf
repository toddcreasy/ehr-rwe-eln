# Redshift Serverless: the SQL engine OHDSI's DatabaseConnector supports. A namespace holds the
# database and admin user; a workgroup holds compute and networking. Billed per second of query
# time; nothing while idle.

data "aws_iam_policy_document" "redshift_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["redshift.amazonaws.com", "redshift-serverless.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "redshift" {
  name               = "${local.name}-redshift"
  assume_role_policy = data.aws_iam_policy_document.redshift_trust.json
}

# Read the catalog and get Lake Formation credentials for the lake tables.
data "aws_iam_policy_document" "redshift_lake" {
  statement {
    actions = [
      "glue:GetCatalog",
      "glue:GetCatalogs",
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartitions",
      "lakeformation:GetDataAccess",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "redshift_lake" {
  role   = aws_iam_role.redshift.id
  policy = data.aws_iam_policy_document.redshift_lake.json
}

resource "aws_redshiftserverless_namespace" "main" {
  namespace_name        = local.name
  db_name               = "ehr_rwe_eln"
  admin_username        = "rwe_admin"
  manage_admin_password = true
  iam_roles             = [aws_iam_role.redshift.arn]
  default_iam_role_arn  = aws_iam_role.redshift.arn
}

resource "aws_redshiftserverless_workgroup" "main" {
  workgroup_name      = local.name
  namespace_name      = aws_redshiftserverless_namespace.main.namespace_name
  base_capacity       = 8
  max_capacity        = 16
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.redshift.id]
  publicly_accessible = false
}

# Hard cap: past 60 RPU-hours in a month the workgroup stops taking queries.
resource "aws_redshiftserverless_usage_limit" "monthly" {
  resource_arn  = aws_redshiftserverless_workgroup.main.arn
  usage_type    = "serverless-compute"
  amount        = 60
  period        = "monthly"
  breach_action = "deactivate"
}
