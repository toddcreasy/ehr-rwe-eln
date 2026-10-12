"""Build data/omop.duckdb: OMOP CDM v5.4 tables, Athena vocabularies, then the Synthea ETL.

Usage: uv run python scripts/build_omop.py

Needs the Athena downloads in data/vocab/ (clinical vocabularies) and data/vocab_extra/
(Gender, Race, Ethnicity), and scripts/generate_synthea.py output.
"""

import time
from pathlib import Path

import duckdb

from ehr_rwe_eln.cohort.cdm import create_cdm, load_vocabulary
from ehr_rwe_eln.cohort.etl import run_etl

DATA = Path(__file__).resolve().parent.parent / "data"
DATABASE = DATA / "omop.duckdb"


def main() -> None:
    if DATABASE.exists():
        raise SystemExit(f"{DATABASE} already exists; move it to the trash and rerun")
    con = duckdb.connect(str(DATABASE))
    create_cdm(con)

    start = time.time()
    counts = load_vocabulary(con, DATA / "vocab", DATA / "vocab_extra")
    print(f"vocabulary loaded in {time.time() - start:.0f}s")
    for table, n in counts.items():
        print(f"  {table:<22}{n:>14,}")

    start = time.time()
    counts = run_etl(con, DATA / "synthea" / "output" / "csv")
    print(f"ETL done in {time.time() - start:.0f}s")
    for table, n in counts.items():
        print(f"  {table:<22}{n:>14,}")


if __name__ == "__main__":
    main()
