"""Write trial emulation protocols' cohorts to the OHDSI cohort table that HADES reads.

Usage: uv run python scripts/write_cohorts.py [PROTOCOL ...]

Default: the two lisinopril protocols (the metformin ones are not estimable). Reads OMOP from
the lake and writes results.cohort in Redshift's own storage (OMOP_SOURCE=staging writes the
staging Postgres instead). The cohort IDs and names go to data/hades/cohortmethod/cohorts.json,
which r/run_cohortmethod.R reads.
"""

import argparse
import json
from pathlib import Path

from ehr_rwe_eln.omop import connect_omop
from ehr_rwe_eln.tte.ohdsi import write_cohorts
from ehr_rwe_eln.tte.protocol import PROTOCOLS, load_protocol

OUT = Path(__file__).resolve().parents[1] / "data/hades/cohortmethod/cohorts.json"
DEFAULT = ["lisinopril_vs_amlodipine_ckd", "lisinopril_vs_amlodipine_mi"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("protocols", nargs="*", default=DEFAULT)
    args = parser.parse_args()

    written = []
    omop, cdm = connect_omop()
    with omop as con:
        for name in args.protocols:
            ids = write_cohorts(con, load_protocol(PROTOCOLS / f"{name}.yaml"), cdm)
            if hasattr(con, "commit"):
                con.commit()
            written.append(ids)
            print(f"{name}:")
            for key in ("treatment", "comparator", "outcome"):
                entry = ids[key]
                print(f"  {entry['id']:>5}  {entry['persons']:>6,}  {key}: {entry['name']}")
            for entry in ids["negative_controls"]:
                print(
                    f"  {entry['id']:>5}  {entry['persons']:>6,}  negative control: {entry['name']}"
                )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(written, indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
