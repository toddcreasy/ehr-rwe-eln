from datetime import UTC, datetime

import psycopg
from pydantic import BaseModel, Field
from strands import Agent, tool
from strands.models import CacheConfig
from strands.models.anthropic import AnthropicModel

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


@tool
def current_time() -> str:
    """Return the current UTC date and time in ISO 8601 format."""
    return datetime.now(UTC).isoformat(timespec="seconds")


@tool
def check_database_health() -> str:
    """Check whether the project's Postgres database is reachable."""
    try:
        with DatabaseSettings().connect(connect_timeout=5) as con:
            con.execute("SELECT 1")
    except psycopg.OperationalError:
        return "unreachable"
    return "reachable"


def build_agent(model_id: str, api_key: str | None = None) -> Agent:
    model = AnthropicModel(
        client_args={"api_key": api_key} if api_key else None,
        model_id=model_id,
        max_tokens=1024,
        # Caches the system prompt and tool definitions once they exceed the model's minimum
        # cacheable length. This prompt is below it, so expect cache_read 0 here.
        cache_config=CacheConfig(strategy="auto"),
    )
    tools = [current_time, check_database_health]
    # callback_handler=None stops Strands printing the streamed reply to stdout.
    return Agent(model=model, system_prompt=SYSTEM_PROMPT, tools=tools, callback_handler=None)
