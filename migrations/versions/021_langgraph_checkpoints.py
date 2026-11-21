"""langgraph: checkpoints for the literature curation graph

Revision ID: 021
Revises: 020
Create Date: 2026-11-21
"""

from collections.abc import Sequence

from alembic import op
from langgraph.checkpoint.postgres.base import BasePostgresSaver

revision: str = "021"
down_revision: str | Sequence[str] | None = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The graph in curation/literature_graph.py saves its state here after every step, so a run
    # paused for the curator resumes where it stopped. The tables are langgraph-checkpoint-
    # postgres's own, made by its migration list, so its setup() finds nothing left to do
    # (tests/test_curation_literature_graph.py checks this; a library upgrade that adds a
    # migration needs a new one here). CONCURRENTLY is dropped: the tables are new and empty,
    # and it can't run inside the migration's transaction. Checkpoints hold paper passages
    # (publishers' text): this schema is never copied to Aurora.
    op.execute("CREATE SCHEMA langgraph")
    op.execute("SET LOCAL search_path TO langgraph")
    for sql in BasePostgresSaver.MIGRATIONS:
        op.execute(sql.replace(" CONCURRENTLY", ""))
    n = len(BasePostgresSaver.MIGRATIONS)
    op.execute(f"INSERT INTO checkpoint_migrations (v) SELECT generate_series(0, {n - 1})")  # noqa: S608  (an int)
    op.execute("SET LOCAL search_path TO DEFAULT")
    # The decisions route resumes the graph, so the app writes checkpoints.
    op.execute("GRANT USAGE ON SCHEMA langgraph TO app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA langgraph TO app")


def downgrade() -> None:
    op.execute("DROP SCHEMA langgraph CASCADE")
