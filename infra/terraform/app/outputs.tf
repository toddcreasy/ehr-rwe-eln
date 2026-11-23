output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "cluster" {
  value = aws_ecs_cluster.main.name
}

output "app_url" {
  description = "The public HTTPS URL Express Mode gave the service."
  value       = try(aws_ecs_express_gateway_service.app.ingress_paths[0].endpoint, null)
}

output "bastion_task_definition" {
  value = aws_ecs_task_definition.bastion.arn_without_revision
}

output "monitor_task_definition" {
  value = aws_ecs_task_definition.monitor.arn_without_revision
}

output "public_subnet_ids" {
  value = local.foundation.public_subnet_ids
}

output "app_security_group_id" {
  value = local.foundation.app_security_group_id
}

output "gwas_bucket" {
  value = aws_s3_bucket.gwas.id
}

output "gwas_repository" {
  value = aws_ecr_repository.gwas.name
}

output "gwas_image_tag" {
  value = local.gwas_image_tag
}

output "gwas_codebuild_project" {
  value = aws_codebuild_project.gwas.name
}

output "gwas_task_definition" {
  value = aws_ecs_task_definition.gwas.arn_without_revision
}

output "exomiser_repository" {
  value = aws_ecr_repository.exomiser.name
}

output "exomiser_repository_url" {
  value = aws_ecr_repository.exomiser.repository_url
}

output "exomiser_image_tag" {
  value = local.exomiser_image_tag
}

output "exomiser_task_definition" {
  value = aws_ecs_task_definition.exomiser.arn_without_revision
}

output "app_codebuild_project" {
  value = aws_codebuild_project.app.name
}

output "bias_repository" {
  value = aws_ecr_repository.bias.name
}

output "bias_repository_url" {
  value = aws_ecr_repository.bias.repository_url
}

output "bias_image_tag" {
  value = local.bias_image_tag
}

output "bias_task_definition" {
  value = aws_ecs_task_definition.bias.arn_without_revision
}

output "synth_repository" {
  value = aws_ecr_repository.synth.name
}

output "synth_repository_url" {
  value = aws_ecr_repository.synth.repository_url
}

output "synth_image_tag" {
  value = local.synth_image_tag
}

output "synth_task_definition" {
  value = aws_ecs_task_definition.synth.arn_without_revision
}
