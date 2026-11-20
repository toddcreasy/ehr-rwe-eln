# Aurora Serverless v2 PostgreSQL: the app's own data (module schemas, curation decisions,
# synthetic releases) and pgvector. Never OMOP; that lives in the lake. Pauses to 0 ACU after
# 5 idle minutes and takes about 15 s to wake.

resource "aws_db_subnet_group" "aurora" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_rds_cluster" "app" {
  cluster_identifier          = local.name
  engine                      = "aurora-postgresql"
  engine_version              = "18.6"
  engine_mode                 = "provisioned"
  database_name               = "ehr_rwe_eln"
  master_username             = "postgres"
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.aurora.name
  vpc_security_group_ids      = [aws_security_group.aurora.id]
  storage_encrypted           = true
  backup_retention_period     = 1
  deletion_protection         = true
  skip_final_snapshot         = true

  # RDS Data API: SQL over HTTPS with IAM auth, so a laptop can reach the private cluster.
  enable_http_endpoint = true

  serverlessv2_scaling_configuration {
    min_capacity             = 0
    max_capacity             = 4
    seconds_until_auto_pause = 300
  }
}

resource "aws_rds_cluster_instance" "app" {
  identifier         = "${local.name}-1"
  cluster_identifier = aws_rds_cluster.app.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.app.engine
  engine_version     = aws_rds_cluster.app.engine_version
}
