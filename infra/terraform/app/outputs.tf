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
