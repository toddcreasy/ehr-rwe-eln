"""schema version table

Alembic creates alembic_version when it applies this revision. Nothing else.

Revision ID: 001
Revises:
Create Date: 2026-10-07
"""

from collections.abc import Sequence

revision: str = "001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
