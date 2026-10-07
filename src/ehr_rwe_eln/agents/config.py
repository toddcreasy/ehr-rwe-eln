from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """Model tiering: agents default to MODEL_SMALL; MODEL_LARGE is for final synthesis only."""

    # protected_namespaces=() because pydantic reserves the "model_" prefix by default.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=())

    model_small: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    model_large: str = "us.anthropic.claude-sonnet-5-5"
    aws_region: str = "us-east-1"
    # AgentCore Gateway MCP endpoint. Unset: the agent runs with local tools only.
    gateway_url: str | None = None
    log_level: str = "INFO"
