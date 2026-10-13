"""Build every cohort definition into cdm.cohort in the Compose Postgres.

Usage: uv run python scripts/build_cohorts.py

Run scripts/build_omop.py first. Prints each cohort's attrition table.
"""

from ehr_rwe_eln.cohort.spec import DEFINITIONS, build_cohort, load_definition
from ehr_rwe_eln.config import DatabaseSettings


def main() -> None:
    con = DatabaseSettings().connect()
    for path in sorted(DEFINITIONS.glob("*.yaml")):
        definition = load_definition(path)
        attrition = build_cohort(con, definition)
        print(f"\n{definition.id}: {definition.name}")
        for rule, persons in attrition:
            print(f"  {persons:>6,}  {rule}")
    con.commit()


if __name__ == "__main__":
    main()
