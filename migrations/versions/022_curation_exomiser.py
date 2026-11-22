"""curation: carriers' Exomiser phenotype ranks per variant, shown to the curator as context

Revision ID: 022
Revises: 021
Create Date: 2026-11-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "022"
down_revision: str | Sequence[str] | None = "021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One row per panel variant per Exomiser data release, written by
    # scripts/run_exomiser.py. ranks: for each carrier, where the variant's gene falls by
    # Exomiser's phenotype score among the genes that carrier has a variant in (1 is first);
    # genes: how many genes each carrier has, in the same order. auc: how well the phenotype
    # score picks out the gene's pathogenic carriers across the study (null when the gene has
    # none). Only the phenotype score: Exomiser's variant score includes ClinVar. Context for
    # the curator, not ACMG evidence: nothing here is scored as PP4. No subject or person IDs.
    op.execute("""
        CREATE TABLE curation.exomiser (
            data_release text NOT NULL,
            variant_id text NOT NULL,
            gene text NOT NULL,
            subjects integer NOT NULL,
            ranks integer[] NOT NULL,
            genes integer[] NOT NULL,
            auc real,
            created_at timestamptz NOT NULL,
            PRIMARY KEY (data_release, variant_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE curation.exomiser")
