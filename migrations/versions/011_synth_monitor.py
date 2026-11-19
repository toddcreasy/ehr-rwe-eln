"""synth: a record of each scheduled privacy check

Revision ID: 011
Revises: 010
Create Date: 2026-11-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "011"
down_revision: str | Sequence[str] | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One row per run of ehr_rwe_eln.synth.monitor. fingerprints holds, per spec, a hash of the
    # source table and of the synth code; a run whose fingerprints match the last evaluated
    # run's is recorded as skipped, since seeded attacks on the same data give the same result.
    op.execute("""
        CREATE TABLE synth.monitor_run (
            run_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            started_at timestamptz NOT NULL,
            finished_at timestamptz NOT NULL,
            fingerprints jsonb NOT NULL,
            skipped boolean NOT NULL,
            releases_checked integer NOT NULL,
            flags jsonb NOT NULL
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE synth.monitor_run")
