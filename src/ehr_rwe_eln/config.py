import psycopg
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Locally these come from .env, matching docker-compose.yml."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_host: str
    db_port: int = 5432
    db_name: str = "ehr_rwe_eln"
    db_user: str = "postgres"
    db_password: SecretStr

    def connect(self, dbname: str | None = None, **kwargs) -> psycopg.Connection:
        return psycopg.connect(
            host=self.db_host,
            port=self.db_port,
            dbname=dbname or self.db_name,
            user=self.db_user,
            password=self.db_password.get_secret_value(),
            **kwargs,
        )


class Settings(DatabaseSettings):
    """Locally these come from .env. Deployed, ECS injects them from the Secrets Manager secret."""

    log_level: str = "INFO"
    cognito_user_pool_id: str
    cognito_client_id: str
