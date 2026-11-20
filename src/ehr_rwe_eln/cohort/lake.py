"""Publish OMOP from the staging Postgres to the S3 Tables lake, and fingerprint each table so the
copy can be checked against its source.

The ETL (etl.py) still builds OMOP in Postgres; this copies its output. Each table is purged,
recreated, and filled in one Iceberg transaction, so a table is either complete or empty, never
partial. A crash mid-table leaves it empty; rerun that table.
"""

import contextlib
import math
import time
from collections.abc import Iterator

import boto3
import psycopg
import pyarrow as pa
from psycopg import sql
from pyiceberg.catalog import Catalog, load_catalog
from pyiceberg.exceptions import NoSuchTableError

from ehr_rwe_eln.config import LakeSettings

# Postgres type -> Arrow type. OMOP's numeric columns have no fixed precision, which Iceberg
# decimals require, so they travel as 64-bit floats. Any other type stops the publish.
ARROW_TYPES = {
    "integer": pa.int32(),
    "bigint": pa.int64(),
    "character varying": pa.string(),
    "text": pa.string(),
    "date": pa.date32(),
    "timestamp without time zone": pa.timestamp("us"),
    "numeric": pa.float64(),
}

BATCH_ROWS = 500_000


def catalog(settings: LakeSettings) -> Catalog:
    """The table bucket through the S3 Tables Iceberg REST endpoint, signed with the caller's AWS
    credentials."""
    return load_catalog(
        "s3tables",
        type="rest",
        uri=f"https://s3tables.{settings.aws_region}.amazonaws.com/iceberg",
        warehouse=settings.lake_table_bucket_arn,
        **{
            "rest.sigv4-enabled": "true",
            "rest.signing-name": "s3tables",
            "rest.signing-region": settings.aws_region,
        },
    )


def tables(con: psycopg.Connection, schema: str) -> list[str]:
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name",
        [schema],
    )
    return [name for (name,) in rows]


def columns(con: psycopg.Connection, schema: str, table: str) -> list[tuple[str, str]]:
    """(name, Postgres type) in table order."""
    return con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
        [schema, table],
    ).fetchall()


def arrow_schema(cols: list[tuple[str, str]]) -> pa.Schema:
    unknown = [f"{name} ({kind})" for name, kind in cols if kind not in ARROW_TYPES]
    if unknown:
        raise ValueError(f"no lake type for: {', '.join(unknown)}")
    return pa.schema([pa.field(name, ARROW_TYPES[kind]) for name, kind in cols])


def batches(
    con: psycopg.Connection, schema: str, table: str, batch_rows: int = BATCH_ROWS
) -> Iterator[pa.Table]:
    """The table as Arrow batches, streamed through a server-side cursor so a 16M-row table never
    sits in memory at once."""
    cols = columns(con, schema, table)
    arrow = arrow_schema(cols)
    select = sql.SQL(", ").join(
        sql.SQL("{}::double precision").format(sql.Identifier(name))
        if kind == "numeric"
        else sql.Identifier(name)
        for name, kind in cols
    )
    query = sql.SQL("SELECT {} FROM {}.{}").format(
        select, sql.Identifier(schema), sql.Identifier(table)
    )
    with con.cursor(name=f"publish_{table}") as cur:
        cur.itersize = batch_rows
        cur.execute(query)
        while rows := cur.fetchmany(batch_rows):
            values = zip(*rows, strict=True)
            yield pa.table(
                [pa.array(v, type=f.type) for v, f in zip(values, arrow, strict=True)],
                schema=arrow,
            )


def publish_table(
    con: psycopg.Connection,
    lake: Catalog,
    namespace: str,
    schema: str,
    table: str,
    batch_rows: int = BATCH_ROWS,
) -> int:
    """Replace one lake table with the Postgres table. Returns the rows written."""
    identifier = f"{namespace}.{table}"
    # S3 Tables only drops with purge, which deletes the data files too.
    with contextlib.suppress(NoSuchTableError):
        lake.purge_table(identifier)
    iceberg = lake.create_table(identifier, schema=arrow_schema(columns(con, schema, table)))
    written = 0
    with iceberg.transaction() as tx:
        for batch in batches(con, schema, table, batch_rows):
            tx.append(batch)
            written += batch.num_rows
    return written


def fingerprint_sql(relation: str, cols: list[tuple[str, str]]) -> tuple[str, list[tuple]]:
    """One summary query that runs unchanged on Postgres and Redshift, and its (label, kind)
    columns. kind is 'int' (compare exactly) or 'float' (compare within 1e-9, since float sums
    depend on addition order)."""
    exprs = ["count(*)"]
    labels = [("rows", "int")]
    for name, kind in cols:
        col = f'"{name}"'
        exprs.append(f"count({col})")
        labels.append((f"{name}: non-null", "int"))
        if kind in ("integer", "bigint"):
            exprs.append(f"sum(cast({col} as bigint))")
            labels.append((f"{name}: sum", "int"))
        elif kind in ("character varying", "text"):
            exprs.append(f"sum(cast(length({col}) as bigint))")
            labels.append((f"{name}: total length", "int"))
        elif kind in ("date", "timestamp without time zone"):
            exprs.append(f"cast(min({col}) as varchar)")
            labels.append((f"{name}: min", "text"))
            exprs.append(f"cast(max({col}) as varchar)")
            labels.append((f"{name}: max", "text"))
        elif kind == "numeric":
            exprs.append(f"sum(cast({col} as double precision))")
            labels.append((f"{name}: sum", "float"))
        else:
            raise ValueError(f"no fingerprint for {name} ({kind})")
    return f"SELECT {', '.join(exprs)} FROM {relation}", labels


def compare(labels: list[tuple], source: list, lake: list) -> list[str]:
    """Differences between two fingerprints, as readable lines; empty when they match."""
    diffs = []
    for (label, kind), a, b in zip(labels, source, lake, strict=True):
        if a is None or b is None:
            same = a is None and b is None
        elif kind == "float":
            same = math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
        elif kind == "int":
            same = int(a) == int(b)
        else:
            same = str(a) == str(b)
        if not same:
            diffs.append(f"{label}: source {a}, lake {b}")
    return diffs


def redshift_query(settings: LakeSettings, query: str, timeout_s: int = 600) -> list[list]:
    """Run one statement through the Redshift Data API as the caller's IAM identity and return
    its rows."""
    client = boto3.client("redshift-data", region_name=settings.aws_region)
    statement = client.execute_statement(
        WorkgroupName=settings.redshift_workgroup,
        Database=settings.redshift_database,
        Sql=query,
    )
    deadline = time.monotonic() + timeout_s
    while True:
        status = client.describe_statement(Id=statement["Id"])
        if status["Status"] == "FINISHED":
            break
        if status["Status"] in ("FAILED", "ABORTED"):
            raise RuntimeError(f"Redshift: {status.get('Error', status['Status'])}")
        if time.monotonic() > deadline:
            raise TimeoutError(f"Redshift statement {statement['Id']} still {status['Status']}")
        time.sleep(1)
    if not status.get("HasResultSet"):
        return []
    rows = []
    for page in client.get_paginator("get_statement_result").paginate(Id=statement["Id"]):
        for record in page["Records"]:
            rows.append([None if f.get("isNull") else next(iter(f.values())) for f in record])
    return rows
