"""synth: holdout counts on releases, and evaluation reports

Revision ID: 008
Revises: 007
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "008"
down_revision: str | Sequence[str] | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # source_rows now counts the people a release was trained on; holdout_rows the people kept
    # out of it for evaluation.
    op.execute("ALTER TABLE synth.release ADD COLUMN holdout_rows integer")
    # One report per release and kind (fidelity now, privacy next), replaced when rerun.
    op.execute("""
        CREATE TABLE synth.report (
            release_id integer REFERENCES synth.release ON DELETE CASCADE,
            kind text,
            created_at timestamptz NOT NULL,
            code_version text,
            report jsonb NOT NULL,
            PRIMARY KEY (release_id, kind)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE synth.report")
    op.execute("ALTER TABLE synth.release DROP COLUMN holdout_rows")
