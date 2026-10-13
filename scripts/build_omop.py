"""Build the OMOP CDM v5.4 schema in the Compose Postgres: tables, Athena vocabularies, the
Synthea ETL, condition and drug eras, then primary keys, foreign keys, and indices.

Usage: uv run python scripts/build_omop.py [--synthea data/synthea/output/csv]

The database comes from DB_NAME (default ehr_rwe_eln). Module 4's larger population:
  DB_NAME=ehr_rwe_eln_tte uv run python scripts/build_omop.py --synthea data/synthea_20k/output/csv

Needs the Athena downloads in data/vocab/ (clinical vocabularies) and data/vocab_extra/
(Gender, Race, Ethnicity), scripts/generate_synthea.py output, and the database running
(docker compose up -d --wait).
"""

import argparse
import time
from pathlib import Path

from ehr_rwe_eln.cohort.cdm import add_constraints, create_cdm, load_vocabulary
from ehr_rwe_eln.cohort.eras import build_eras
from ehr_rwe_eln.cohort.etl import run_etl
from ehr_rwe_eln.config import DatabaseSettings

DATA = Path(__file__).resolve().parent.parent / "data"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthea", type=Path, default=DATA / "synthea" / "output" / "csv")
    args = parser.parse_args()

    con = DatabaseSettings().connect()
    if con.execute(
        "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'cdm'"
    ).fetchone():
        raise SystemExit("schema cdm already exists; drop it (DROP SCHEMA cdm CASCADE) and rerun")
    create_cdm(con)

    start = time.time()
    counts = load_vocabulary(con, DATA / "vocab", DATA / "vocab_extra")
    print(f"vocabulary loaded in {time.time() - start:.0f}s")
    for table, n in counts.items():
        print(f"  {table:<22}{n:>14,}")

    start = time.time()
    counts = run_etl(con, args.synthea)
    print(f"ETL done in {time.time() - start:.0f}s")
    for table, n in counts.items():
        print(f"  {table:<22}{n:>14,}")

    counts = build_eras(con)
    for table, n in counts.items():
        print(f"  {table:<22}{n:>14,}")

    start = time.time()
    add_constraints(con)
    print(f"keys and indices added in {time.time() - start:.0f}s")
    con.commit()


if __name__ == "__main__":
    main()
