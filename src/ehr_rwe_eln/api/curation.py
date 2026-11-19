from contextlib import AbstractContextManager
from typing import Literal

import psycopg
from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.curation.rules import POINTS, classify, label

router = APIRouter(prefix="/curation")

Class = Literal[
    "Pathogenic", "Likely pathogenic", "Uncertain significance", "Likely benign", "Benign"
]

# The latest rules run of each variant set. Literature runs hold proposals, not assessments.
SETS_SQL = """
SELECT DISTINCT ON (r.variant_set) r.variant_set, r.run_id, r.created_at,
       (SELECT count(*) FROM curation.assessment a WHERE a.run_id = r.run_id) AS variants,
       (SELECT count(DISTINCT d.variant_id) FROM curation.decision d
        WHERE d.run_id = r.run_id) AS decided
FROM curation.run r
WHERE NOT r.sources ? 'literature'
ORDER BY r.variant_set, r.run_id DESC
"""

# Proposals come from the latest literature run on the same variant set.
PROPOSALS_SQL = """
SELECT p.proposal_id, p.run_id, p.criterion, p.strength, p.pmid, p.quote, p.rationale,
       p.verified, p.rejected_why
FROM curation.proposal p
WHERE p.variant_id = %(variant_id)s AND p.run_id = (SELECT max(r.run_id) FROM curation.run r
    WHERE r.variant_set = %(variant_set)s AND r.sources ? 'literature')
ORDER BY p.verified DESC, p.proposal_id
"""

VARIANTS_SQL = """
SELECT a.variant_id, a.gene, a.hgvsc, a.hgvsp, a.points, a.classification, a.expected,
       (SELECT count(*) FROM curation.proposal p
        WHERE p.variant_id = a.variant_id AND p.verified AND p.run_id = (
            SELECT max(r.run_id) FROM curation.run r
            WHERE r.variant_set = %(variant_set)s AND r.sources ? 'literature')
       ) AS proposals,
       d.classification AS decision, d.curator, d.decided_at
FROM curation.assessment a
LEFT JOIN LATERAL (
    SELECT classification, curator, decided_at FROM curation.decision d
    WHERE d.run_id = a.run_id AND d.variant_id = a.variant_id
    ORDER BY decision_id DESC LIMIT 1) d ON true
WHERE a.run_id = %(run_id)s
ORDER BY a.gene, a.variant_id
"""


def connect() -> AbstractContextManager[psycopg.Connection]:
    return DatabaseSettings().connect(connect_timeout=5, row_factory=dict_row)


class Draft(BaseModel):
    run_id: int
    variant_id: str
    accepted: list[int] = []


class Decision(Draft):
    curator: str = Field(min_length=1, max_length=100)
    classification: Class
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("curator", "note")
    @classmethod
    def strip(cls, v: str | None) -> str | None:
        return v.strip() if v else v


def _assessment(con: psycopg.Connection, run_id: int, variant_id: str) -> dict:
    found = con.execute(
        "SELECT a.*, r.variant_set, r.sources, r.created_at AS run_at"
        " FROM curation.assessment a JOIN curation.run r USING (run_id)"
        " WHERE a.run_id = %s AND a.variant_id = %s",
        [run_id, variant_id],
    ).fetchone()
    if found is None:
        raise HTTPException(status_code=404, detail=f"no variant {variant_id} in run {run_id}")
    return found


def score(con: psycopg.Connection, draft: Draft) -> dict:
    """The rules' criteria plus the accepted proposals, and what they score. A proposal can
    only add a criterion the rules did not already meet, and one criterion counts once, at the
    strongest strength accepted."""
    found = _assessment(con, draft.run_id, draft.variant_id)
    proposals = {
        p["proposal_id"]: p for p in con.execute(PROPOSALS_SQL, found).fetchall() if p["verified"]
    }
    ruled = {c["code"] for c in found["met"]}
    added: dict[str, dict] = {}
    for pid in dict.fromkeys(draft.accepted):
        p = proposals.get(pid)
        if p is None:
            raise HTTPException(
                status_code=422,
                detail=f"proposal {pid} is not a verified proposal for this variant",
            )
        if p["criterion"] in ruled:
            raise HTTPException(
                status_code=422, detail=f"{p['criterion']} is already met by the rules"
            )
        held = added.get(p["criterion"])
        if held is None or POINTS[p["strength"]] > POINTS[held["strength"]]:
            added[p["criterion"]] = {
                "code": p["criterion"],
                "label": label(p["criterion"], p["strength"]),
                "strength": p["strength"],
                "reason": f"PMID {p['pmid']}: {p['quote']}",
                "proposal_id": pid,
            }
    criteria = found["met"] + list(added.values())
    return {"criteria": criteria, **classify(criteria)}


@router.get("/sets")
def sets() -> list[dict]:
    with connect() as con:
        return con.execute(SETS_SQL).fetchall()


@router.get("/runs/{run_id}/variants")
def variants(run_id: int) -> list[dict]:
    with connect() as con:
        found = con.execute(
            "SELECT variant_set FROM curation.run WHERE run_id = %s", [run_id]
        ).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail=f"no run {run_id}")
        return con.execute(VARIANTS_SQL, {"run_id": run_id, **found}).fetchall()


@router.get("/runs/{run_id}/variants/{variant_id}")
def variant(run_id: int, variant_id: str) -> dict:
    with connect() as con:
        found = _assessment(con, run_id, variant_id)
        proposals = con.execute(PROPOSALS_SQL, found).fetchall()
        decisions = con.execute(
            "SELECT * FROM curation.decision WHERE run_id = %s AND variant_id = %s"
            " ORDER BY decision_id DESC",
            [run_id, variant_id],
        ).fetchall()
    return {**found, "proposals": proposals, "decisions": decisions}


@router.post("/score")
def preview(draft: Draft) -> dict:
    with connect() as con:
        return score(con, draft)


@router.post("/decisions", status_code=201)
def decide(decision: Decision) -> dict:
    if not decision.curator:
        raise HTTPException(status_code=422, detail="say who is deciding")
    with connect() as con:
        scored = score(con, decision)
        if decision.classification != scored["classification"] and not decision.note:
            raise HTTPException(
                status_code=422,
                detail=f"the criteria score {scored['classification']}; a different class"
                " needs a note saying why",
            )
        return con.execute(
            "INSERT INTO curation.decision (run_id, variant_id, curator, accepted, criteria,"
            " points, computed, classification, note) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " RETURNING *",
            [
                decision.run_id,
                decision.variant_id,
                decision.curator,
                list(dict.fromkeys(decision.accepted)),
                Jsonb(scored["criteria"]),
                scored["points"],
                scored["classification"],
                decision.classification,
                decision.note,
            ],
        ).fetchone()
