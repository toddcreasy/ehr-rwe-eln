"""Store a synthetic release with its provenance: what made it, from what, at what privacy cost.

source_rows is the exact source count. It is kept for the release record and its reviewers; it
is not part of the synthetic data, whose row count is noisy.
"""

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb

from ehr_rwe_eln.synth.bayes_net import Measurement, plan
from ehr_rwe_eln.synth.spec import Release, Spec


def code_version() -> str | None:
    """The git commit, with -dirty when there are uncommitted changes; None without git or
    outside a checkout (the app container has neither)."""
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
    measurements: list[Measurement],
    synthetic: pd.DataFrame,
    source_rows: int,
) -> int:
    release_id = con.execute(
        "INSERT INTO synth.release (created_at, spec_name, method, epsilon, seed, spec,"
        " measurements, source_database, source_rows, rows, code_version)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, current_database(), %s, %s, %s)"
        " RETURNING release_id",
        [
            datetime.now(UTC),
            spec.name,
            release.method,
            release.epsilon,
            spec.seed,
            Jsonb(spec.model_dump(mode="json")),
            Jsonb(plan(measurements)),
            source_rows,
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
