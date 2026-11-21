"""Agent entry point. The API serves it at POST /agent; evals call invoke directly."""

import logging

from pydantic import BaseModel, Field, ValidationError

from ehr_rwe_eln.agents.config import AgentSettings
from ehr_rwe_eln.agents.workbench import BLOCKED_OUTPUT_REPLY, guardrail_check, run_agent

settings = AgentSettings()
log = logging.getLogger("ehr_rwe_eln.agents")


class AgentRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


def usage(model_id: str, responses: list) -> dict:
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
    return fields


def invoke(request: AgentRequest) -> dict:
    model_id = settings.model
    if settings.guardrail_id:
        refusal = guardrail_check(request.prompt, settings)
        if refusal is not None:
            fields = usage(model_id, []) | {"guardrail": "input_blocked"}
            log.info("agent run", extra={"fields": fields})
            return {"output": {"reply": refusal}, "usage": fields}
    try:
        responses = run_agent(model_id, request.prompt)
    except ValidationError:
        if not settings.guardrail_id:
            raise
        # The guardrail replaced the model's output. The SDK raised before returning the
        # responses, so the daily limit and the token alarm miss this run's tokens (Bedrock's
        # own InputTokenCount and OutputTokenCount metrics still have them). Rare: blocked
        # prompts stop at guardrail_check, before the model.
        fields = usage(model_id, []) | {"guardrail": "output_blocked"}
        log.warning("agent run", extra={"fields": fields})
        return {"output": {"reply": BLOCKED_OUTPUT_REPLY}, "usage": fields}

    fields = usage(model_id, responses)
    log.info("agent run", extra={"fields": fields})
    # None when the run hit MAX_MODEL_CALLS before a final reply; the tokens still count.
    parsed = responses[-1].parsed_output
    return {"output": parsed.model_dump() if parsed else None, "usage": fields}
