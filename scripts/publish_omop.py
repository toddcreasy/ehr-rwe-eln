"""Publish the OMOP tables from the staging Postgres (built by build_omop.py) to the S3 Tables lake.

Usage: uv run python scripts/publish_omop.py [--tables person measurement ...]

Replaces each lake table in cdm with its Postgres copy, all tables by default. Needs
LAKE_TABLE_BUCKET_ARN in .env and AWS credentials from the CLI profile (aws sso login). Check the
result with scripts/reconcile_lake.py.
"""

import argparse
import time

from ehr_rwe_eln.cohort.lake import catalog, publish_table, tables
from ehr_rwe_eln.config import DatabaseSettings, LakeSettings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tables", nargs="+", help="only these tables (default: every cdm table)")
    args = parser.parse_args()

    settings = LakeSettings()
    lake = catalog(settings)
    con = DatabaseSettings().connect()
    names = args.tables or tables(con, "cdm")

    start = time.time()
    total = 0
    for table in names:
        t = time.time()
        rows = publish_table(con, lake, settings.lake_namespace, "cdm", table)
        con.rollback()
        total += rows
        print(f"  {table:<24}{rows:>12,}  {time.time() - t:>6.0f}s")
    print(f"{len(names)} tables, {total:,} rows in {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
