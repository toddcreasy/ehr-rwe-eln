"""Invoke the deployed AgentCore agent once and print its typed output and token usage.

    uv run python scripts/agent_smoke.py ["your prompt"]

AGENT_RUNTIME_ARN comes from the AgentStack output of the same name.
"""

import json
import sys
import time
import uuid

import boto3
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    agent_runtime_arn: str
    aws_region: str = "us-east-1"


def main() -> None:
    settings = Settings()
    prompt = sys.argv[1] if len(sys.argv) > 1 else "What time is it right now in UTC?"
    client = boto3.client("bedrock-agentcore", region_name=settings.aws_region)

    # Session ids must be at least 33 characters; one session per smoke run.
    session_id = f"smoke-{uuid.uuid4()}"
    started = time.monotonic()
    response = client.invoke_agent_runtime(
        agentRuntimeArn=settings.agent_runtime_arn,
        qualifier="DEFAULT",
        runtimeSessionId=session_id,
        contentType="application/json",
        accept="application/json",
        payload=json.dumps({"prompt": prompt}).encode(),
    )
    body = json.loads(response["response"].read())
    print(f"session {session_id}, {time.monotonic() - started:.1f}s, HTTP {response['statusCode']}")
    print(json.dumps(body, indent=2))


if __name__ == "__main__":
    main()
