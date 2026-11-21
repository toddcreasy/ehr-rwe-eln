"""The agent's OMOP tools as plain functions on a database connection (the app's Postgres:
Aurora on AWS). Each returns a typed model; /api/agent and the MCP endpoint wrap the same
functions.

Bounded on purpose, for a public demo with no sign-in: read-only, no free-form SQL, inputs
validated here, results capped, and person counts read from omop_stats (precomputed, counts under
omop_stats.MIN_CELL never stored). Tool output goes back to the model, so it carries data only:
names and numbers, never instructions.
"""

from typing import Literal

import psycopg
from pydantic import BaseModel

from ehr_rwe_eln.omop_stats import MIN_CELL

DOMAINS = ("Condition", "Drug", "Procedure", "Measurement", "Observation", "Device")
MAX_RESULTS = 25
SUPPRESSED = f"fewer than {MIN_CELL}"


class ToolInputError(ValueError):
    """An input outside what the tool accepts; the message is safe to show the model."""


class Concept(BaseModel):
    concept_id: int
    name: str
    domain: str
    vocabulary: str
    concept_class: str
    # Persons with the concept or any descendant; None when suppressed.
    persons: int | None
    persons_display: str


def _concept(row) -> Concept:
    concept_id, name, domain, vocabulary, concept_class, persons = row
    return Concept(
        concept_id=concept_id,
        name=name,
        domain=domain,
        vocabulary=vocabulary,
        concept_class=concept_class,
        persons=persons,
        persons_display=SUPPRESSED if persons is None else f"{persons:,}",
    )


CONCEPT_COLUMNS = "concept_id, concept_name, domain_id, vocabulary_id, concept_class_id, persons"


def concept_search(
    con: psycopg.Connection, text: str, domain: str | None = None, limit: int = 10
) -> list[Concept]:
    """Concepts in the data whose name contains text (or whose ID is text), most persons first."""
    text = text.strip()
    if not 2 <= len(text) <= 100:
        raise ToolInputError("search text must be 2 to 100 characters")
    if domain is not None and domain not in DOMAINS:
        raise ToolInputError(f"domain must be one of {', '.join(DOMAINS)}")
    limit = max(1, min(int(limit), MAX_RESULTS))
    where, params = ["concept_name ILIKE %s"], ["%" + text.replace("%", r"\%") + "%"]
    if text.isdigit():
        where = ["(concept_name ILIKE %s OR concept_id = %s)"]
        params.append(int(text))
    if domain:
        where.append("domain_id = %s")
        params.append(domain)
    rows = con.execute(
        f"SELECT {CONCEPT_COLUMNS} FROM omop_stats.concept_count WHERE {' AND '.join(where)}"
        " ORDER BY persons DESC NULLS LAST, concept_name LIMIT %s",
        [*params, limit],
    ).fetchall()
    return [_concept(r) for r in rows]


def concept_count(con: psycopg.Connection, concept_id: int) -> Concept | None:
    """Persons with this concept or any descendant; None if the data never reach it."""
    row = con.execute(
        f"SELECT {CONCEPT_COLUMNS} FROM omop_stats.concept_count WHERE concept_id = %s",
        [int(concept_id)],
    ).fetchone()
    return _concept(row) if row else None


class Arm(BaseModel):
    name: str
    persons: int
    events: int


class TrialResult(BaseModel):
    protocol: str
    description: str
    treatment: str
    comparator: str
    outcome: str
    arms: list[Arm]
    not_estimable: str | None
    hazard_ratio: float | None
    hazard_ratio_95ci: tuple[float, float] | None
    crude_hazard_ratio: float | None
    largest_smd_after_weighting: float | None
    negative_controls: int
    negative_controls_excluding_1: int
    run_id: int
    run_finished_at: str


def tte_results(con: psycopg.Connection, protocol: str | None = None) -> list[TrialResult]:
    """The newest trial emulation run's results, for one protocol or all of them."""
    run = con.execute("SELECT run_id, finished_at FROM tte.run ORDER BY run_id DESC LIMIT 1")
    latest = run.fetchone()
    if latest is None:
        return []
    run_id, finished_at = latest
    rows = con.execute(
        "SELECT protocol_name, report FROM tte.report WHERE run_id = %s ORDER BY protocol_id",
        [run_id],
    ).fetchall()
    names = [name for name, _ in rows]
    if protocol is not None and protocol not in names:
        raise ToolInputError(f"protocol must be one of {', '.join(names)}")
    out = []
    for name, report in rows:
        if protocol is not None and name != protocol:
            continue
        p, survival, balance = report["protocol"], report["survival"], report["balance"]
        controls = report["negative_controls"]
        out.append(
            TrialResult(
                protocol=name,
                description=p["description"],
                treatment=p["treatment"],
                comparator=p["comparator"],
                outcome=p["outcome"],
                arms=[
                    Arm(name=a["name"], persons=a["persons"], events=a["events"])
                    for a in report["arms"]
                ],
                not_estimable=report["not_estimable"],
                hazard_ratio=survival["hazard_ratio"] if survival else None,
                hazard_ratio_95ci=tuple(survival["hazard_ratio_robust_ci"])
                if survival and survival["hazard_ratio_robust_ci"]
                else None,
                crude_hazard_ratio=survival["crude_hazard_ratio"] if survival else None,
                largest_smd_after_weighting=max(abs(b["smd_after"]) for b in balance)
                if balance
                else None,
                negative_controls=len(controls),
                negative_controls_excluding_1=sum(1 for c in controls if c["excludes_null"]),
                run_id=run_id,
                run_finished_at=finished_at.isoformat(),
            )
        )
    return out


class FailedCheck(BaseModel):
    check: str
    table: str
    field: str | None
    category: str
    pct_violated_rows: float | None
    threshold: float | None


class QualitySummary(BaseModel):
    run_id: int
    run_finished_at: str
    checks: int
    failed: int
    failed_checks: list[FailedCheck]


def dq_results(
    con: psycopg.Connection,
    table: str | None = None,
    category: Literal["Conformance", "Completeness", "Plausibility"] | None = None,
) -> QualitySummary | None:
    """The newest data quality run: how many checks failed, and which (at most MAX_RESULTS),
    optionally for one OMOP table or one Kahn category."""
    latest = con.execute(
        "SELECT run_id, finished_at FROM dq.run ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    if latest is None:
        return None
    run_id, finished_at = latest
    if table is not None and not table.replace("_", "").isalnum():
        raise ToolInputError("table must be an OMOP table name, such as measurement")
    where, params = ["run_id = %s"], [run_id]
    if table:
        where.append("lower(cdm_table_name) = lower(%s)")
        params.append(table)
    if category:
        where.append("category = %s")
        params.append(category)
    clause = " AND ".join(where)
    checks, failed = con.execute(
        f"SELECT count(*), count(*) FILTER (WHERE failed) FROM dq.result WHERE {clause}", params
    ).fetchone()
    rows = con.execute(
        "SELECT check_name, cdm_table_name, cdm_field_name, category, pct_violated_rows,"
        f" threshold_value FROM dq.result WHERE {clause} AND failed"
        " ORDER BY pct_violated_rows DESC NULLS LAST LIMIT %s",
        [*params, MAX_RESULTS],
    ).fetchall()
    return QualitySummary(
        run_id=run_id,
        run_finished_at=finished_at.isoformat(),
        checks=checks,
        failed=failed,
        failed_checks=[
            FailedCheck(
                check=r[0],
                table=r[1],
                field=r[2],
                category=r[3],
                pct_violated_rows=r[4],
                threshold=r[5],
            )
            for r in rows
        ],
    )
