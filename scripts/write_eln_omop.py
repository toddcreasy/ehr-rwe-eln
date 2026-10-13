"""Write the stored ELN extractions to OMOP specimen, measurement, and fact_relationship rows.

Usage: uv run python scripts/write_eln_omop.py

Run scripts/extract_eln.py first. Replaces every ELN-derived row each time, so rerun it after new
extractions land. Prints what was written and what was skipped.
"""

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.eln.omop import write_omop


def main() -> None:
    con = DatabaseSettings().connect()
    counts = write_omop(con)
    con.commit()
    for name, n in counts.items():
        print(f"  {name.replace('_', ' '):<30}{n:>8,}")


if __name__ == "__main__":
    main()
