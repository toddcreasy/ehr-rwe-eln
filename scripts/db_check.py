"""Round-trip check against Aurora through the RDS Data API: pgvector insert + cosine similarity.

Runs in one transaction on a temp table and rolls back, so it leaves nothing behind.

    uv run python scripts/db_check.py
"""

import json
import time

import boto3
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

    started = time.monotonic()
    for attempt in range(12):
        try:
            tx = data.begin_transaction(**target)["transactionId"]
            break
        except data.exceptions.DatabaseResumingException:
            print(f"cluster resuming from pause, retry {attempt + 1}")
            time.sleep(5)
    else:
        raise TimeoutError("cluster did not resume")
    print(f"connected in {time.monotonic() - started:.1f}s via {cluster_arn}")

    def query(sql: str) -> list[dict]:
        result = data.execute_statement(sql=sql, transactionId=tx, formatRecordsAs="JSON", **target)
        return json.loads(result.get("formattedRecords", "[]"))

    try:
        print(query("SELECT version() AS server")[0]["server"])
        print(query("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
        query("CREATE TEMP TABLE db_check (id int, label text, embedding vector(3))")
        query(
            "INSERT INTO db_check VALUES "
            "(1, 'same direction', '[2,4,6]'), "
            "(2, 'close', '[1,2,3.5]'), "
            "(3, 'opposite', '[-1,-2,-3]')"
        )
        rows = query(
            "SELECT id, label, 1 - (embedding <=> '[1,2,3]') AS cosine_similarity "
            "FROM db_check ORDER BY embedding <=> '[1,2,3]'"
        )
        print("query vector [1,2,3]:")
        for row in rows:
            print(
                f"  {row['id']} {row['label']:<15} cosine_similarity={row['cosine_similarity']:.4f}"
            )
    finally:
        data.rollback_transaction(
            resourceArn=cluster_arn, secretArn=settings.database_secret_arn, transactionId=tx
        )


if __name__ == "__main__":
    main()
