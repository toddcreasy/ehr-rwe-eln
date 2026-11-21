"""Baseline covariates: what was known about each person before time zero.

Everything is measured up to the day before time zero. A covariate recorded after treatment
starts could be a result of the treatment, and adjusting for it would bias the comparison; so
could one recorded on the day itself, such as the kidney function check drawn when an ACE
inhibitor is started (2026-11-21; same window as r/run_cohortmethod.R).
"""

import pandas as pd

from ehr_rwe_eln.tte.cohort import concept_set_sql
from ehr_rwe_eln.tte.protocol import Protocol

# Rows per INSERT when loading the eligible people; keeps each statement well under the Redshift
# Data API's 100 KB limit.
CHUNK = 1000


def add_covariates(con, protocol: Protocol, table: pd.DataFrame, cdm: str = "cdm") -> pd.DataFrame:
    """Return the analysis table with male, one 0/1 column per condition covariate, and one
    column per measurement covariate (NaN when there is no value in the lookback window).
    con is a psycopg connection or a lake.RedshiftSession; cdm is the OMOP tables' prefix. The
    SQL runs unchanged on both (see tte/cohort.py)."""
    con.execute("DROP TABLE IF EXISTS tte_eligible")
    con.execute("CREATE TEMP TABLE tte_eligible (person_id bigint PRIMARY KEY, time_zero date)")
    rows = [
        f"({int(person_id)}, DATE '{time_zero.isoformat()}')"
        for person_id, time_zero in table[["person_id", "time_zero"]].itertuples(index=False)
    ]
    for i in range(0, len(rows), CHUNK):
        con.execute(f"INSERT INTO tte_eligible VALUES {', '.join(rows[i : i + CHUNK])}")

    out = table.copy()
    out["male"] = (out["gender_concept_id"] == 8507).astype(int)
    for covariate in protocol.covariates.conditions:
        concepts = concept_set_sql(covariate.conditions, cdm)
        values = dict(
            con.execute(
                f"""
                WITH concepts AS ({concepts}),
                has AS (
                    SELECT DISTINCT e.person_id
                    FROM tte_eligible e
                    JOIN {cdm}.condition_occurrence co
                      ON co.person_id = e.person_id AND co.condition_start_date < e.time_zero
                    JOIN concepts c ON c.concept_id = co.condition_concept_id
                )
                SELECT e.person_id, CASE WHEN h.person_id IS NOT NULL THEN 1 ELSE 0 END
                FROM tte_eligible e LEFT JOIN has h ON h.person_id = e.person_id
                """
            ).fetchall()
        )
        out[covariate.name] = out["person_id"].map(values)
    for covariate in protocol.covariates.measurements:
        concepts = concept_set_sql(covariate.measurements, cdm)
        values = dict(
            con.execute(
                f"""
                WITH concepts AS ({concepts}),
                ranked AS (
                    SELECT e.person_id, m.value_as_number,
                           row_number() OVER (
                               PARTITION BY e.person_id
                               ORDER BY m.measurement_date DESC, m.measurement_id DESC) AS n
                    FROM tte_eligible e
                    JOIN {cdm}.measurement m
                      ON m.person_id = e.person_id
                     AND m.measurement_date BETWEEN e.time_zero - {int(covariate.lookback_days)}
                                                AND e.time_zero - 1
                     AND m.value_as_number IS NOT NULL
                    JOIN concepts c ON c.concept_id = m.measurement_concept_id
                )
                SELECT person_id, value_as_number FROM ranked WHERE n = 1
                """
            ).fetchall()
        )
        out[covariate.name] = out["person_id"].map(values).astype(float)
    return out
