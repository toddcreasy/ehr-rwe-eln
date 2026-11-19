"""synth: withdrawing releases, and who each release went to

Revision ID: 009
Revises: 008
Create Date: 2026-11-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "009"
down_revision: str | Sequence[str] | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A withdrawn release stays in the database, so its record and reports can still be
    # reviewed, but can no longer be exported, and its card says not to use it.
    op.execute("ALTER TABLE synth.release ADD COLUMN withdrawn_at timestamptz")
    op.execute("ALTER TABLE synth.release ADD COLUMN withdrawn_reason text")
    # One row per export: who received the release, so a withdrawal knows whom to notify.
    op.execute("""
        CREATE TABLE synth.distribution (
            distribution_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            release_id integer NOT NULL REFERENCES synth.release ON DELETE CASCADE,
            recipient text NOT NULL,
            contact text NOT NULL,
            purpose text NOT NULL,
            path text NOT NULL,
            exported_at timestamptz NOT NULL,
            code_version text
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE synth.distribution")
    op.execute("ALTER TABLE synth.release DROP COLUMN withdrawn_reason")
    op.execute("ALTER TABLE synth.release DROP COLUMN withdrawn_at")
