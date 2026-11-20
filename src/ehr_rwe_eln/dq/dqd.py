"""Load the JSON that OHDSI's DataQualityDashboard (r/run_dqd.R) writes into the dq schema, the
tables the /dq/ page reads.

DQD's CheckResults carry the same fields as dq.result (the Python checks this replaces were
modeled on it). Two things are filled in here: severity, which the results JSON leaves out, comes
from DQD's own check descriptions (csv/, copied from DQD); and the overview gains the three fields
the page shows beyond DQD's Overview (not applicable count, error count, strict pass rate).
"""

import csv
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from ehr_rwe_eln.dq.checks import CSV

RESULT_COLUMNS = (
    "check_id",
    "check_name",
    "check_level",
    "check_description",
    "cdm_table_name",
    "cdm_field_name",
    "category",
    "subcategory",
    "context",
    "severity",
    "num_violated_rows",
    "pct_violated_rows",
    "num_denominator_rows",
    "threshold_value",
    "notes_value",
    "failed",
    "passed",
    "is_error",
    "not_applicable",
    "not_applicable_reason",
    "error",
    "execution_seconds",
    "query_text",
    "concept_id",
    "unit_concept_id",
)


@dataclass
class DqdRun:
    started_at: datetime
    finished_at: datetime
    cdm_source_name: str | None
    cdm_release_date: str | None
    vocabulary_version: str | None
    overview: dict
    results: list[dict]  # one dict per check, keyed by RESULT_COLUMNS


def _one(value):
    """DQD writes most scalars as one-element lists."""
    return value[0] if isinstance(value, list) and len(value) == 1 else value


