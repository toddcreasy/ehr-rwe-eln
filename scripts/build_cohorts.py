"""Build every cohort definition into the cohort table of data/omop.duckdb.

Usage: uv run python scripts/build_cohorts.py

Run scripts/build_omop.py first. Prints each cohort's attrition table.
"""

from pathlib import Path

import duckdb

from ehr_rwe_eln.cohort.spec import DEFINITIONS, build_cohort, load_definition

DATABASE = Path(__file__).resolve().parent.parent / "data" / "omop.duckdb"


def main() -> None:
    con = duckdb.connect(str(DATABASE))
    for path in sorted(DEFINITIONS.glob("*.yaml")):
        definition = load_definition(path)
        attrition = build_cohort(con, definition)
        print(f"\n{definition.id}: {definition.name}")
        for rule, persons in attrition:
            print(f"  {persons:>6,}  {rule}")


if __name__ == "__main__":
    main()
