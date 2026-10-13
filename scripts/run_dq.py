"""Run the data quality checks against the CDM and store the run in the dq schema.

Usage: uv run python scripts/run_dq.py

Needs the CDM built (scripts/build_omop.py) and migrations applied (uv run alembic upgrade head).
"""

from datetime import UTC, datetime

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.dq.run import run_checks, save_run
from ehr_rwe_eln.dq.scoring import summarize


def main() -> None:
    con = DatabaseSettings().connect()
    started_at = datetime.now(UTC)
    results = run_checks(con)
    run_id = save_run(con, results, started_at)
    con.commit()

    overview = summarize(results)
    print(f"run {run_id}: {overview['countTotal']} checks")
    print(f"  failed          {overview['countOverallFailed']:>6}")
    print(f"  errors          {overview['countIsError']:>6}")
    print(f"  not applicable  {overview['countNotApplicable']:>6}")
    print(f"  DQD pass rate   {overview['percentPassed']:>6}%  (counts not applicable as passed)")
    print(f"  strict          {overview['strictPercentPassed']:>6}%  (applicable checks only)")
    print("\nfailed checks:")
    for r in sorted(results, key=lambda r: -(r.pct_violated_rows or 0)):
        if r.failed:
            print(
                f"  {r.check.check_id:<70} {r.num_violated_rows:>9,} of"
                f" {r.num_denominator_rows:>9,}  threshold {r.check.threshold or 0:g}%"
            )


if __name__ == "__main__":
    main()
