"""Run extraction over many entries with the Message Batches API: half the price of single
calls, for offline jobs where an answer within the hour is fine.

Each request carries the same system prompt and Extraction schema as extract(); results come
back in any order, keyed by entry id, and each is validated against Extraction before use.
"""

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from pydantic import ValidationError

from ehr_rwe_eln.eln.extract import SYSTEM_PROMPT
from ehr_rwe_eln.eln.models import Extraction

OUTPUT_FORMAT = {
    "type": "json_schema",
    "schema": anthropic.transform_schema(Extraction.model_json_schema()),
}


def batch_requests(entries: dict[str, str], model: str) -> list[Request]:
    """One request per entry, from {entry id: body}."""
    return [
        Request(
            custom_id=entry_id,
            params=MessageCreateParamsNonStreaming(
                model=model,
                max_tokens=8192,
                system=[
                    {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
                ],
                messages=[{"role": "user", "content": body}],
                output_config={"format": OUTPUT_FORMAT},
            ),
        )
        for entry_id, body in entries.items()
    ]


def read_result(result) -> tuple[Extraction | None, str | None]:
    """(extraction, None) for a valid one, (None, error) otherwise."""
    outcome = result.result
    if outcome.type != "succeeded":
        detail = getattr(getattr(outcome, "error", None), "type", "")
        return None, f"{outcome.type} {detail}".strip()
    message = outcome.message
    if message.stop_reason != "end_turn":
        return None, f"stop_reason {message.stop_reason}"
    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        return Extraction.model_validate_json(text), None
    except ValidationError as exc:
        return None, f"invalid extraction: {exc.error_count()} errors"
