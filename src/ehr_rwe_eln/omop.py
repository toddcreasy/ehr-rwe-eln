"""Where OMOP readers get their data: the lake through the Redshift Data API, or the staging
Postgres. Needs only boto3 and psycopg, so it runs in the app image (publishing to the lake, in
cohort/lake.py, needs the lake dependency group)."""

import contextlib
import datetime
import time
from dataclasses import dataclass
from decimal import Decimal

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from ehr_rwe_eln.config import DatabaseSettings, LakeSettings


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

    # keep_alive_s: how long the session (and its temp tables) outlives its last statement.
    # Callers do long local work between statements; run_tte.py's 500 bootstrap replicates went
    # past 15 minutes on 2026-11-21 and the session expired. An idle session is still billed
    # as compute until it ends (8 RPUs for the hour, 2026-11-23), so leaving the block ends it.
    def __init__(self, settings: LakeSettings, keep_alive_s: int = 3600, timeout_s: int = 900):
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
        try:
            status = _wait(self.client, statement["Id"], self.timeout_s)
        except BaseException:
            # A timeout or Ctrl-C leaves the statement running, and a busy session refuses the
            # terminate in __exit__: cancel it and give the cancel time to land.
            with contextlib.suppress(Exception):
                self.client.cancel_statement(Id=statement["Id"])
                for _ in range(30):
                    state = self.client.describe_statement(Id=statement["Id"])["Status"]
                    if state not in ("SUBMITTED", "PICKED", "STARTED"):
                        break
                    time.sleep(1)
            raise
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
        # The Data API has no call to end a session, so the session ends its own backend (the
        # statement is not waited on: it fails as its connection closes). A session that has
        # already expired refuses it, which is just as good.
        if self.session_id:
            with contextlib.suppress(ClientError, BotoCoreError):
                self.client.execute_statement(
                    Sql="SELECT pg_terminate_backend(pg_backend_pid())", SessionId=self.session_id
                )
        self.session_id = None


def connect_omop(settings: LakeSettings | None = None):
    """Where OMOP is read from, and the prefix its tables go by: the lake through Redshift
    (OMOP_SOURCE=lake, the default) or the staging Postgres (OMOP_SOURCE=staging)."""
    settings = settings or LakeSettings()
    if settings.omop_source == "staging":
        return DatabaseSettings().connect(), "cdm"
    return RedshiftSession(settings), settings.redshift_lake_schema
