from datetime import UTC, datetime

from pydantic import BaseModel, Field
from strands import Agent, tool
from strands.models import BedrockModel
from strands.models.bedrock import CacheConfig

SYSTEM_PROMPT = (
    "You are the platform check agent for ehr-rwe-eln, a research project on synthetic data. "
    "Answer in one or two sentences. If the user asks about the date or time, call the "
    "current_time tool and use its result; never guess the time."
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


def build_agent(model_id: str, region: str) -> Agent:
    model = BedrockModel(
        model_id=model_id,
        region_name=region,
        # Explicit cap: unset, Bedrock reserves the model's maximum output against our quota.
        max_tokens=1024,
        # Caches the system prompt and tool definitions once they exceed the model's minimum
        # (4,096 tokens for Haiku 4.5). Below that Bedrock ignores it, so expect cache_read 0 here.
        cache_config=CacheConfig(strategy="auto"),
    )
    # callback_handler=None stops Strands printing the streamed reply to stdout.
    return Agent(
        model=model, system_prompt=SYSTEM_PROMPT, tools=[current_time], callback_handler=None
    )
