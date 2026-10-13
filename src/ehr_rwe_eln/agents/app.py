"""Agent entry point. The API serves it at POST /agent; evals call invoke directly."""

import logging
from typing import Literal

from pydantic import BaseModel, Field

from ehr_rwe_eln.agents.config import AgentSettings
from ehr_rwe_eln.agents.hello import HelloReply, build_agent

settings = AgentSettings()
log = logging.getLogger("ehr_rwe_eln.agents")


class AgentRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    tier: Literal["small", "large"] = "small"


def invoke(request: AgentRequest) -> dict:
    model_id = settings.model_large if request.tier == "large" else settings.model_small
    api_key = settings.anthropic_api_key
    agent = build_agent(model_id, api_key.get_secret_value() if api_key else None)
    result = agent(request.prompt, structured_output_model=HelloReply)
    tools_called = [
        block["toolUse"]["name"]
        for message in agent.messages
        for block in message["content"]
        if "toolUse" in block
    ]

    usage = result.metrics.accumulated_usage
    fields = {
        "model": model_id,
        "input_tokens": usage.get("inputTokens", 0),
        "output_tokens": usage.get("outputTokens", 0),
        "cache_read": usage.get("cacheReadInputTokens", 0),
        "cache_write": usage.get("cacheWriteInputTokens", 0),
        "model_calls": result.metrics.cycle_count,
        "tools_called": tools_called,
    }
    log.info("agent run", extra={"fields": fields})
    return {"output": result.structured_output.model_dump(), "usage": fields}
