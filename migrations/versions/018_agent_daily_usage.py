"""agent: tokens the public /agent spent each day, for the daily limit

Revision ID: 018
Revises: 017
Create Date: 2026-11-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "018"
down_revision: str | Sequence[str] | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One row per day, US Eastern. /agent adds each call's tokens (input, output, cache reads
    # and writes) after it finishes and refuses new calls once today's total reaches
    # DAILY_TOKEN_LIMIT. Same design as glia-nav's daily_usage.
    op.execute("CREATE SCHEMA IF NOT EXISTS agent")
    op.execute("""
        CREATE TABLE agent.daily_usage (
            day date PRIMARY KEY,
            tokens bigint NOT NULL,
            calls integer NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE agent.daily_usage")
    op.execute("DROP SCHEMA agent")
