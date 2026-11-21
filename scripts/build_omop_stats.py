"""Count persons and records per OMOP concept (rolled up through descendants, small counts
suppressed) and store them in omop_stats, which the agent's tools read.

Usage: OMOP_SOURCE=staging uv run python scripts/build_omop_stats.py --target aurora|local

Reads OMOP through connect_omop(): OMOP_SOURCE=staging reads the staging Postgres (identical to
the lake, and free); the default reads the lake through Redshift, one query. aurora stores the
result through the RDS Data API (the cluster and secret ARNs from the foundation stack's Terraform
outputs); local, in the Compose Postgres from .env. Rerun after the lake is republished.
"""

import argparse
import json
import subprocess
from pathlib import Path

import boto3

from ehr_rwe_eln.config import DatabaseSettings, LakeSettings
from ehr_rwe_eln.omop import connect_omop
from ehr_rwe_eln.omop_stats import build, save, save_data_api, summary

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["aurora", "local"], required=True)
    args = parser.parse_args()

    omop, cdm = connect_omop()
    with omop as con:
        record, rows = build(con, cdm)
    print(summary(record, rows))

    if args.target == "local":
        with DatabaseSettings().connect() as con:
            save(con, record, rows)
            con.commit()
    else:
        out = subprocess.run(  # noqa: S603  (fixed command)
            ["terraform", f"-chdir={ROOT / 'infra/terraform/foundation'}", "output", "-json"],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        outputs = {k: v["value"] for k, v in json.loads(out).items()}
        save_data_api(
            boto3.client("rds-data", region_name=LakeSettings().aws_region),
            outputs["aurora_cluster_arn"],
            outputs["aurora_master_secret_arn"],
            "ehr_rwe_eln",
            record,
            rows,
        )
    print(f"stored in omop_stats ({args.target})")


if __name__ == "__main__":
    main()
