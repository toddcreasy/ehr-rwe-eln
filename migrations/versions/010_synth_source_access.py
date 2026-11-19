"""synth: every stored spec states its source access

Revision ID: 010
Revises: 009
Create Date: 2026-11-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "010"
down_revision: str | Sequence[str] | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Specs now must say whether their source is synthetic or controlled-access, so the
    # real-data guards cannot be skipped by leaving it out. Releases stored before carry no
    # such field. They can only be synthetic: this repository never holds real patient data
    # (CLAUDE.md, data rules), so they are marked synthetic rather than left unreadable.
    op.execute(
        'UPDATE synth.release SET spec = spec || \'{"source_access": "synthetic"}\''
        " WHERE NOT spec ? 'source_access'"
    )


def downgrade() -> None:
    op.execute("UPDATE synth.release SET spec = spec - 'source_access'")
