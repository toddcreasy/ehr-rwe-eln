"""Agent entry point. The API serves it at POST /agent; evals call invoke directly."""

import logging

from pydantic import BaseModel, Field

from ehr_rwe_eln.agents.config import AgentSettings
from ehr_rwe_eln.agents.hello import run_agent

settings = AgentSettings()
log = logging.getLogger("ehr_rwe_eln.agents")


class AgentRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


def invoke(request: AgentRequest) -> dict:
    model_id = settings.model
    responses = run_agent(model_id, request.prompt)
    tools_called = [
        block.name
        for response in responses
        for block in response.content
        if block.type == "tool_use"
    ]

    fields = {
        "model": model_id,
        "input_tokens": sum(r.usage.input_tokens for r in responses),
        "output_tokens": sum(r.usage.output_tokens for r in responses),
        "cache_read": sum(r.usage.cache_read_input_tokens or 0 for r in responses),
        "cache_write": sum(r.usage.cache_creation_input_tokens or 0 for r in responses),
        "model_calls": len(responses),
        "tools_called": tools_called,
    }
    # Everything the call billed, cache reads and writes included: the daily limit and the
    # CloudWatch token alarm both count this.
    fields["total_tokens"] = (
        fields["input_tokens"]
        + fields["output_tokens"]
        + fields["cache_read"]
        + fields["cache_write"]
    )
    log.info("agent run", extra={"fields": fields})
    return {"output": responses[-1].parsed_output.model_dump(), "usage": fields}
