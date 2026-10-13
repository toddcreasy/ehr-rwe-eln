"""Compare row counts: our ETL (the Compose Postgres) against OHDSI ETL-Synthea (local Postgres).

Usage: uv run python scripts/compare_etl_synthea.py

Run scripts/build_omop.py and scripts/etl_synthea_reference.R first. ETL-Synthea drops rows
whose code has no standard concept, so "ours, mapped" leaves out concept_id 0 to line up.
"""

from pathlib import Path

import psycopg

from ehr_rwe_eln.config import DatabaseSettings

DATA = Path(__file__).resolve().parent.parent / "data"

# table -> concept column; None where the table has no event concept
TABLES = {
    "person": None,
    "death": None,
    "observation_period": None,
    "visit_occurrence": "visit_concept_id",
    "condition_occurrence": "condition_concept_id",
    "procedure_occurrence": "procedure_concept_id",
    "drug_exposure": "drug_concept_id",
    "measurement": "measurement_concept_id",
    "observation": "observation_concept_id",
    "device_exposure": "device_concept_id",
}


def main() -> None:
    ours = DatabaseSettings().connect()
    password = (DATA / "etl-synthea" / "pgpass").read_text().strip()
    ref = psycopg.connect(
        host="127.0.0.1", port=5433, dbname="synthea", user="postgres", password=password
    )
    print(f"{'table':<22}{'ours':>11}{'ours, mapped':>14}{'ETL-Synthea':>13}{'difference':>12}")
    for table, concept in TABLES.items():
        # Identifiers come from TABLES above.
        total = ours.execute(f"SELECT count(*) FROM cdm.{table}").fetchone()[0]  # noqa: S608
        mapped = total
        if concept:
            mapped = ours.execute(
                f"SELECT count(*) FROM cdm.{table} WHERE {concept} <> 0"  # noqa: S608
            ).fetchone()[0]
        reference_sql = f"SELECT count(*) FROM cdm_synthea.{table}"  # noqa: S608
        reference = ref.execute(reference_sql).fetchone()[0]
        print(f"{table:<22}{total:>11,}{mapped:>14,}{reference:>13,}{mapped - reference:>+12,}")


if __name__ == "__main__":
    main()
