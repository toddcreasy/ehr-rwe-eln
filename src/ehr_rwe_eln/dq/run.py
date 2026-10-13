"""Run the data quality checks against the CDM and store the results in the dq schema."""

import time
from datetime import UTC, datetime

import psycopg
from psycopg.types.json import Jsonb

from ehr_rwe_eln.dq.checks import Check, load_checks
from ehr_rwe_eln.dq.scoring import Result, evaluate, summarize
from ehr_rwe_eln.dq.sql import check_sql


def run_checks(
    con: psycopg.Connection, checks: list[Check] | None = None, schema: str = "cdm"
) -> list[Result]:
    """Run each check and score the results. A check whose SQL fails records the error, as DQD
    does: a missing table or field is how cdmTable and cdmField fail."""
    results = []
    for check in checks if checks is not None else load_checks():
        query = check_sql(check, schema)
        started = time.perf_counter()
        violated = denominator = error = None
        try:
            with con.transaction():
                violated, denominator = con.execute(query).fetchone()
        except psycopg.Error as exc:
            error = str(exc).strip()
        results.append(
            Result(check, violated, denominator, error, time.perf_counter() - started, query)
        )
    evaluate(results)
    return results


def save_run(
    con: psycopg.Connection, results: list[Result], started_at: datetime, schema: str = "cdm"
) -> int:
    source = con.execute(
        f"SELECT cdm_source_name, cdm_release_date, vocabulary_version FROM {schema}.cdm_source"
    ).fetchone() or (None, None, None)
    run_id = con.execute(
        "INSERT INTO dq.run (started_at, finished_at, cdm_source_name, cdm_release_date,"
        " vocabulary_version, overview) VALUES (%s, %s, %s, %s, %s, %s) RETURNING run_id",
        [started_at, datetime.now(UTC), *source, Jsonb(summarize(results))],
    ).fetchone()[0]
    with con.cursor() as cur:
        cur.executemany(
            "INSERT INTO dq.result VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
            " %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    run_id,
                    r.check.check_id,
                    r.check.name,
                    r.check.level,
                    r.check.description,
                    r.check.table,
                    r.check.field,
                    r.check.category,
                    r.check.subcategory,
                    r.check.context,
                    r.check.severity,
                    r.num_violated_rows,
                    r.pct_violated_rows,
                    r.num_denominator_rows,
                    r.check.threshold,
                    r.check.notes,
                    r.failed,
                    r.passed,
                    r.is_error,
                    r.not_applicable,
                    r.not_applicable_reason,
                    r.error,
                    r.execution_seconds,
                    r.query_text,
                    r.check.concept_id,
                    r.check.unit_concept_id,
                )
                for r in results
            ],
        )
    return run_id
