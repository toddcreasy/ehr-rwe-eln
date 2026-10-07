from datetime import UTC, datetime

from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from pydantic import BaseModel, Field
from strands import Agent, tool
from strands.models import BedrockModel
from strands.models.bedrock import CacheConfig
from strands.tools.mcp import MCPClient

SYSTEM_PROMPT = (
    "You are the platform check agent for ehr-rwe-eln, a research project on synthetic data. "
    "Answer in one or two sentences. Call a tool only when the question needs it; for greetings "
    "and general questions answer directly and leave utc_time empty. If the user asks about the "
    "date or time, call the "
    "current_time tool and use its result; never guess the time. If the user asks whether the "
    "database is reachable or healthy, call the checkDatabaseHealth tool and report its result. "
    "Never give medical or clinical advice: if asked for a diagnosis, treatment or dosing, decline "
    "and say this is a research tool on synthetic data."
)


class HelloReply(BaseModel):
    reply: str = Field(description="One or two sentence answer to the user.")
    utc_time: str | None = Field(
        default=None, description="ISO 8601 UTC time from the current_time tool, if called."
    )


@tool
def current_time() -> str:
    """Return the current UTC date and time in ISO 8601 format."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def build_agent(model_id: str, region: str, gateway_url: str | None = None) -> Agent:
    model = BedrockModel(
        model_id=model_id,
        region_name=region,
        # Explicit cap: unset, Bedrock reserves the model's maximum output against our quota.
        max_tokens=1024,
        # Caches the system prompt and tool definitions once they exceed the model's minimum
        # (4,096 tokens for Haiku 4.5). Below that Bedrock ignores it, so expect cache_read 0 here.
        cache_config=CacheConfig(strategy="auto"),
    )
    tools = [current_time]
    if gateway_url:
        # Gateway tools over MCP. Requests are SigV4-signed with whatever AWS credentials are
        # active: the runtime's execution role when deployed, your own credentials locally.
        tools.append(
            MCPClient(
                lambda: aws_iam_streamablehttp_client(
                    endpoint=gateway_url, aws_service="bedrock-agentcore", aws_region=region
                )
            )
        )
    # callback_handler=None stops Strands printing the streamed reply to stdout.
    return Agent(model=model, system_prompt=SYSTEM_PROMPT, tools=tools, callback_handler=None)
