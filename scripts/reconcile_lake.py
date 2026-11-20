"""Check the lake against the staging Postgres it was published from, table by table.

Usage: uv run python scripts/reconcile_lake.py [--tables person measurement ...]

For every cdm table, runs the same fingerprint query (row count; per column the non-null count,
and the sum, total text length, or min and max date) on Postgres and, through the Redshift Data
API, on the lake. Then compares cohort sizes. Exits 1 on any difference.
"""

import argparse
import sys

from ehr_rwe_eln.cohort.lake import columns, compare, fingerprint_sql, tables
from ehr_rwe_eln.config import DatabaseSettings, LakeSettings
from ehr_rwe_eln.omop import redshift_query

COHORTS_SQL = "SELECT cohort_definition_id, count(*) FROM {} GROUP BY 1 ORDER BY 1"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tables", nargs="+", help="only these tables (default: every cdm table)")
    args = parser.parse_args()

    settings = LakeSettings()
    con = DatabaseSettings().connect()
    failed = []
    for table in args.tables or tables(con, "cdm"):
        cols = columns(con, "cdm", table)
        source_sql, labels = fingerprint_sql(f'cdm."{table}"', cols)
        lake_sql, _ = fingerprint_sql(f'{settings.redshift_lake_schema}."{table}"', cols)
        source = list(con.execute(source_sql).fetchone())
        lake = redshift_query(settings, lake_sql)[0]
        diffs = compare(labels, source, lake)
        print(
            f"  {table:<24}{source[0]:>12,} rows  {len(labels):>3} checks  "
            f"{'OK' if not diffs else f'{len(diffs)} DIFFER'}"
        )
        for line in diffs:
            print(f"      {line}")
        if diffs:
            failed.append(table)

    source = con.execute(COHORTS_SQL.format("cdm.cohort")).fetchall()
    lake = redshift_query(settings, COHORTS_SQL.format(f"{settings.redshift_lake_schema}.cohort"))
    lake = [(int(cid), int(n)) for cid, n in lake]
    print(f"  cohorts: source {source}, lake {lake}  {'OK' if source == lake else 'DIFFER'}")
    if source != lake:
        failed.append("cohort sizes")

    if failed:
        sys.exit(f"lake differs from source: {', '.join(failed)}")
    print("lake matches source")


if __name__ == "__main__":
    main()
