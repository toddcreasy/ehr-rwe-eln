import os

import aws_cdk as cdk
from stacks.agent_stack import AgentStack
from stacks.backend_stack import BackendStack
from stacks.data_stack import DataStack
from stacks.ops_stack import OpsStack

app = cdk.App()

project = app.node.get_context("project")
env_name = app.node.get_context("env")

cdk.Tags.of(app).add("project", project)
cdk.Tags.of(app).add("env", env_name)
cdk.Tags.of(app).add("managed-by", "cdk")

env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="us-east-1")

# Prefixed stack names: other projects in this account already own the bare names.
ops = OpsStack(app, "OpsStack", stack_name=f"{project}-OpsStack", env=env)
data = DataStack(app, "DataStack", stack_name=f"{project}-DataStack", env=env)
backend = BackendStack(
    app,
    "BackendStack",
    stack_name=f"{project}-BackendStack",
    vpc=data.vpc,
    database=data.cluster,
    env=env,
)
AgentStack(
    app,
    "AgentStack",
    stack_name=f"{project}-AgentStack",
    api_endpoint=backend.api_endpoint,
    alerts_topic=ops.alerts_topic,
    env=env,
)

app.synth()
