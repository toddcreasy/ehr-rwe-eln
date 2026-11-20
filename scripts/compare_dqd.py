"""Compare module 4's data quality checks with OHDSI DataQualityDashboard on the same CDM.

Usage: uv run python scripts/compare_dqd.py [--database DB] [--schema SCHEMA] [--reference FILE]

Needs the JSON from scripts/dqd_reference.R, run against the same database and schema. Runs
our checks fresh (nothing is stored) and compares every check by checkId, then the Overview.
See docs/dqd_comparison.md.
"""

import argparse
import json
import math
from pathlib import Path

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.dq.run import run_checks
from ehr_rwe_eln.dq.scoring import summarize

RESULTS = Path(__file__).resolve().parent.parent / "data" / "dqd"

# DQD's JSON key, and how to read the same value from one of our results.
FIELDS = {
    "numViolatedRows": lambda r: r.num_violated_rows,
    "numDenominatorRows": lambda r: r.num_denominator_rows,
    # DQD writes its JSON with jsonlite::toJSON, which keeps 4 decimals; it scores unrounded.
    "pctViolatedRows": lambda r: (
        None if r.pct_violated_rows is None else round(r.pct_violated_rows, 4)
    ),
    "thresholdValue": lambda r: r.check.threshold,
    "failed": lambda r: int(r.failed),
    "passed": lambda r: int(r.passed),
    "isError": lambda r: int(r.is_error),
    "notApplicable": lambda r: int(r.not_applicable),
    "notApplicableReason": lambda r: r.not_applicable_reason,
    "checkDescription": lambda r: r.check.description,
    "category": lambda r: r.check.category,
    "subcategory": lambda r: r.check.subcategory,
    "context": lambda r: r.check.context,
}


def same(ours, theirs) -> bool:
    if isinstance(ours, float) or isinstance(theirs, float):
        return ours is not None and theirs is not None and math.isclose(ours, theirs, rel_tol=1e-9)
    # DQD's JSON trims trailing spaces from descriptions; the CSV text keeps them.
    if isinstance(ours, str) and isinstance(theirs, str):
        return ours.strip() == theirs.strip()
    return ours == theirs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="ehr_rwe_eln")
    parser.add_argument("--schema", default="cdm")
    parser.add_argument("--reference", default="dqd-results.json")
    args = parser.parse_args()

    reference = json.loads((RESULTS / args.reference).read_text())
    theirs = {r["checkId"]: r for r in reference["CheckResults"]}
    with DatabaseSettings().connect(dbname=args.database) as con:
        ours = {r.check.check_id: r for r in run_checks(con, schema=args.schema)}
        con.rollback()

    print(f"checks: ours {len(ours):,}, DQD {len(theirs):,}")
    print(f"  only ours: {sorted(set(ours) - set(theirs))}")
    print(f"  only DQD:  {sorted(set(theirs) - set(ours))}")

    shared = sorted(set(ours) & set(theirs))
    differences = {}
    for check_id in shared:
        for key, read in FIELDS.items():
            if not same(read(ours[check_id]), theirs[check_id].get(key)):
                differences.setdefault(key, []).append(check_id)
    print(f"\nper-check fields, {len(shared):,} shared checks:")
    for key, read in FIELDS.items():
        found = differences.get(key, [])
        print(f"  {key:<22} {len(found):>5} differ")
        for check_id in found[:5]:
            mine, dqd = read(ours[check_id]), theirs[check_id].get(key)
            print(f"      {check_id}: ours {mine!r}, DQD {dqd!r}")

    overview = summarize(list(ours.values()))
    print("\nOverview:")
    for key, value in reference["Overview"].items():
        value = value[0]
        mark = "" if same(overview[key], value) else "   <- differs"
        print(f"  {key:<26} ours {overview[key]!s:>8}  DQD {value!s:>8}{mark}")


if __name__ == "__main__":
    main()
