from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Locally these come from .env. Deployed, ECS injects them from the Secrets Manager secret."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_host: str
    db_port: int = 5432
    db_name: str = "ehr_rwe_eln"
    db_user: str = "postgres"
    db_password: SecretStr
    log_level: str = "INFO"
    cognito_user_pool_id: str
    cognito_client_id: str
