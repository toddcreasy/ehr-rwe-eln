"""synth: recipients confirming they deleted a withdrawn release

Revision ID: 012
Revises: 011
Create Date: 2026-11-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "012"
down_revision: str | Sequence[str] | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Set when a recipient of a withdrawn release confirms they deleted every copy. evidence
    # says how (a reply, and when), so the record can be checked later.
    op.execute("ALTER TABLE synth.distribution ADD COLUMN deletion_confirmed_at timestamptz")
    op.execute("ALTER TABLE synth.distribution ADD COLUMN deletion_evidence text")


def downgrade() -> None:
    op.execute("ALTER TABLE synth.distribution DROP COLUMN deletion_evidence")
    op.execute("ALTER TABLE synth.distribution DROP COLUMN deletion_confirmed_at")
