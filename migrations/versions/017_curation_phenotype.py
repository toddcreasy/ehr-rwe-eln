"""curation: carriers' phenotype scores per variant, shown to the curator as context

Revision ID: 017
Revises: 016
Create Date: 2026-11-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "017"
down_revision: str | Sequence[str] | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One row per panel variant per HPO release, written by scripts/match_phenotypes.py.
    # percentiles: where each carrier's phenotype score for the gene's group falls among all
    # study subjects. Context for the curator, not ACMG evidence: nothing here is scored as
    # PP4. No subject or person IDs.
    op.execute("""
        CREATE TABLE curation.phenotype (
            hpo_release text NOT NULL,
            variant_id text NOT NULL,
            gene text NOT NULL,
            gene_group text[] NOT NULL,
            subjects integer NOT NULL,
            percentiles real[] NOT NULL,
            created_at timestamptz NOT NULL,
            PRIMARY KEY (hpo_release, variant_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE curation.phenotype")
