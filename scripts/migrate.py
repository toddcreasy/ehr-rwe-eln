"""Apply Alembic migrations to Aurora through the RDS Data API.

The cluster has no network path from outside the VPC, so Alembic renders the
pending migrations as SQL (offline mode) and this script runs that SQL in one
Data API transaction.

    uv run python scripts/migrate.py
"""

import io
import json
import time

import boto3
from alembic import command
from alembic.config import Config
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_secret_arn: str
    aws_region: str = "us-east-1"


def main() -> None:
    settings = Settings()
    secrets = boto3.client("secretsmanager", region_name=settings.aws_region)
    rds = boto3.client("rds", region_name=settings.aws_region)
    data = boto3.client("rds-data", region_name=settings.aws_region)

    secret = json.loads(
        secrets.get_secret_value(SecretId=settings.database_secret_arn)["SecretString"]
    )
    cluster_arn = rds.describe_db_clusters(DBClusterIdentifier=secret["dbClusterIdentifier"])[
        "DBClusters"
    ][0]["DBClusterArn"]
    target = {
        "resourceArn": cluster_arn,
        "secretArn": settings.database_secret_arn,
        "database": secret["dbname"],
    }

    def execute(sql: str, **kwargs) -> dict:
        for attempt in range(12):
            try:
                return data.execute_statement(sql=sql, **target, **kwargs)
            except data.exceptions.DatabaseResumingException:
                print(f"cluster resuming from pause, retry {attempt + 1}")
                time.sleep(5)
        raise TimeoutError("cluster did not resume")

    has_table = execute("SELECT to_regclass('alembic_version') IS NOT NULL")
    current = None
    if has_table["records"][0][0]["booleanValue"]:
        rows = execute("SELECT version_num FROM alembic_version")["records"]
        current = rows[0][0]["stringValue"] if rows else None
    print(f"current revision: {current or 'none'}")

    buffer = io.StringIO()
    command.upgrade(
        Config("alembic.ini", output_buffer=buffer),
        f"{current}:head" if current else "head",
        sql=True,
    )
    statements = [
        s.strip()
        for s in buffer.getvalue().split(";\n")
        if s.strip() and s.strip() not in ("BEGIN", "COMMIT")
    ]
    statements = [
        "\n".join(line for line in s.splitlines() if not line.startswith("--")).strip()
        for s in statements
    ]
    statements = [s for s in statements if s]
    if not statements:
        print("up to date")
        return

    tx = data.begin_transaction(**target)["transactionId"]
    try:
        for sql in statements:
            print(f"> {sql.splitlines()[0]}")
            execute(sql, transactionId=tx)
    except Exception:
        data.rollback_transaction(
            resourceArn=cluster_arn, secretArn=settings.database_secret_arn, transactionId=tx
        )
        raise
    data.commit_transaction(
        resourceArn=cluster_arn, secretArn=settings.database_secret_arn, transactionId=tx
    )
    head = execute("SELECT version_num FROM alembic_version")["records"][0][0]["stringValue"]
    print(f"now at: {head}")


if __name__ == "__main__":
    main()
