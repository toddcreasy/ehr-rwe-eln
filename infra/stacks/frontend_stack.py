import aws_cdk as cdk
from aws_cdk import aws_amplify as amplify
from constructs import Construct


class FrontendStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, api_endpoint: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        project = self.node.get_context("project")

        # No repository: a Git-backed app needs a stored GitHub token. Builds are uploaded
        # instead with scripts/deploy_frontend.py.
        app = amplify.CfnApp(
            self,
            "WebApp",
            name=project,
            platform="WEB",
            custom_rules=[
                # 200 = proxy, not redirect: the browser stays same-origin, so no CORS.
                amplify.CfnApp.CustomRuleProperty(
                    source="/api/<*>", target=f"https://{api_endpoint}/<*>", status="200"
                ),
            ],
        )
        branch = amplify.CfnBranch(self, "MainBranch", app_id=app.attr_app_id, branch_name="main")

        cdk.CfnOutput(self, "AmplifyAppId", value=app.attr_app_id)
        cdk.CfnOutput(
            self, "WebUrl", value=f"https://{branch.branch_name}.{app.attr_default_domain}"
        )
