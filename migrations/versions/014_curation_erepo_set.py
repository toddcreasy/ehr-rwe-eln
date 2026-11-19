"""curation: allow eval runs against the ClinGen Evidence Repository

Revision ID: 014
Revises: 013
Create Date: 2026-11-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "014"
down_revision: str | Sequence[str] | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # erepo: expert panel curations from the Evidence Repository, scored criterion by
    # criterion as well as by class.
    op.execute("ALTER TABLE curation.run DROP CONSTRAINT run_variant_set_check")
    op.execute(
        "ALTER TABLE curation.run ADD CONSTRAINT run_variant_set_check"
        " CHECK (variant_set IN ('panel', 'eval', 'erepo'))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM curation.run WHERE variant_set = 'erepo'")
    op.execute("ALTER TABLE curation.run DROP CONSTRAINT run_variant_set_check")
    op.execute(
        "ALTER TABLE curation.run ADD CONSTRAINT run_variant_set_check"
        " CHECK (variant_set IN ('panel', 'eval'))"
    )
