from typing import Literal

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


class LakeSettings(BaseSettings):
    """The S3 Tables lake that serves OMOP and the Redshift workgroup that queries it. Locally
    these come from .env; AWS credentials come from the AWS CLI profile, never from here."""

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

    lake_table_bucket_arn: str = ""
    # Where OMOP readers (trial emulation, synthetic data, genomics scripts) read from: the lake
    # through Redshift, or the staging Postgres the ETL builds in.
    omop_source: Literal["lake", "staging"] = "lake"
    lake_namespace: str = "cdm"
    aws_region: str = "us-east-1"
    redshift_workgroup: str = "ehr-rwe-eln"
    redshift_database: str = "ehr_rwe_eln"
    # The Glue resource link Redshift reads the lake through: awsdatacatalog.omop_cdm.<table>.
    redshift_lake_schema: str = "awsdatacatalog.omop_cdm"


class Settings(DatabaseSettings):
    """Locally these come from .env. Docker Compose adds the app service's environment."""

    log_level: str = "INFO"
    frontend_dir: str = "frontend/out"
