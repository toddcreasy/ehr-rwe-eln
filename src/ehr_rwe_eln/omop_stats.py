"""Concept counts from OMOP, precomputed for the agent's tools (agents/omop_tools.py).

Public tool calls read these from Aurora and never reach Redshift, where every query bills at least
60 seconds against the workgroup's monthly cap. scripts/build_omop_stats.py runs the count once
(the lake or the staging Postgres) and stores it.

For each concept the data reach, persons is how many people have a record of it or any of its
descendants, and records how many such records; through concept_ancestor, so "hypertension"
includes every more specific kind. A count under MIN_CELL is never stored: persons and records are
both NULL, and the tools say "fewer than 11" (the CMS cell size rule; decided 2026-11-21).
"""

import json
from datetime import datetime

# Persons below this are suppressed, so a rare concept can't point at a handful of people.
MIN_CELL = 11

# Every event table with a standard concept, as (table, concept column).
EVENT_TABLES = [
    ("condition_occurrence", "condition_concept_id"),
    ("drug_exposure", "drug_concept_id"),
    ("procedure_occurrence", "procedure_concept_id"),
    ("measurement", "measurement_concept_id"),
    ("observation", "observation_concept_id"),
    ("device_exposure", "device_concept_id"),
]


def concept_counts_sql(cdm: str = "cdm") -> str:
    """One query, unchanged on Postgres and Redshift. Events are reduced to one row per person and
    concept first, so the join to concept_ancestor stays small; a person reaches an ancestor
    through several descendants, hence count(DISTINCT person_id)."""
    events = "\n            UNION ALL ".join(
        f"SELECT person_id, {column} AS concept_id FROM {cdm}.{table}"
        for table, column in EVENT_TABLES
    )
    return f"""
        WITH events AS (
            {events}
        ),
        per_person AS (
            SELECT person_id, concept_id, count(*) AS records
            FROM events WHERE concept_id <> 0
            GROUP BY person_id, concept_id
        ),
        rolled AS (
            SELECT ca.ancestor_concept_id AS concept_id,
                   count(DISTINCT p.person_id) AS persons, sum(p.records) AS records
            FROM per_person p
            JOIN {cdm}.concept_ancestor ca ON ca.descendant_concept_id = p.concept_id
            GROUP BY ca.ancestor_concept_id
        )
        SELECT c.concept_id, c.concept_name, c.domain_id, c.vocabulary_id, c.concept_class_id,
               r.persons, r.records
        FROM rolled r JOIN {cdm}.concept c ON c.concept_id = r.concept_id
    """


def suppress(rows: list[tuple]) -> list[tuple]:
    """(concept_id, name, domain, vocabulary, class, persons, records) with persons and records
    set to None where persons is under MIN_CELL."""
    return [
        (*row[:5], *((int(row[5]), int(row[6])) if row[5] >= MIN_CELL else (None, None)))
        for row in rows
    ]


def build(con, cdm: str = "cdm") -> tuple[dict, list[tuple]]:
    """The build record and the suppressed concept counts. con is a psycopg connection or a
    lake.RedshiftSession; cdm is the OMOP tables' prefix."""
    rows = suppress(con.execute(concept_counts_sql(cdm)).fetchall())
    source = con.execute(f"SELECT cdm_source_name FROM {cdm}.cdm_source").fetchone()
    persons = con.execute(f"SELECT count(*) FROM {cdm}.person").fetchone()[0]
    record = {
        "built_at": datetime.now().astimezone(),
        "cdm_source_name": source[0] if source else None,
        "persons": int(persons),
        "min_cell": MIN_CELL,
    }
    return record, rows


INSERT_BUILD = (
    "INSERT INTO omop_stats.build (built_at, cdm_source_name, persons, min_cell)"
    " VALUES (%s, %s, %s, %s)"
)
INSERT_COUNT = (
    "INSERT INTO omop_stats.concept_count (concept_id, concept_name, domain_id, vocabulary_id,"
    " concept_class_id, persons, records) VALUES (%s, %s, %s, %s, %s, %s, %s)"
)


def save(con, record: dict, rows: list[tuple]) -> None:
    """Replace the stored counts (psycopg; the caller commits)."""
    con.execute("DELETE FROM omop_stats.build")
    con.execute("DELETE FROM omop_stats.concept_count")
    con.execute(INSERT_BUILD, list(record.values()))
    with con.cursor() as cur:
        cur.executemany(INSERT_COUNT, rows)


def save_data_api(client, cluster_arn: str, secret_arn: str, database: str, record, rows) -> None:
    """Replace the stored counts in Aurora through the RDS Data API, in one transaction."""
    common = dict(resourceArn=cluster_arn, secretArn=secret_arn, database=database)
    tx = client.begin_transaction(**common)["transactionId"]

    def value(v):
        if v is None:
            return {"isNull": True}
        if isinstance(v, int):
            return {"longValue": v}
        if isinstance(v, datetime):
            return {"stringValue": v.isoformat()}
        return {"stringValue": str(v)}

    try:
        for sql in ("DELETE FROM omop_stats.build", "DELETE FROM omop_stats.concept_count"):
            client.execute_statement(**common, transactionId=tx, sql=sql)
        client.execute_statement(
            **common,
            transactionId=tx,
            sql="INSERT INTO omop_stats.build VALUES"
            " (CAST(:built_at AS timestamptz), :source, :persons, :min_cell)",
            parameters=[
                {"name": "built_at", "value": value(record["built_at"])},
                {"name": "source", "value": value(record["cdm_source_name"])},
                {"name": "persons", "value": value(record["persons"])},
                {"name": "min_cell", "value": value(record["min_cell"])},
            ],
        )
        names = ["id", "name", "domain", "vocabulary", "class", "persons", "records"]
        sql = (
            "INSERT INTO omop_stats.concept_count VALUES"
            " (:id, :name, :domain, :vocabulary, :class, :persons, :records)"
        )
        sets = [
            [{"name": n, "value": value(v)} for n, v in zip(names, row, strict=True)]
            for row in rows
        ]
        for i in range(0, len(sets), 500):
            client.batch_execute_statement(
                **common, transactionId=tx, sql=sql, parameterSets=sets[i : i + 500]
            )
        client.commit_transaction(resourceArn=cluster_arn, secretArn=secret_arn, transactionId=tx)
    except Exception:
        client.rollback_transaction(resourceArn=cluster_arn, secretArn=secret_arn, transactionId=tx)
        raise


def summary(record: dict, rows: list[tuple]) -> str:
    shown = sum(1 for r in rows if r[5] is not None)
    return json.dumps(
        {
            "concepts": len(rows),
            "with_counts": shown,
            "suppressed": len(rows) - shown,
            "persons": record["persons"],
            "min_cell": record["min_cell"],
        }
    )