def _timestamp(value) -> datetime:
    return datetime.strptime(_one(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def _seconds(text: str | None) -> float:
    """DQD's executionTime reads like '5.985009 secs' (or mins)."""
    match = re.match(r"([\d.]+)\s*(sec|min)", text or "")
    if not match:
        return 0.0
    return float(match.group(1)) * (60 if match.group(2) == "min" else 1)


def severities() -> dict[str, str]:
    with (CSV / "OMOP_CDMv5.4_Check_Descriptions.csv").open(encoding="utf-8-sig") as f:
        return {row["checkName"]: row["severity"] for row in csv.DictReader(f)}


def read_dqd(path: Path) -> DqdRun:
    data = json.loads(path.read_text())
    severity = severities()
    results = []
    for r in data["CheckResults"]:
        results.append(
            {
                "check_id": r["checkId"],
                "check_name": r["checkName"],
                "check_level": r["checkLevel"],
                "check_description": r["checkDescription"],
                "cdm_table_name": r["cdmTableName"],
                "cdm_field_name": r.get("cdmFieldName"),
                "category": r["category"],
                "subcategory": r.get("subcategory"),
                "context": r["context"],
                "severity": r.get("severity") or severity.get(r["checkName"], ""),
                "num_violated_rows": r.get("numViolatedRows"),
                "pct_violated_rows": r.get("pctViolatedRows"),
                "num_denominator_rows": r.get("numDenominatorRows"),
                "threshold_value": r.get("thresholdValue"),
                "notes_value": r.get("notesValue"),
                "failed": bool(r["failed"]),
                "passed": bool(r["passed"]),
                "is_error": bool(r["isError"]),
                "not_applicable": bool(r["notApplicable"]),
                "not_applicable_reason": r.get("notApplicableReason"),
                "error": r.get("error"),
                "execution_seconds": _seconds(r.get("executionTime")),
                "query_text": r.get("queryText", ""),
                "concept_id": str(r["conceptId"]) if r.get("conceptId") is not None else None,
                "unit_concept_id": (
                    str(r["unitConceptId"]) if r.get("unitConceptId") is not None else None
                ),
            }
        )
    overview = {k: _one(v) for k, v in data["Overview"].items()}
    applicable = [r for r in results if not r["not_applicable"]]
    overview["countNotApplicable"] = len(results) - len(applicable)
    overview["countIsError"] = sum(r["is_error"] for r in results)
    overview["strictPercentPassed"] = (
        round(sum(r["passed"] for r in applicable) / len(applicable) * 100, 2)
        if applicable
        else None
    )
    metadata = data["Metadata"][0] if data.get("Metadata") else {}
    return DqdRun(
        started_at=_timestamp(data["startTimestamp"]),
        finished_at=_timestamp(data["endTimestamp"]),
        cdm_source_name=metadata.get("cdmSourceName") or None,
        cdm_release_date=metadata.get("cdmReleaseDate") or None,
        vocabulary_version=metadata.get("vocabularyVersion") or None,
        overview=overview,
        results=results,
    )


RUN_SQL = (
    "INSERT INTO dq.run (started_at, finished_at, cdm_source_name, cdm_release_date,"
    " vocabulary_version, overview) VALUES (%s, %s, %s, %s, %s, %s) RETURNING run_id"
)
RESULT_SQL = (
    f"INSERT INTO dq.result (run_id, {', '.join(RESULT_COLUMNS)})"
    f" VALUES (%s, {', '.join(['%s'] * len(RESULT_COLUMNS))})"
)


def save_dqd(con: psycopg.Connection, run: DqdRun) -> int:
    """Store the run in the dq schema on a Postgres connection; the caller commits."""
    run_id = con.execute(
        RUN_SQL,
        [
            run.started_at,
            run.finished_at,
            run.cdm_source_name,
            run.cdm_release_date,
            run.vocabulary_version,
            Jsonb(run.overview),
        ],
    ).fetchone()[0]
    with con.cursor() as cur:
        cur.executemany(
            RESULT_SQL, [(run_id, *(r[c] for c in RESULT_COLUMNS)) for r in run.results]
        )
    return run_id


def _field(value) -> dict:
    """A Python value as an RDS Data API field."""
    if value is None:
        return {"isNull": True}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"longValue": value}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": str(value)}


def _begin(client, common: dict, attempts: int = 12, wait_s: float = 5.0) -> str:
    """Start a transaction, waiting while a paused Aurora wakes (about 15 s): the Data API answers
    DatabaseResumingException instead of waiting. Nothing has been written yet, so retrying is
    safe."""
    for attempt in range(attempts):
        try:
            return client.begin_transaction(**common)["transactionId"]
        except Exception as exc:
            if "DatabaseResuming" not in type(exc).__name__ or attempt == attempts - 1:
                raise
            time.sleep(wait_s)
    raise AssertionError("unreachable")


def save_dqd_data_api(client, cluster_arn: str, secret_arn: str, database: str, run: DqdRun) -> int:
    """Store the run in Aurora through the RDS Data API (SQL over HTTPS with IAM; no network
    path to the database needed), in one transaction."""
    common = dict(resourceArn=cluster_arn, secretArn=secret_arn, database=database)
    tx = _begin(client, common)
    try:
        run_params = {
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat(),
            "source": run.cdm_source_name,
            "released": run.cdm_release_date,
            "vocabulary": run.vocabulary_version,
            "overview": json.dumps(run.overview),
        }
        run_id = client.execute_statement(
            **common,
            transactionId=tx,
            sql=(
                "INSERT INTO dq.run (started_at, finished_at, cdm_source_name, cdm_release_date,"
                " vocabulary_version, overview) VALUES (CAST(:started_at AS timestamptz),"
                " CAST(:finished_at AS timestamptz), :source, CAST(:released AS date),"
                " :vocabulary, CAST(:overview AS jsonb)) RETURNING run_id"
            ),
            parameters=[{"name": k, "value": _field(v)} for k, v in run_params.items()],
        )["records"][0][0]["longValue"]
        sql = (
            f"INSERT INTO dq.result (run_id, {', '.join(RESULT_COLUMNS)})"
            f" VALUES (:run_id, {', '.join(':' + c for c in RESULT_COLUMNS)})"
        )
        rows = [
            [{"name": "run_id", "value": {"longValue": run_id}}]
            + [{"name": c, "value": _field(r[c])} for c in RESULT_COLUMNS]
            for r in run.results
        ]
        for i in range(0, len(rows), 200):
            client.batch_execute_statement(
                **common, transactionId=tx, sql=sql, parameterSets=rows[i : i + 200]
            )
        client.commit_transaction(resourceArn=cluster_arn, secretArn=secret_arn, transactionId=tx)
    except Exception:
        client.rollback_transaction(resourceArn=cluster_arn, secretArn=secret_arn, transactionId=tx)
        raise
    return run_id
