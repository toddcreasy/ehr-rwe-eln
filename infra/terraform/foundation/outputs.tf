output "vpc_id" {
  value = aws_vpc.main.id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "app_security_group_id" {
  value = aws_security_group.app.id
}

output "omop_table_bucket_arn" {
  value = aws_s3tables_table_bucket.omop.arn
}

output "redshift_workgroup" {
  value = aws_redshiftserverless_workgroup.main.workgroup_name
}

output "redshift_workgroup_arn" {
  value = aws_redshiftserverless_workgroup.main.arn
}

output "lake_glue_arns" {
  value = local.lake_glue_arns
}

output "redshift_endpoint" {
  value = aws_redshiftserverless_workgroup.main.endpoint[0].address
}

output "redshift_admin_secret_arn" {
  value = aws_redshiftserverless_namespace.main.admin_password_secret_arn
}

output "aurora_cluster_arn" {
  value = aws_rds_cluster.app.arn
}

output "aurora_endpoint" {
  value = aws_rds_cluster.app.endpoint
}

output "aurora_cluster_resource_id" {
  value = aws_rds_cluster.app.cluster_resource_id
}

output "aurora_master_secret_arn" {
  value = aws_rds_cluster.app.master_user_secret[0].secret_arn
}
