import psycopg
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Locally these come from .env, matching docker-compose.yml."""

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

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
    """Locally these come from .env. Docker Compose adds the app service's environment."""

    log_level: str = "INFO"
    frontend_dir: str = "frontend/out"
