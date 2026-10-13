"""Baseline covariates: what was known about each person at time zero.

Everything is measured on or before time zero, never after: a covariate recorded after
treatment starts could be a result of the treatment, and adjusting for it would bias the
comparison.
"""

import pandas as pd
import psycopg

from ehr_rwe_eln.tte.cohort import concept_set_sql
from ehr_rwe_eln.tte.protocol import Protocol


def add_covariates(
    con: psycopg.Connection, protocol: Protocol, table: pd.DataFrame
) -> pd.DataFrame:
    """Return the analysis table with male, one 0/1 column per condition covariate, and one
    column per measurement covariate (NaN when there is no value in the lookback window)."""
    con.execute("DROP TABLE IF EXISTS tte_eligible")
    con.execute("CREATE TEMP TABLE tte_eligible (person_id bigint PRIMARY KEY, time_zero date)")
    with con.cursor().copy("COPY tte_eligible FROM STDIN") as copy:
        for row in table[["person_id", "time_zero"]].itertuples(index=False):
            copy.write_row(row)

    out = table.copy()
    out["male"] = (out["gender_concept_id"] == 8507).astype(int)
    for covariate in protocol.covariates.conditions:
        concepts, params = concept_set_sql(covariate.conditions)
        values = dict(
            con.execute(
                f"""
                SELECT e.person_id, EXISTS (
                    SELECT FROM cdm.condition_occurrence co
                    WHERE co.person_id = e.person_id AND co.condition_start_date <= e.time_zero
                      AND co.condition_concept_id IN ({concepts}))::integer
                FROM tte_eligible e
                """,
                params,
            ).fetchall()
        )
        out[covariate.name] = out["person_id"].map(values)
    for covariate in protocol.covariates.measurements:
        concepts, params = concept_set_sql(covariate.measurements)
        values = dict(
            con.execute(
                f"""
                SELECT DISTINCT ON (e.person_id) e.person_id, m.value_as_number
                FROM tte_eligible e
                JOIN cdm.measurement m
                  ON m.person_id = e.person_id
                 AND m.measurement_date BETWEEN e.time_zero - %s AND e.time_zero
                 AND m.value_as_number IS NOT NULL
                 AND m.measurement_concept_id IN ({concepts})
                ORDER BY e.person_id, m.measurement_date DESC, m.measurement_id DESC
                """,
                [covariate.lookback_days, *params],
            ).fetchall()
        )
        out[covariate.name] = out["person_id"].map(values).astype(float)
    return out
