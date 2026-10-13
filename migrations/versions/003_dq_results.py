"""dq schema for data quality runs and check results

Revision ID: 003
Revises: 002
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "003"
down_revision: str | Sequence[str] | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Outside the cdm schema, so rebuilding the CDM keeps the run history.
    op.execute("CREATE SCHEMA dq")
    op.execute("""
        CREATE TABLE dq.run (
            run_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            started_at timestamptz NOT NULL,
            finished_at timestamptz NOT NULL,
            cdm_source_name text,
            cdm_release_date date,
            vocabulary_version text,
            overview jsonb NOT NULL
        )
    """)
    # One row per check, with the columns of DQD's dqdashboard_results table.
    op.execute("""
        CREATE TABLE dq.result (
            run_id integer NOT NULL REFERENCES dq.run ON DELETE CASCADE,
            check_id text NOT NULL,
            check_name text NOT NULL,
            check_level text NOT NULL,
            check_description text NOT NULL,
            cdm_table_name text NOT NULL,
            cdm_field_name text,
            category text NOT NULL,
            subcategory text,
            context text NOT NULL,
            severity text NOT NULL,
            num_violated_rows bigint,
            pct_violated_rows double precision,
            num_denominator_rows bigint,
            threshold_value double precision,
            notes_value text,
            failed boolean NOT NULL,
            passed boolean NOT NULL,
            is_error boolean NOT NULL,
            not_applicable boolean NOT NULL,
            not_applicable_reason text,
            error text,
            execution_seconds double precision NOT NULL,
            query_text text NOT NULL,
            PRIMARY KEY (run_id, check_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA dq CASCADE")
