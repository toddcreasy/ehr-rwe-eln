from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """Every model call in the project uses MODEL, Claude Opus 5.5 unless .env says otherwise."""

    # protected_namespaces=() because pydantic reserves the "model_" prefix by default.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", protected_namespaces=())

    # Each user brings their own key. Unset here, the Anthropic SDK reads ANTHROPIC_API_KEY from
    # the environment and fails with its own message if that is missing too.
    anthropic_api_key: SecretStr | None = None
    model: str = "claude-opus-5-5"
