"""AgentCore Runtime entry point. Serves POST /invocations and GET /ping on port 8080.

Local run: uv run python -m ehr_rwe_eln.agents.app
"""

import logging
from typing import Literal

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from pydantic import BaseModel, Field, ValidationError
from starlette.exceptions import HTTPException

from ehr_rwe_eln.agents.config import AgentSettings
from ehr_rwe_eln.agents.hello import HelloReply, build_agent
from ehr_rwe_eln.api.log_config import configure_logging

settings = AgentSettings()
configure_logging(settings.log_level)
log = logging.getLogger("ehr_rwe_eln.agents")

app = BedrockAgentCoreApp()
# The SDK logs through its own JSON handler (with requestId); stop it also reaching ours.
app.logger.propagate = False


class AgentRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    tier: Literal["small", "large"] = "small"


@app.entrypoint
def invoke(payload: dict) -> dict:
    try:
        request = AgentRequest.model_validate(payload)
    except ValidationError as exc:
        # Caller error: 400, not the SDK's default 500.
        raise HTTPException(status_code=400, detail=exc.errors(include_url=False)) from exc
    model_id = settings.model_large if request.tier == "large" else settings.model_small

    agent = build_agent(model_id, settings.aws_region, settings.gateway_url)
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


if __name__ == "__main__":
    app.run()
