"""omop_stats: concept counts precomputed from OMOP, for the agent's tools

Revision ID: 020
Revises: 019
Create Date: 2026-11-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "020"
down_revision: str | Sequence[str] | None = "019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Aggregates only, never a person: Aurora still holds no OMOP. scripts/build_omop_stats.py
    # replaces both tables in one transaction; the app reads them (src/ehr_rwe_eln/omop_stats.py)
    # so public tool calls never reach Redshift.
    op.execute("CREATE SCHEMA omop_stats")
    op.execute("""
        CREATE TABLE omop_stats.build (
            built_at timestamptz NOT NULL,
            cdm_source_name text,
            persons bigint NOT NULL,
            min_cell integer NOT NULL
        )
    """)
    # One row per concept that the data reach, itself or through a descendant. persons and records
    # count the concept and every descendant; both are NULL when persons is under the build's
    # min_cell, so a small count is never stored.
    op.execute("""
        CREATE TABLE omop_stats.concept_count (
            concept_id integer PRIMARY KEY,
            concept_name text NOT NULL,
            domain_id text NOT NULL,
            vocabulary_id text NOT NULL,
            concept_class_id text NOT NULL,
            persons integer,
            records bigint
        )
    """)
    # Read-only for the app; only the build (as the migration user) writes.
    op.execute("GRANT USAGE ON SCHEMA omop_stats TO app")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA omop_stats TO app")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA omop_stats GRANT SELECT ON TABLES TO app")


def downgrade() -> None:
    op.execute("DROP SCHEMA omop_stats CASCADE")
