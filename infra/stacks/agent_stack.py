import hashlib
import json
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from aws_cdk import custom_resources as cr
from constructs import Construct

REPO_ROOT = Path(__file__).resolve().parents[2]


class AgentStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        api_endpoint: str,
        alerts_topic: sns.ITopic,
        **kwargs,
    ) -> None:
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

        guardrail_config = {
            "pii": ["NAME", "EMAIL", "PHONE", "ADDRESS", "US_SOCIAL_SECURITY_NUMBER"],
            "topic": {
                "name": "ClinicalAdvice",
                # Bedrock caps a topic definition at 200 characters.
                "definition": (
                    "Requests for diagnosis, treatment, medication dosing, or other medical advice "
                    "about a real or hypothetical patient."
                ),
                "examples": [
                    "What dose of metformin should I give my patient?",
                    "Do I have diabetes?",
                ],
            },
            "blocked": (
                "This is a research tool on synthetic data and cannot help with that request. "
                "It does not give medical or clinical advice."
            ),
        }
        guardrail = bedrock.CfnGuardrail(
            self,
            "AgentGuardrail",
            name=f"{project}-agent",
            blocked_input_messaging=guardrail_config["blocked"],
            blocked_outputs_messaging=guardrail_config["blocked"],
            sensitive_information_policy_config=bedrock.CfnGuardrail.SensitiveInformationPolicyConfigProperty(
                pii_entities_config=[
                    bedrock.CfnGuardrail.PiiEntityConfigProperty(type=pii, action="ANONYMIZE")
                    for pii in guardrail_config["pii"]
                ]
            ),
            topic_policy_config=bedrock.CfnGuardrail.TopicPolicyConfigProperty(
                topics_config=[
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        type="DENY", **guardrail_config["topic"]
                    )
                ]
            ),
        )
        # Versions are immutable and CloudFormation never cuts a new one on a policy change.
        # Hashing the config into the logical id replaces the version whenever the policy moves.
        config_hash = hashlib.sha256(
            json.dumps(guardrail_config, sort_keys=True).encode()
        ).hexdigest()[:8]
        guardrail_version = bedrock.CfnGuardrailVersion(
            self,
            f"AgentGuardrailVersion{config_hash}",
            guardrail_identifier=guardrail.attr_guardrail_id,
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:ApplyGuardrail"], resources=[guardrail.attr_guardrail_arn]
            )
        )

        # Scoped by runtime name: the account hosts other projects' runtimes under the same prefix.
        runtime_log_groups = (
            f"arn:aws:logs:{self.region}:{self.account}:log-group:"
            f"/aws/bedrock-agentcore/runtimes/{runtime_name}-*"
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

        # Gateway: an AWS-hosted MCP server. Inbound auth is IAM (SigV4): only principals with
        # bedrock-agentcore:InvokeGateway on this gateway can list or call its tools.
        gateway_role = iam.Role(
            self,
            "GatewayRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": self.account},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:*"
                    },
                },
            ),
        )
        gateway = agentcore.CfnGateway(
            self,
            "Gateway",
            name=f"{project}-gateway",
            description="MCP tools over the ehr-rwe-eln backend API",
            protocol_type="MCP",
            authorizer_type="AWS_IAM",
            role_arn=gateway_role.role_arn,
        )
        gateway.node.add_dependency(gateway_role)

        # One OpenAPI target. Gateway names each tool <target>___<operationId>, so the agent
        # sees backend___checkDatabaseHealth. No outbound auth for now: /health/db is already
        # public; the target moves to Cognito OAuth (client credentials) in Phase 7.
        backend_api = {
            "openapi": "3.0.0",
            "info": {"title": "ehr-rwe-eln backend", "version": "1.0.0"},
            "servers": [{"url": f"https://{api_endpoint}"}],
            "paths": {
                "/health/db": {
                    "get": {
                        "operationId": "checkDatabaseHealth",
                        "summary": "Check that the backend can reach the Aurora database",
                        "description": (
                            "Runs SELECT 1 against the project database. Returns status ok when "
                            "reachable. The first call after the database has been idle can take "
                            "about 20 seconds while it resumes."
                        ),
                        "responses": {
                            "200": {
                                "description": "Database reachable",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "status": {"type": "string"},
                                                "database": {"type": "string"},
                                            },
                                        }
                                    }
                                },
                            },
                            "503": {"description": "Database unreachable"},
                        },
                    }
                }
            },
        }
        agentcore.CfnGatewayTarget(
            self,
            "BackendTarget",
            name="backend",
            description="ehr-rwe-eln FastAPI backend on ECS Express Mode",
            gateway_identifier=gateway.attr_gateway_identifier,
            target_configuration=agentcore.CfnGatewayTarget.TargetConfigurationProperty(
                mcp=agentcore.CfnGatewayTarget.McpTargetConfigurationProperty(
                    open_api_schema=agentcore.CfnGatewayTarget.ApiSchemaConfigurationProperty(
                        inline_payload=self.to_json_string(backend_api)
                    )
                )
            ),
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeGateway"], resources=[gateway.attr_gateway_arn]
            )
        )

        # The deploy workflow runs evals with the CI role: same models, same Gateway.
        # Looked up by name so OpsStack never references this stack (that would be a cycle).
        iam.Policy(
            self,
            "CiEvalsPolicy",
            roles=[iam.Role.from_role_name(self, "CiRole", f"{project}-github-actions")],
            statements=[
                iam.PolicyStatement(
                    actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                    resources=model_arns,
                ),
                iam.PolicyStatement(
                    actions=["bedrock-agentcore:InvokeGateway"],
                    resources=[gateway.attr_gateway_arn],
                ),
                iam.PolicyStatement(
                    actions=["bedrock:ApplyGuardrail"], resources=[guardrail.attr_guardrail_arn]
                ),
            ],
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
            environment_variables={
                **models,
                "GATEWAY_URL": gateway.attr_gateway_url,
                "GUARDRAIL_ID": guardrail.attr_guardrail_id,
                "GUARDRAIL_VERSION": guardrail_version.attr_version,
                "LOG_LEVEL": "INFO",
            },
        )
        # The role's policy must exist before AgentCore validates and assumes the role.
        runtime.node.add_dependency(role)

        log_group_name = f"/aws/bedrock-agentcore/runtimes/{runtime.attr_agent_runtime_id}-DEFAULT"
        log_group_arn = f"arn:aws:logs:{self.region}:{self.account}:log-group:{log_group_name}"
        runtime_metric_dims = {
            "Resource": runtime.attr_agent_runtime_arn,
            "Operation": "InvokeAgentRuntime",
            "Name": f"{runtime_name}::DEFAULT",
        }

        # --- Tracing -------------------------------------------------------------------------
        # Agent spans (model calls, tool calls) come from ADOT in the container (Dockerfile.agent).
        # New runtimes write them to the `spans` stream of their own log group, which needs
        # PutResourcePolicy on that group. Scoped by runtime name: referencing the runtime id here
        # would make the role depend on the runtime, a dependency cycle.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:PutResourcePolicy"],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:"
                    f"/aws/bedrock-agentcore/runtimes/{runtime_name}-*"
                ],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                ],
                resources=["*"],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}},
            )
        )
        # "Tracing enabled" for the runtime and the Gateway: a TRACES log delivery to X-Ray.
        # Needs CloudWatch Transaction Search, which is already on account-wide (glia-nav owns it).
        xray_destination = logs.CfnDeliveryDestination(
            self, "TracesDestination", name=f"{project}-traces", delivery_destination_type="XRAY"
        )
        for source_id, resource_arn in [
            ("Runtime", runtime.attr_agent_runtime_arn),
            ("Gateway", gateway.attr_gateway_arn),
        ]:
            source = logs.CfnDeliverySource(
                self,
                f"{source_id}TracesSource",
                name=f"{project}-{source_id.lower()}-traces",
                log_type="TRACES",
                resource_arn=resource_arn,
            )
            delivery = logs.CfnDelivery(
                self,
                f"{source_id}TracesDelivery",
                delivery_source_name=source.name,
                delivery_destination_arn=xray_destination.attr_arn,
            )
            delivery.add_dependency(source)

        # --- Managed evaluations (LLM-as-a-judge on live traces) -----------------------------
        eval_role = iam.Role(
            self,
            "EvaluationRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {
                        "aws:SourceAccount": self.account,
                        "aws:ResourceAccount": self.account,
                    },
                    "ArnLike": {
                        "aws:SourceArn": [
                            f"arn:aws:bedrock-agentcore:{self.region}:{self.account}:evaluator/*",
                            f"arn:aws:bedrock-agentcore:{self.region}:{self.account}"
                            ":online-evaluation-config/*",
                        ]
                    },
                },
            ),
        )
        # DescribeLogGroups has no resource type; the queries scope to the groups they read.
        eval_role.add_to_policy(
            iam.PolicyStatement(actions=["logs:DescribeLogGroups"], resources=["*"])
        )
        eval_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:StartQuery", "logs:GetQueryResults"],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:aws/spans",
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:aws/spans:*",
                    log_group_arn,
                    f"{log_group_arn}:*",
                ],
            )
        )
        eval_results_groups = (
            f"arn:aws:logs:{self.region}:{self.account}:log-group:"
            "/aws/bedrock-agentcore/evaluations/*"
        )
        eval_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                resources=[eval_results_groups],
            )
        )
        eval_role.add_to_policy(
            iam.PolicyStatement(
                actions=["logs:DescribeIndexPolicies", "logs:PutIndexPolicy"],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:aws/spans",
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:aws/spans:*",
                    log_group_arn,
                    f"{log_group_arn}:*",
                ],
            )
        )
        # Built-in evaluators run the judge model on AWS's side, so no bedrock:InvokeModel here.
        online_eval = agentcore.CfnOnlineEvaluationConfig(
            self,
            "OnlineEvaluation",
            online_evaluation_config_name=f"{project.replace('-', '_')}_quality",
            description="Response quality and tool selection on live traces",
            evaluation_execution_role_arn=eval_role.role_arn,
            data_source_config=agentcore.CfnOnlineEvaluationConfig.DataSourceConfigProperty(
                cloud_watch_logs=agentcore.CfnOnlineEvaluationConfig.CloudWatchLogsInputConfigProperty(
                    log_group_names=[log_group_name],
                    service_names=[f"{runtime_name}.DEFAULT"],
                )
            ),
            evaluators=[
                agentcore.CfnOnlineEvaluationConfig.EvaluatorReferenceProperty(evaluator_id=e)
                for e in ["Builtin.Helpfulness", "Builtin.ToolSelectionAccuracy"]
            ],
            rule=agentcore.CfnOnlineEvaluationConfig.RuleProperty(
                # Defaults are DISABLED and 10%: it would deploy clean and score nothing.
                # 100% is fine at dev volume; drop to ~10% before real traffic.
                sampling_config=agentcore.CfnOnlineEvaluationConfig.SamplingConfigProperty(
                    sampling_percentage=100
                ),
                session_config=agentcore.CfnOnlineEvaluationConfig.SessionConfigProperty(
                    session_timeout_minutes=15
                ),
            ),
            execution_status="ENABLED",
        )
        online_eval.node.add_dependency(eval_role)
        eval_results_log_group = (
            "/aws/bedrock-agentcore/evaluations/results/"
            f"{online_eval.attr_online_evaluation_config_id}"
        )

        # --- Log retention -------------------------------------------------------------------
        # AgentCore creates the runtime and evaluation-results log groups itself, with no expiry,
        # so CloudFormation can't own them. Set 30-day retention on each after the fact.
        helper_logs = logs.LogGroup(
            self,
            "RetentionHelperLogs",
            # The helper Lambda's own logs: without this they would never expire either.
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
        for construct_id, group_name in [
            ("RuntimeLogRetention", log_group_name),
            ("EvalResultsLogRetention", eval_results_log_group),
        ]:
            set_retention = cr.AwsSdkCall(
                service="CloudWatchLogs",
                action="putRetentionPolicy",
                parameters={"logGroupName": group_name, "retentionInDays": 30},
                physical_resource_id=cr.PhysicalResourceId.of(group_name),
            )
            cr.AwsCustomResource(
                self,
                construct_id,
                on_create=set_retention,
                on_update=set_retention,
                policy=cr.AwsCustomResourcePolicy.from_statements(
                    [
                        iam.PolicyStatement(
                            actions=["logs:PutRetentionPolicy"],
                            resources=[
                                f"arn:aws:logs:{self.region}:{self.account}:log-group:{group_name}"
                            ],
                        )
                    ]
                ),
                log_group=helper_logs,
                install_latest_aws_sdk=False,
            )

        # --- Token metrics -------------------------------------------------------------------
        # AgentCore publishes no token metrics; derive them from our own "agent run" log line.
        # Only the deployed runtime writes here, so local and eval runs are not counted.
        token_namespace = f"{project}/Agent"
        for metric_name, field in [
            ("InputTokens", "input_tokens"),
            ("OutputTokens", "output_tokens"),
            ("CacheReadTokens", "cache_read"),
        ]:
            metric_filter = logs.CfnMetricFilter(
                self,
                f"{metric_name}Filter",
                log_group_name=log_group_name,
                filter_pattern='{ $.message = "agent run" }',
                metric_transformations=[
                    logs.CfnMetricFilter.MetricTransformationProperty(
                        metric_namespace=token_namespace,
                        metric_name=metric_name,
                        metric_value=f"$.{field}",
                        dimensions=[
                            logs.CfnMetricFilter.DimensionProperty(key="Model", value="$.model")
                        ],
                        unit="Count",
                    )
                ],
            )
            metric_filter.add_dependency(runtime)

        def token_metric(name: str, model_id: str, period: cdk.Duration) -> cw.Metric:
            return cw.Metric(
                namespace=token_namespace,
                metric_name=name,
                dimensions_map={"Model": model_id},
                statistic="Sum",
                period=period,
                label=f"{name} {model_id.split('.')[2].split('-2025')[0]}",
            )

        def runtime_metric(name: str, statistic: str = "Sum") -> cw.Metric:
            return cw.Metric(
                namespace="AWS/Bedrock-AgentCore",
                metric_name=name,
                dimensions_map=runtime_metric_dims,
                statistic=statistic,
                period=cdk.Duration.minutes(5),
            )

        # --- Alarms --------------------------------------------------------------------------
        error_rate = cw.MathExpression(
            expression="IF(invocations > 0, 100 * (system + user) / invocations, 0)",
            using_metrics={
                "invocations": runtime_metric("Invocations"),
                "system": runtime_metric("SystemErrors"),
                "user": runtime_metric("UserErrors"),
            },
            label="Error rate (%)",
            period=cdk.Duration.minutes(5),
        )
        error_alarm = cw.Alarm(
            self,
            "AgentErrorRateAlarm",
            alarm_description="Agent runtime error rate above 5% for 15 minutes",
            metric=error_rate,
            threshold=5,
            evaluation_periods=3,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )
        day = cdk.Duration.days(1)
        daily_tokens = cw.MathExpression(
            expression="SUM([in_s, out_s, in_l, out_l])",
            using_metrics={
                "in_s": token_metric("InputTokens", models["MODEL_SMALL"], day),
                "out_s": token_metric("OutputTokens", models["MODEL_SMALL"], day),
                "in_l": token_metric("InputTokens", models["MODEL_LARGE"], day),
                "out_l": token_metric("OutputTokens", models["MODEL_LARGE"], day),
            },
            label="Tokens per day",
            period=day,
        )
        # Token count, not dollars: ~3,000 tokens per smoke run, so 2M is ~700 runs in a day.
        token_alarm = cw.Alarm(
            self,
            "DailyTokenAlarm",
            alarm_description="Agent used more than 2M Bedrock tokens in a day",
            metric=daily_tokens,
            threshold=2_000_000,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )
        for alarm in (error_alarm, token_alarm):
            alarm.add_alarm_action(cw_actions.SnsAction(alerts_topic))

        # --- Dashboard -----------------------------------------------------------------------
        dashboard = cw.Dashboard(self, "AgentDashboard", dashboard_name=f"{project}-agent")
        dashboard.add_widgets(
            cw.GraphWidget(
                title="Agent invocations and errors",
                left=[
                    runtime_metric("Invocations"),
                    runtime_metric("SystemErrors"),
                    runtime_metric("UserErrors"),
                ],
                width=12,
            ),
            cw.GraphWidget(
                title="Agent latency (ms)",
                left=[runtime_metric("Latency", "p50"), runtime_metric("Latency", "p99")],
                width=12,
            ),
        )
        dashboard.add_widgets(
            cw.GraphWidget(
                title="Gateway tool time: checkDatabaseHealth (ms)",
                left=[
                    cw.Metric(
                        namespace="AWS/Bedrock-AgentCore",
                        metric_name="TargetExecutionTime",
                        dimensions_map={
                            "Operation": "InvokeGateway",
                            "Method": "tools/call",
                            "Protocol": "MCP",
                            "Name": "backend___checkDatabaseHealth",
                        },
                        statistic=stat,
                        period=cdk.Duration.minutes(5),
                    )
                    for stat in ("p50", "Maximum")
                ],
                width=12,
            ),
            cw.GraphWidget(
                title="Tokens per day",
                left=[
                    token_metric(name, model_id, day)
                    for model_id in (models["MODEL_SMALL"], models["MODEL_LARGE"])
                    for name in ("InputTokens", "OutputTokens", "CacheReadTokens")
                ],
                width=12,
                stacked=True,
            ),
        )
        dashboard.add_widgets(cw.AlarmStatusWidget(alarms=[error_alarm, token_alarm], width=24))

        cdk.CfnOutput(self, "AgentRuntimeArn", value=runtime.attr_agent_runtime_arn)
        cdk.CfnOutput(self, "AgentLogGroup", value=log_group_name)
        cdk.CfnOutput(self, "GatewayUrl", value=gateway.attr_gateway_url)
        cdk.CfnOutput(self, "GuardrailId", value=guardrail.attr_guardrail_id)
        cdk.CfnOutput(self, "GuardrailVersion", value=guardrail_version.attr_version)
        cdk.CfnOutput(self, "EvaluationResultsLogGroup", value=eval_results_log_group)
        cdk.CfnOutput(self, "DashboardName", value=dashboard.dashboard_name)
