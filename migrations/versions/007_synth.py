"""synth schema: synthetic data releases and their rows

Revision ID: 007
Revises: 006
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "007"
down_revision: str | Sequence[str] | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA synth")
    # One row per release, with what is needed to remake it and to review it: the spec as run,
    # each histogram's epsilon, the source, and the code version.
    op.execute("""
        CREATE TABLE synth.release (
            release_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            created_at timestamptz NOT NULL,
            spec_name text NOT NULL,
            method text NOT NULL,
            epsilon double precision NOT NULL CHECK (epsilon > 0),
            seed integer,
            spec jsonb NOT NULL,
            measurements jsonb NOT NULL,
            source_database text NOT NULL,
            source_rows integer NOT NULL,
            rows integer NOT NULL,
            code_version text
        )
    """)
    op.execute("""
        CREATE TABLE synth.row (
            release_id integer REFERENCES synth.release ON DELETE CASCADE,
            row_number integer,
            data jsonb NOT NULL,
            PRIMARY KEY (release_id, row_number)
        )
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA synth CASCADE")
