"""Publish OMOP from the staging Postgres to the S3 Tables lake, and fingerprint each table so the
copy can be checked against its source.

The ETL (etl.py) still builds OMOP in Postgres; this copies its output. Each table is purged,
recreated, and filled in one Iceberg transaction, so a table is either complete or empty, never
partial. A crash mid-table leaves it empty; rerun that table.
"""

import contextlib
import datetime
import math
import time
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal

import boto3
import psycopg
import pyarrow as pa
from psycopg import sql
from pyiceberg.catalog import Catalog, load_catalog
from pyiceberg.exceptions import NoSuchTableError

from ehr_rwe_eln.config import DatabaseSettings, LakeSettings

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
    if not settings.lake_table_bucket_arn:
        raise ValueError("LAKE_TABLE_BUCKET_ARN is not set in .env")
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


def _wait(client, statement_id: str, timeout_s: int) -> dict:
    deadline = time.monotonic() + timeout_s
    while True:
        status = client.describe_statement(Id=statement_id)
        if status["Status"] == "FINISHED":
            return status
        if status["Status"] in ("FAILED", "ABORTED"):
            raise RuntimeError(f"Redshift: {status.get('Error', status['Status'])}")
        if time.monotonic() > deadline:
            raise TimeoutError(f"Redshift statement {statement_id} still {status['Status']}")
        time.sleep(0.5)


def _results(client, statement_id: str) -> tuple[list[dict], list[list]]:
    """Column metadata and raw rows (None for NULL, else the field's one value)."""
    meta, rows = [], []
    for page in client.get_paginator("get_statement_result").paginate(Id=statement_id):
        meta = meta or page["ColumnMetadata"]
        for record in page["Records"]:
            rows.append([None if f.get("isNull") else next(iter(f.values())) for f in record])
    return meta, rows


def redshift_query(settings: LakeSettings, query: str, timeout_s: int = 600) -> list[list]:
    """Run one statement through the Redshift Data API as the caller's IAM identity and return
    its rows, values as the Data API gives them."""
    client = boto3.client("redshift-data", region_name=settings.aws_region)
    statement = client.execute_statement(
        WorkgroupName=settings.redshift_workgroup,
        Database=settings.redshift_database,
        Sql=query,
    )
    status = _wait(client, statement["Id"], timeout_s)
    return _results(client, statement["Id"])[1] if status.get("HasResultSet") else []


# Redshift returns dates, timestamps, and numerics as text; psycopg returns Python objects.
# Converting them makes results from both engines compare equal.
_CONVERT = {
    "date": datetime.date.fromisoformat,
    "timestamp": datetime.datetime.fromisoformat,
    "numeric": Decimal,
}


@dataclass
class Column:
    name: str


class RedshiftCursor:
    def __init__(self, columns: list[Column], rows: list[tuple]):
        self.description = columns
        self.rows = rows

    def fetchone(self) -> tuple | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple]:
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class RedshiftSession:
    """The part of a psycopg connection the OMOP readers use (execute, then fetchone, fetchall,
    description), over one Redshift Data API session, so temp tables live across statements.
    Statements take no parameters: callers write integers into the SQL themselves."""

    def __init__(self, settings: LakeSettings, keep_alive_s: int = 900, timeout_s: int = 900):
        self.settings = settings
        self.keep_alive_s = keep_alive_s
        self.timeout_s = timeout_s
        self.client = boto3.client("redshift-data", region_name=settings.aws_region)
        self.session_id: str | None = None

    def execute(self, query: str) -> RedshiftCursor:
        if self.session_id:
            statement = self.client.execute_statement(Sql=query, SessionId=self.session_id)
        else:
            statement = self.client.execute_statement(
                Sql=query,
                WorkgroupName=self.settings.redshift_workgroup,
                Database=self.settings.redshift_database,
                SessionKeepAliveSeconds=self.keep_alive_s,
            )
            self.session_id = statement["SessionId"]
        status = _wait(self.client, statement["Id"], self.timeout_s)
        if not status.get("HasResultSet"):
            return RedshiftCursor([], [])
        meta, raw = _results(self.client, statement["Id"])
        convert = [_CONVERT.get(m["typeName"]) for m in meta]
        rows = [
            tuple(v if v is None or f is None else f(v) for v, f in zip(row, convert, strict=True))
            for row in raw
        ]
        return RedshiftCursor([Column(m["label"]) for m in meta], rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        # The Data API has no call to end a session; it expires keep_alive_s after the last use.
        self.session_id = None


def connect_omop(settings: LakeSettings | None = None):
    """Where OMOP is read from, and the prefix its tables go by: the lake through Redshift
    (OMOP_SOURCE=lake, the default) or the staging Postgres (OMOP_SOURCE=staging)."""
    settings = settings or LakeSettings()
    if settings.omop_source == "staging":
        return DatabaseSettings().connect(), "cdm"
    return RedshiftSession(settings), settings.redshift_lake_schema
