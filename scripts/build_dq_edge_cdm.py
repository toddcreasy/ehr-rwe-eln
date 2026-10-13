"""Build a small CDM with planted data quality problems, for comparing module 7 with DQD on the
scoring paths the real data never reaches: errors, a missing table, failing keys, and failing
concept checks.

Usage: uv run python scripts/build_dq_edge_cdm.py

Replaces schema dq_edge in the test database. Then run scripts/dqd_reference.R and
scripts/compare_dqd.py against ehr_rwe_eln_test, dq_edge (see docs/dqd_comparison.md).
"""

from ehr_rwe_eln.cohort.cdm import create_cdm
from ehr_rwe_eln.config import DatabaseSettings

PLANTED = [
    # Duplicate person_id, and a birth year below DQD's 1850 floor.
    "INSERT INTO dq_edge.person (person_id, gender_concept_id, year_of_birth, race_concept_id,"
    " ethnicity_concept_id) VALUES (1, 8507, 1980, 0, 0), (1, 8532, 1849, 0, 0)",
    # An exposure that ends before it starts, and one for a person who does not exist.
    "INSERT INTO dq_edge.drug_exposure (drug_exposure_id, person_id, drug_concept_id,"
    " drug_exposure_start_date, drug_exposure_end_date, drug_type_concept_id) VALUES"
    " (1, 1, 0, DATE '2020-03-01', DATE '2020-02-01', 32817),"
    " (2, 9, 0, DATE '2020-01-01', DATE '2020-01-05', 32817)",
    # A mapped condition with no condition_era, a female-only condition (192367, dysplasia of
    # cervix) on a male, and a descendant of the male-only finding 4090861 on a female.
    "INSERT INTO dq_edge.person (person_id, gender_concept_id, year_of_birth, race_concept_id,"
    " ethnicity_concept_id) VALUES (2, 8532, 1990, 0, 0)",
    "INSERT INTO dq_edge.concept_ancestor VALUES (4090861, 900000001, 1, 1)",
    "INSERT INTO dq_edge.condition_occurrence (condition_occurrence_id, person_id,"
    " condition_concept_id, condition_start_date, condition_type_concept_id) VALUES"
    " (1, 1, 4000001, DATE '2020-01-01', 32817), (2, 1, 192367, DATE '2020-01-01', 32817),"
    " (3, 2, 900000001, DATE '2020-01-01', 32817)",
    # Basophils (3006315) in a unit outside DQD's list, and one in a listed unit (8784).
    "INSERT INTO dq_edge.measurement (measurement_id, person_id, measurement_concept_id,"
    " measurement_date, measurement_type_concept_id, unit_concept_id) VALUES"
    " (1, 1, 3006315, DATE '2020-01-01', 32817, 8582),"
    " (2, 2, 3006315, DATE '2020-01-01', 32817, 8784)",
    # DQD will not run without a cdm_source row.
    "INSERT INTO dq_edge.cdm_source VALUES ('dq edge', 'dq_edge', 'test', NULL, NULL, NULL,"
    " DATE '2026-01-01', CURRENT_DATE, '5.4', 902983, 'none')",
    # A missing table. A missing column is left out: DQD v2.9.0 stops on one.
    "DROP TABLE dq_edge.specimen",
]


def main() -> None:
    with DatabaseSettings().connect(dbname="ehr_rwe_eln_test") as con:
        con.execute("DROP SCHEMA IF EXISTS dq_edge CASCADE")
        create_cdm(con, schema="dq_edge")
        for statement in PLANTED:
            con.execute(statement)
    print("built schema dq_edge in ehr_rwe_eln_test")


if __name__ == "__main__":
    main()
