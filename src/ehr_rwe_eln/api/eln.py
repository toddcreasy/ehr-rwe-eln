from contextlib import AbstractContextManager

import psycopg
from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row

from ehr_rwe_eln.config import DB_CONNECT_TIMEOUT_S, DatabaseSettings

router = APIRouter(prefix="/eln")

SUMMARY_SQL = """
SELECT (SELECT count(*) FROM eln.subject) AS subjects,
       (SELECT count(*) FROM eln.entry) AS entries,
       count(*) FILTER (WHERE x.extraction IS NOT NULL) AS extracted,
       count(*) FILTER (WHERE x.error IS NOT NULL) AS failed,
       coalesce(sum(jsonb_array_length(x.extraction -> 'samples')), 0) AS samples,
       coalesce(sum(jsonb_array_length(x.extraction -> 'results')), 0) AS results,
       array_remove(array_agg(DISTINCT x.model), NULL) AS models
FROM eln.extraction x
"""

ENTRIES_SQL = """
SELECT e.entry_id, e.title, e.author, e.created,
       CASE WHEN x.extraction IS NOT NULL THEN 'extracted'
            WHEN x.error IS NOT NULL THEN 'failed' ELSE 'pending' END AS status,
       jsonb_array_length(x.extraction -> 'samples') AS samples,
       jsonb_array_length(x.extraction -> 'results') AS results
FROM eln.entry e LEFT JOIN eln.extraction x USING (entry_id)
"""


def connect() -> AbstractContextManager[psycopg.Connection]:
    return DatabaseSettings().connect(connect_timeout=DB_CONNECT_TIMEOUT_S, row_factory=dict_row)


@router.get("/summary")
def summary() -> dict:
    with connect() as con:
        return con.execute(SUMMARY_SQL).fetchone()


@router.get("/entries")
def entries() -> list[dict]:
    with connect() as con:
        return con.execute(ENTRIES_SQL + " ORDER BY e.entry_id").fetchall()


@router.get("/entries/{entry_id}")
def entry(entry_id: str) -> dict:
    with connect() as con:
        found = con.execute(
            "SELECT e.entry_id, e.title, e.author, e.created, e.body, x.model, x.extracted_at,"
            " x.extraction, x.error"
            " FROM eln.entry e LEFT JOIN eln.extraction x USING (entry_id)"
            " WHERE e.entry_id = %s",
            [entry_id],
        ).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail=f"no ELN entry {entry_id}")
        # Which subject codes in the extraction resolve to an OMOP person. Only the yes or no
        # leaves the database: the person_id is the re-identification key.
        codes = sorted({s["subject_id"] for s in (found["extraction"] or {}).get("samples", [])})
        linked = {
            r["subject_id"]
            for r in con.execute(
                "SELECT subject_id FROM eln.subject WHERE subject_id = ANY(%s)", [codes]
            ).fetchall()
        }
    return {**found, "subjects": [{"subject_id": c, "linked": c in linked} for c in codes]}
