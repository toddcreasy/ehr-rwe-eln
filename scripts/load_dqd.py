"""Store a DataQualityDashboard run (the JSON r/run_dqd.R writes) in the dq schema.

Usage: uv run python scripts/load_dqd.py data/hades/dqd/<file>.json --target aurora|local

aurora: the deployed app's database, through the RDS Data API (SQL over HTTPS with your AWS login;
the cluster and secret ARNs come from the foundation stack's Terraform outputs). local: the
Compose Postgres from .env. The /dq/ page shows the newest run.
"""

import argparse
import json
import subprocess
from pathlib import Path

import boto3

from ehr_rwe_eln.config import DatabaseSettings, LakeSettings
from ehr_rwe_eln.dq.dqd import read_dqd, save_dqd, save_dqd_data_api

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--target", choices=["aurora", "local"], required=True)
    args = parser.parse_args()

    run = read_dqd(args.path)
    o = run.overview
    print(
        f"{len(run.results):,} checks: {o['countOverallFailed']} failed,"
        f" {o['countNotApplicable']} not applicable, {o['countIsError']} errors;"
        f" pass rate {o['strictPercentPassed']}% (DQD's {o['percentPassed']}%)"
    )
    if args.target == "local":
        with DatabaseSettings().connect() as con:
            run_id = save_dqd(con, run)
            con.commit()
    else:
        out = subprocess.run(  # noqa: S603  (fixed command)
            ["terraform", f"-chdir={ROOT / 'infra/terraform/foundation'}", "output", "-json"],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        outputs = {k: v["value"] for k, v in json.loads(out).items()}
        settings = LakeSettings()
        run_id = save_dqd_data_api(
            boto3.client("rds-data", region_name=settings.aws_region),
            outputs["aurora_cluster_arn"],
            outputs["aurora_master_secret_arn"],
            "ehr_rwe_eln",
            run,
        )
    print(f"stored as dq run {run_id} ({args.target})")


if __name__ == "__main__":
    main()
