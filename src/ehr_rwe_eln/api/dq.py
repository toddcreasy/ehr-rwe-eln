from contextlib import AbstractContextManager

import psycopg
from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row

from ehr_rwe_eln.config import DB_CONNECT_TIMEOUT_S, DatabaseSettings

router = APIRouter(prefix="/dq")

RUNS_SQL = (
    "SELECT run_id, started_at, finished_at, cdm_source_name, cdm_release_date,"
    " vocabulary_version, overview FROM dq.run"
)
# Everything in dq.result except the SQL text, which the dashboard does not show.
RESULTS_SQL = (
    "SELECT check_id, check_name, check_level, check_description, cdm_table_name,"
    " cdm_field_name, concept_id, unit_concept_id, category, subcategory, context, severity,"
    " num_violated_rows, pct_violated_rows, num_denominator_rows, threshold_value, notes_value,"
    " failed, passed, is_error, not_applicable, not_applicable_reason, error"
    " FROM dq.result WHERE run_id = %s ORDER BY check_id"
)


def connect() -> AbstractContextManager[psycopg.Connection]:
    return DatabaseSettings().connect(connect_timeout=DB_CONNECT_TIMEOUT_S, row_factory=dict_row)


@router.get("/runs")
def runs() -> list[dict]:
    with connect() as con:
        return con.execute(RUNS_SQL + " ORDER BY run_id DESC").fetchall()


@router.get("/runs/{run_id}")
def run(run_id: int) -> dict:
    with connect() as con:
        found = con.execute(RUNS_SQL + " WHERE run_id = %s", [run_id]).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail=f"no data quality run {run_id}")
        results = con.execute(RESULTS_SQL, [run_id]).fetchall()
    return {"run": found, "results": results}
