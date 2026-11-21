import anthropic
from pydantic_settings import BaseSettings, SettingsConfigDict

# Opus 4.6 thinks only when asked; adaptive lets it decide how much. Every call sets this.
THINKING = {"type": "adaptive"}


class AgentSettings(BaseSettings):
    """Every model call in the project uses MODEL on Amazon Bedrock: Claude Opus 4.6 unless .env
    says otherwise, the newest Claude this account can call (Opus 5.5, 4.8, and 4.7 return
    AccessDenied, tested 2026-11-19)."""

    # protected_namespaces=() because pydantic reserves the "model_" prefix by default.
    model_config = SettingsConfigDict(
        env_file=".env", env_ignore_empty=True, extra="ignore", protected_namespaces=()
    )

    model: str = "us.anthropic.claude-opus-4-6-v1"
    aws_region: str = "us-east-1"
    # The Bedrock Guardrail on /api/agent (infra/terraform/app/guardrail.tf). Empty locally,
    # where no guardrail is used.
    guardrail_id: str = ""
    guardrail_version: str = ""


def claude_client() -> anthropic.AnthropicBedrock:
    """Claude on Bedrock. Credentials come from the AWS default chain: the CLI profile (SSO) on a
    laptop, the task role on ECS. No API key anywhere."""
    return anthropic.AnthropicBedrock(aws_region=AgentSettings().aws_region)
