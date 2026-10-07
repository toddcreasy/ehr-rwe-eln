import os

import aws_cdk as cdk
from stacks.ops_stack import OpsStack

app = cdk.App()

project = app.node.get_context("project")
env_name = app.node.get_context("env")

cdk.Tags.of(app).add("project", project)
cdk.Tags.of(app).add("env", env_name)
cdk.Tags.of(app).add("managed-by", "cdk")

env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="us-east-1")

# Prefixed stack names: other projects in this account already own the bare names.
OpsStack(app, "OpsStack", stack_name=f"{project}-OpsStack", env=env)

app.synth()
