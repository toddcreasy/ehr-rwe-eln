from contextlib import AbstractContextManager

import psycopg
from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row

from ehr_rwe_eln.config import DB_CONNECT_TIMEOUT_S, DatabaseSettings

router = APIRouter(prefix="/tte")

RUNS_SQL = "SELECT run_id, started_at, finished_at, cdm_source_name, persons FROM tte.run"


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
            raise HTTPException(status_code=404, detail=f"no target trial emulation run {run_id}")
        reports = con.execute(
            "SELECT report FROM tte.report WHERE run_id = %s ORDER BY protocol_id", [run_id]
        ).fetchall()
    return {"run": found, "reports": [r["report"] for r in reports]}
