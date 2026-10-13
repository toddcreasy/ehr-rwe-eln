from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """Model tiering: agents default to MODEL_SMALL; MODEL_LARGE is for final synthesis only."""

    # protected_namespaces=() because pydantic reserves the "model_" prefix by default.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=())

    # Each user brings their own key. Unset here, the Anthropic SDK reads ANTHROPIC_API_KEY from
    # the environment and fails with its own message if that is missing too.
    anthropic_api_key: SecretStr | None = None
    model_small: str = "claude-haiku-5-5"
    model_large: str = "claude-sonnet-5-5"
