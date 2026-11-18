from contextlib import AbstractContextManager

import psycopg
from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.synth.card import render_card

router = APIRouter(prefix="/synth")

# One row per release with its headline numbers, read from the stored reports. A number is
# null when its report was not made (no holdout, no trial, or not evaluated yet).
RELEASES_SQL = """
SELECT r.release_id, r.created_at, r.spec_name, r.method, r.epsilon, r.rows,
       r.source_rows, r.holdout_rows,
       (f.report -> 'summary' ->> 'column_tvd_mean')::float AS column_tvd_mean,
       (f.report -> 'summary' ->> 'pair_tvd_mean')::float AS pair_tvd_mean,
       (f.report -> 'noise_floor' ->> 'pair_tvd_mean')::float AS pair_tvd_floor,
       (f.report -> 'utility' ->> 'tstr_auc')::float AS utility_auc,
       (f.report -> 'utility' ->> 'trtr_auc')::float AS utility_auc_real,
       (p.report -> 'membership_inference' ->> 'auc')::float AS membership_auc,
       (t.report -> 'repeated' ->> 'covers_real')::float AS trial_covers_real,
       (t.report -> 'repeated' ->> 'spurious_effect')::float AS trial_spurious
FROM synth.release r
LEFT JOIN synth.report f ON f.release_id = r.release_id AND f.kind = 'fidelity'
LEFT JOIN synth.report p ON p.release_id = r.release_id AND p.kind = 'privacy'
LEFT JOIN synth.report t ON t.release_id = r.release_id AND t.kind = 'trial'
"""

# The columns render_card reads; the release's rows stay in synth.row.
RELEASE_SQL = """
SELECT release_id, created_at, spec_name, method, epsilon, seed, spec, measurements,
       source_database, source_rows, holdout_rows, rows, code_version
FROM synth.release WHERE release_id = %s
"""


def connect() -> AbstractContextManager[psycopg.Connection]:
    return DatabaseSettings().connect(connect_timeout=5, row_factory=dict_row)


@router.get("/releases")
def releases() -> list[dict]:
    with connect() as con:
        return con.execute(RELEASES_SQL + " ORDER BY r.spec_name, r.release_id").fetchall()


@router.get("/releases/{release_id}")
def release(release_id: int) -> dict:
    with connect() as con:
        found = con.execute(RELEASE_SQL, [release_id]).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail=f"no synthetic release {release_id}")
        rows = con.execute(
            "SELECT kind, report FROM synth.report WHERE release_id = %s", [release_id]
        ).fetchall()
    return {
        "release_id": release_id,
        "card": render_card(found, {r["kind"]: r["report"] for r in rows}),
    }
