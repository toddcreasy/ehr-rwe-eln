from datetime import UTC, datetime

import anthropic
import psycopg
from anthropic import beta_tool
from anthropic.types.beta.parsed_beta_message import ParsedBetaMessage
from pydantic import BaseModel, Field

from ehr_rwe_eln.config import DatabaseSettings

SYSTEM_PROMPT = (
    "You are the platform check agent for ehr-rwe-eln, a research project on synthetic data. "
    "Answer in one or two sentences. Call a tool only when the question needs it; for greetings "
    "and general questions answer directly and leave utc_time empty. If the user asks about the "
    "date or time, call the "
    "current_time tool and use its result; never guess the time. If the user asks whether the "
    "database is reachable or healthy, call the check_database_health tool and report its result. "
    "If it reports the database unreachable, suggest starting it with docker compose up -d. "
    "Never give medical or clinical advice: if asked for a diagnosis, treatment or dosing, decline "
    "and say this is a research tool on synthetic data."
)


class HelloReply(BaseModel):
    reply: str = Field(description="One or two sentence answer to the user.")
    utc_time: str | None = Field(
        default=None, description="ISO 8601 UTC time from the current_time tool, if called."
    )


@beta_tool
def current_time() -> str:
    """Return the current UTC date and time in ISO 8601 format."""
    return datetime.now(UTC).isoformat(timespec="seconds")


@beta_tool
def check_database_health() -> str:
    """Check whether the project's Postgres database is reachable."""
    try:
        with DatabaseSettings().connect(connect_timeout=5) as con:
            con.execute("SELECT 1")
    except psycopg.OperationalError:
        return "unreachable"
    return "reachable"


def run_agent(
    model_id: str, prompt: str, api_key: str | None = None
) -> list[ParsedBetaMessage[HelloReply]]:
    """Run the tool loop to a final typed reply. Returns every model response, in order."""
    # api_key=None makes the SDK read ANTHROPIC_API_KEY from the environment.
    client = anthropic.Anthropic(api_key=api_key)
    runner = client.beta.messages.tool_runner(
        model=model_id,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[current_time, check_database_health],
        messages=[{"role": "user", "content": prompt}],
        output_format=HelloReply,
        # Caches the system prompt and tool definitions once they exceed the model's minimum
        # cacheable length. This prompt is below it, so expect cache_read 0 here.
        cache_control={"type": "ephemeral"},
    )
    return list(runner)
