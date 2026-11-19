"""curation: variant curation runs and their assessments

Revision ID: 013
Revises: 012
Create Date: 2026-11-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "013"
down_revision: str | Sequence[str] | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA curation")
    # One row per curation run. sources names every input and its version (gnomAD dataset,
    # Ensembl release, ClinVar release for an eval run, each gene's expert-panel spec and a
    # hash of rules.yaml), so an assessment can be traced to exactly what produced it.
    op.execute("""
        CREATE TABLE curation.run (
            run_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            created_at timestamptz NOT NULL,
            variant_set text NOT NULL CHECK (variant_set IN ('panel', 'eval')),
            sources jsonb NOT NULL,
            code_version text,
            summary jsonb NOT NULL
        )
    """)
    # One row per variant per run. evidence holds the gnomAD and VEP facts the rules read;
    # met and not_assessed the criteria, each with its reason. expected is ClinVar's
    # expert-panel classification, set only in eval runs and never read by the rules.
    op.execute("""
        CREATE TABLE curation.assessment (
            run_id integer NOT NULL REFERENCES curation.run ON DELETE CASCADE,
            variant_id text NOT NULL,
            gene text NOT NULL,
            hgvsc text,
            hgvsp text,
            evidence jsonb NOT NULL,
            met jsonb NOT NULL,
            not_assessed jsonb NOT NULL,
            points integer,
            classification text NOT NULL,
            expected text,
            PRIMARY KEY (run_id, variant_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA curation CASCADE")
