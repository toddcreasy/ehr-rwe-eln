from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import custom_resources as cr
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[2]


class AgentStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        project = self.node.get_context("project")
        # Inference profile IDs, e.g. us.anthropic.claude-haiku-4-5-20251001-v1:0
        models = {
            "MODEL_SMALL": self.node.get_context("model_small"),
            "MODEL_LARGE": self.node.get_context("model_large"),
        }
        # Runtime names allow letters, digits and underscores only.
        runtime_name = f"{project.replace('-', '_')}_hello"

        image = ecr_assets.DockerImageAsset(
            self,
            "AgentImage",
            directory=str(REPO_ROOT),
            file="Dockerfile.agent",
            # AgentCore Runtime only runs ARM64 (Graviton) containers.
            platform=ecr_assets.Platform.LINUX_ARM64,
        )

        role = iam.Role(
            self,
            "AgentRuntimeRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                # Confused-deputy guard: only AgentCore acting for this account may assume it.
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:*"
                    },
                },
            ),
        )
        image.repository.grant_pull(role)

        # A us. profile can route to any US region, so allow the profile ARN plus the base
        # model in every region; otherwise InvokeModel fails with AccessDenied.
        model_arns = []
        for profile_id in models.values():
            base_model_id = profile_id.split(".", 1)[1]
            model_arns += [
                f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{profile_id}",
                f"arn:aws:bedrock:*::foundation-model/{base_model_id}",
            ]
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=model_arns,
            )
        )

        runtime_log_groups = (
            f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws/bedrock-agentcore/runtimes/*"
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup", "logs:DescribeLogStreams"],
                resources=[runtime_log_groups],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[f"{runtime_log_groups}:log-stream:*"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:DescribeLogGroups"],
                resources=[f"arn:aws:logs:{self.region}:{self.account}:log-group:*"],
            )
        )
        # ForUserId is left out on purpose: it issues tokens for any caller-supplied user id.
        identity_dir = (
            f"arn:aws:bedrock-agentcore:{self.region}:{self.account}"
            ":workload-identity-directory/default"
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "bedrock-agentcore:GetWorkloadAccessToken",
                    "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                ],
                resources=[identity_dir, f"{identity_dir}/workload-identity/{runtime_name}-*"],
            )
        )

        runtime = agentcore.CfnRuntime(
            self,
            "HelloRuntime",
            agent_runtime_name=runtime_name,
            description="Phase 4 platform check agent (Strands on Bedrock)",
            role_arn=role.role_arn,
            agent_runtime_artifact=agentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=agentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=image.image_uri
                )
            ),
            # PUBLIC: outbound internet so the agent reaches Bedrock without NAT or endpoints.
            # Inbound calls still need IAM-signed requests to the AgentCore API.
            network_configuration=agentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC"
            ),
            protocol_configuration="HTTP",
            environment_variables={**models, "LOG_LEVEL": "INFO"},
        )
        # The role's policy must exist before AgentCore validates and assumes the role.
        runtime.node.add_dependency(role)

        # AgentCore creates this log group itself, at runtime creation, with no expiry, so
        # CloudFormation can't own it. Set 30-day retention on it after the fact instead.
        log_group_name = f"/aws/bedrock-agentcore/runtimes/{runtime.attr_agent_runtime_id}-DEFAULT"
        set_retention = cr.AwsSdkCall(
            service="CloudWatchLogs",
            action="putRetentionPolicy",
            parameters={"logGroupName": log_group_name, "retentionInDays": 30},
            physical_resource_id=cr.PhysicalResourceId.of(log_group_name),
        )
        cr.AwsCustomResource(
            self,
            "RuntimeLogRetention",
            on_create=set_retention,
            on_update=set_retention,
            policy=cr.AwsCustomResourcePolicy.from_statements(
                [
                    iam.PolicyStatement(
                        actions=["logs:PutRetentionPolicy"],
                        resources=[
                            f"arn:aws:logs:{self.region}:{self.account}:log-group:{log_group_name}"
                        ],
                    )
                ]
            ),
            # The helper Lambda's own logs: without this they would never expire either.
            log_group=logs.LogGroup(
                self,
                "RetentionHelperLogs",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            install_latest_aws_sdk=False,
        )

        cdk.CfnOutput(self, "AgentRuntimeArn", value=runtime.attr_agent_runtime_arn)
        cdk.CfnOutput(self, "AgentLogGroup", value=log_group_name)
