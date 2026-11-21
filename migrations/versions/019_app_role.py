"""app: a least-privilege login for the deployed app and monitor, signing in with IAM

Revision ID: 019
Revises: 018
Create Date: 2026-11-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "019"
down_revision: str | Sequence[str] | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every schema the API and the monitor read or write. Tables only: no DDL, no other schemas.
SCHEMAS = ("agent", "curation", "dq", "eln", "synth", "tte")


def upgrade() -> None:
    # No password: on Aurora the app signs in with a 15-minute IAM token (rds_iam). Local Postgres
    # has no rds_iam, so the role exists there but nothing logs in as it.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app') THEN
                CREATE ROLE app LOGIN;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'rds_iam') THEN
                GRANT rds_iam TO app;
            END IF;
        END
        $$
    """)
    for schema in SCHEMAS:
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO app")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO app")
        op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO app")
        # Tables later migrations create (as the migration user) get the same rights.
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app"
        )
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT USAGE, SELECT ON SEQUENCES TO app"
        )


def downgrade() -> None:
    op.execute("DROP OWNED BY app")
    op.execute("DROP ROLE app")
