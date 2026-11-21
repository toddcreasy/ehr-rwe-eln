"""Write a protocol's person-period table for TrialEmulation's per-protocol estimate.

Usage: OMOP_SOURCE=staging uv run python scripts/write_person_periods.py [PROTOCOL ...]

Default: lisinopril_vs_amlodipine_ckd. Writes data/hades/trialemulation/<protocol>/
person_periods.csv and columns.json (covariate names, deviation counts), which
r/run_trialemulation.R reads with no database. OMOP_SOURCE=staging reads the staging Postgres,
identical to the lake and free; the default reads the lake through Redshift.
"""

import argparse
import json
from pathlib import Path

from ehr_rwe_eln.omop import connect_omop
from ehr_rwe_eln.tte.per_protocol import build_person_periods
from ehr_rwe_eln.tte.protocol import PROTOCOLS, load_protocol

OUT = Path(__file__).resolve().parents[1] / "data/hades/trialemulation"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("protocols", nargs="*", default=["lisinopril_vs_amlodipine_ckd"])
    args = parser.parse_args()

    omop, cdm = connect_omop()
    with omop as con:
        for name in args.protocols:
            table, description = build_person_periods(
                con, load_protocol(PROTOCOLS / f"{name}.yaml"), cdm
            )
            out = OUT / name
            out.mkdir(parents=True, exist_ok=True)
            table.to_csv(out / "person_periods.csv", index=False)
            (out / "columns.json").write_text(json.dumps(description, indent=2))
            print(f"{name}: {len(table):,} person-periods, {table['id'].nunique():,} persons")
            for key in ("persons", "stopped", "started_other_drug", "events"):
                print(f"  {key}: {description[key]}")
            print(f"  wrote {out}")


if __name__ == "__main__":
    main()
