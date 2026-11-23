"""Store a synthetic release with its provenance: what made it, from what, at what privacy cost.

The privacy spend (the measurements column) is one record per mechanism that touched the source:
a histogram's columns, cells, and epsilon, or DP-SGD's epsilon, delta, noise, and steps.

source_rows (the people the release was trained on) and holdout_rows (the people kept out for
evaluation) are exact counts. They are kept for the release record and its reviewers; they are
not part of the synthetic data, whose row count is noisy.
"""

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from ehr_rwe_eln.synth.spec import Release, Spec


def code_version() -> str | None:
    """The git commit, with -dirty when there are uncommitted changes; None without git or
    outside a checkout (the app container has neither). The synth task on AWS has no checkout
    either; it runs one commit's code and says which in CODE_VERSION."""
    if os.environ.get("CODE_VERSION"):
        return os.environ["CODE_VERSION"]
    git = shutil.which("git")
    if git is None:
        return None
    try:
        return subprocess.run(  # noqa: S603  (fixed arguments, no input)
            [git, "describe", "--always", "--dirty"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except OSError, subprocess.CalledProcessError:
        return None


def save_release(
    con: psycopg.Connection,
    spec: Spec,
    release: Release,
    spend: list[dict],
    synthetic: pd.DataFrame,
    source_rows: int,
    holdout_rows: int,
) -> int:
    release_id = con.execute(
        "INSERT INTO synth.release (created_at, spec_name, method, epsilon, seed, spec,"
        " measurements, source_database, source_rows, holdout_rows, rows, code_version)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, current_database(), %s, %s, %s, %s)"
        " RETURNING release_id",
        [
            datetime.now(UTC),
            spec.name,
            release.method,
            release.epsilon,
            spec.seed,
            Jsonb(spec.model_dump(mode="json")),
            Jsonb(spend),
            source_rows,
            holdout_rows,
            len(synthetic),
            code_version(),
        ],
    ).fetchone()[0]
    # Through pandas' JSON writer: numpy numbers become plain ones, NaN becomes null.
    records = json.loads(synthetic.to_json(orient="records"))
    with con.cursor().copy("COPY synth.row (release_id, row_number, data) FROM STDIN") as copy:
        for i, record in enumerate(records, start=1):
            copy.write_row((release_id, i, Jsonb(record)))
    return release_id


def load_release(con: psycopg.Connection, release_id: int) -> pd.DataFrame:
    """The release's rows, with columns in its spec's order (jsonb does not keep key order)."""
    spec = con.execute(
        "SELECT spec FROM synth.release WHERE release_id = %s", [release_id]
    ).fetchone()[0]
    rows = con.execute(
        "SELECT data FROM synth.row WHERE release_id = %s ORDER BY row_number", [release_id]
    ).fetchall()
    return pd.DataFrame([r[0] for r in rows], columns=[c["name"] for c in spec["columns"]])


def save_report(con: psycopg.Connection, release_id: int, kind: str, report: dict) -> None:
    con.execute(
        "INSERT INTO synth.report VALUES (%s, %s, %s, %s, %s) ON CONFLICT (release_id, kind)"
        " DO UPDATE SET created_at = excluded.created_at, code_version = excluded.code_version,"
        " report = excluded.report",
        [release_id, kind, datetime.now(UTC), code_version(), Jsonb(report)],
    )
