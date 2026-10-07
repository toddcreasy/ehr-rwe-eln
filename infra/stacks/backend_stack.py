from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_rds as rds
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[2]


class BackendStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        database: rds.DatabaseCluster,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        project = self.node.get_context("project")
        # 1 = running, 0 = paused. Pause with: cdk deploy BackendStack -c backend_tasks=0
        tasks = int(self.node.get_context("backend_tasks"))

        image = ecr_assets.DockerImageAsset(
            self, "ApiImage", directory=str(REPO_ROOT), platform=ecr_assets.Platform.LINUX_AMD64
        )

        cluster = ecs.Cluster(
            self, "Cluster", cluster_name=project, vpc=vpc, enable_fargate_capacity_providers=True
        )

        log_group = logs.LogGroup(
            self,
            "ApiLogs",
            log_group_name=f"/{project}/api",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        task_sg = ec2.SecurityGroup(
            self, "ApiTaskSecurityGroup", vpc=vpc, description="ECS Express API tasks"
        )
        # Declared here, not via database.connections, so the rule lives in this stack and
        # DataStack never depends on BackendStack (that would be a cross-stack cycle).
        ec2.CfnSecurityGroupIngress(
            self,
            "ApiToAurora",
            group_id=database.connections.security_groups[0].security_group_id,
            source_security_group_id=task_sg.security_group_id,
            ip_protocol="tcp",
            from_port=5432,
            to_port=5432,
            description="API tasks to Aurora",
        )

        execution_role = iam.Role(
            self,
            "ApiExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                )
            ],
        )
        database.secret.grant_read(execution_role)

        infrastructure_role = iam.Role(
            self,
            "ExpressInfrastructureRole",
            assumed_by=iam.ServicePrincipal("ecs.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
                )
            ],
        )

        # ECS reads each JSON key of the database secret at task start ("<arn>:<key>::").
        secret_arn = database.secret.secret_arn
        secrets = [
            ecs.CfnExpressGatewayService.SecretProperty(
                name=env_name, value_from=f"{secret_arn}:{key}::"
            )
            for env_name, key in [
                ("DB_HOST", "host"),
                ("DB_PORT", "port"),
                ("DB_NAME", "dbname"),
                ("DB_USER", "username"),
                ("DB_PASSWORD", "password"),
            ]
        ]

        service = ecs.CfnExpressGatewayService(
            self,
            "ApiService",
            service_name=f"{project}-api",
            cluster=cluster.cluster_name,
            cpu="256",
            memory="512",
            execution_role_arn=execution_role.role_arn,
            infrastructure_role_arn=infrastructure_role.role_arn,
            # Never /health/db: the load balancer polls this every 30 s and would keep Aurora awake.
            health_check_path="/health",
            network_configuration=ecs.CfnExpressGatewayService.ExpressGatewayServiceNetworkConfigurationProperty(
                subnets=[s.subnet_id for s in vpc.public_subnets],
                security_groups=[task_sg.security_group_id],
            ),
            primary_container=ecs.CfnExpressGatewayService.ExpressGatewayContainerProperty(
                image=image.image_uri,
                container_port=8000,
                environment=[
                    ecs.CfnExpressGatewayService.KeyValuePairProperty(
                        name="LOG_LEVEL", value="INFO"
                    )
                ],
                secrets=secrets,
                aws_logs_configuration=ecs.CfnExpressGatewayService.ExpressGatewayServiceAwsLogsConfigurationProperty(
                    log_group=log_group.log_group_name, log_stream_prefix="api"
                ),
            ),
            scaling_target=ecs.CfnExpressGatewayService.ExpressGatewayScalingTargetProperty(
                min_task_count=tasks, max_task_count=tasks
            ),
        )
        # Roles (with their policies) and Fargate capacity must exist before Express uses them.
        service.node.add_dependency(execution_role, infrastructure_role, cluster)

        # Hostname only (no scheme); AgentStack builds the Gateway target URL from it.
        self.api_endpoint = service.attr_endpoint

        cdk.CfnOutput(self, "ApiEndpoint", value=service.attr_endpoint)
        cdk.CfnOutput(self, "ApiLogGroup", value=log_group.log_group_name)
