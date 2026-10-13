"""concept and unit ids on dq.result, for CONCEPT level checks

Revision ID: 004
Revises: 003
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "004"
down_revision: str | Sequence[str] | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Text, as DQD writes them: a check can name several concepts, "4090861, 4025213".
    op.execute("ALTER TABLE dq.result ADD COLUMN concept_id text, ADD COLUMN unit_concept_id text")


def downgrade() -> None:
    op.execute("ALTER TABLE dq.result DROP COLUMN concept_id, DROP COLUMN unit_concept_id")
