import aws_cdk as cdk
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct


class OpsStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        ctx = self.node.get_context
        project = ctx("project")

        self.alerts_topic = sns.Topic(self, "AlertsTopic", topic_name=f"{project}-alerts")
        self.alerts_topic.add_subscription(subs.EmailSubscription(ctx("alert_email")))
        self.alerts_topic.add_to_resource_policy(
            iam.PolicyStatement(
                actions=["sns:Publish"],
                principals=[iam.ServicePrincipal("budgets.amazonaws.com")],
                resources=[self.alerts_topic.topic_arn],
                conditions={"StringEquals": {"aws:SourceAccount": self.account}},
            )
        )

        budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=f"{project}-monthly",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=ctx("monthly_budget_usd"), unit="USD"
                ),
                cost_filters={"TagKeyValue": [f"user:project${project}"]},
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        comparison_operator="GREATER_THAN",
                        notification_type="ACTUAL",
                        threshold=threshold,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            address=self.alerts_topic.topic_arn, subscription_type="SNS"
                        )
                    ],
                )
                for threshold in (50, 80, 100)
            ],
        )

        provider = iam.OpenIdConnectProvider.from_open_id_connect_provider_arn(
            self,
            "GitHubOidc",
            f"arn:aws:iam::{self.account}:oidc-provider/token.actions.githubusercontent.com",
        )
        owner, repo = ctx("github_repo").split("/")
        github_role = iam.Role(
            self,
            "GitHubActionsRole",
            role_name=f"{project}-github-actions",
            max_session_duration=cdk.Duration.hours(1),
            assumed_by=iam.WebIdentityPrincipal(
                provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                    },
                    "StringLike": {
                        # main only: this role can deploy, so unmerged branches never get it.
                        "token.actions.githubusercontent.com:sub": [
                            f"repo:{owner}/{repo}:ref:refs/heads/main",
                            f"repo:{owner}@{ctx('github_owner_id')}/{repo}@{ctx('github_repo_id')}"
                            ":ref:refs/heads/main",
                        ]
                    },
                },
            ),
        )
        github_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[
                    f"arn:aws:iam::{self.account}:role/cdk-hnb659fds-*-{self.account}-{self.region}"
                ],
            )
        )
        # scripts/deploy_frontend.py reads stack outputs (pool IDs, Amplify app ID).
        github_role.add_to_policy(
            iam.PolicyStatement(
                actions=["cloudformation:DescribeStacks"],
                resources=[
                    f"arn:aws:cloudformation:{self.region}:{self.account}:stack/{project}-*/*"
                ],
            )
        )

        # Pull request checks get their own role: it can only chain into CDK's read-only lookup
        # role, so a workflow on an unmerged branch can diff but never deploy.
        diff_role = iam.Role(
            self,
            "GitHubDiffRole",
            role_name=f"{project}-github-diff",
            max_session_duration=cdk.Duration.hours(1),
            assumed_by=iam.WebIdentityPrincipal(
                provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                    },
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": [
                            f"repo:{owner}/{repo}:pull_request",
                            f"repo:{owner}@{ctx('github_owner_id')}/{repo}@{ctx('github_repo_id')}"
                            ":pull_request",
                        ]
                    },
                },
            ),
        )
        diff_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole", "sts:TagSession"],
                resources=[
                    f"arn:aws:iam::{self.account}:role/"
                    f"cdk-hnb659fds-lookup-role-{self.account}-{self.region}"
                ],
            )
        )

        cdk.CfnOutput(self, "AlertsTopicArn", value=self.alerts_topic.topic_arn)
        cdk.CfnOutput(self, "GitHubActionsRoleArn", value=github_role.role_arn)
        cdk.CfnOutput(self, "GitHubDiffRoleArn", value=diff_role.role_arn)
