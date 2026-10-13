"""tte schema for target trial emulation runs and their bias reports

Revision ID: 005
Revises: 004
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "005"
down_revision: str | Sequence[str] | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Outside the cdm schema, so rebuilding the CDM keeps the run history.
    op.execute("CREATE SCHEMA tte")
    op.execute("""
        CREATE TABLE tte.run (
            run_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            started_at timestamptz NOT NULL,
            finished_at timestamptz NOT NULL,
            cdm_source_name text,
            persons bigint NOT NULL
        )
    """)
    # One bias report per protocol, as JSON: nested, and only ever read whole by the page.
    op.execute("""
        CREATE TABLE tte.report (
            run_id integer NOT NULL REFERENCES tte.run ON DELETE CASCADE,
            protocol_id integer NOT NULL,
            protocol_name text NOT NULL,
            report jsonb NOT NULL,
            PRIMARY KEY (run_id, protocol_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA tte CASCADE")
