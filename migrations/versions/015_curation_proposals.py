"""curation: literature claims Claude proposes, verified or rejected

Revision ID: 015
Revises: 014
Create Date: 2026-11-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "015"
down_revision: str | Sequence[str] | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Proposed evidence only: nothing here changes an assessment's criteria or class until a
    # curator accepts it. A claim is verified when its PMID was among the passages sent and its
    # quote appears in them; a rejected claim is kept with the reason, for the record.
    op.execute("""
        CREATE TABLE curation.proposal (
            proposal_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            run_id integer NOT NULL REFERENCES curation.run ON DELETE CASCADE,
            variant_id text NOT NULL,
            gene text NOT NULL,
            criterion text NOT NULL,
            strength text NOT NULL,
            pmid text NOT NULL,
            quote text NOT NULL,
            rationale text NOT NULL,
            verified boolean NOT NULL,
            rejected_why text
        )
    """)
    op.execute("CREATE INDEX proposal_run_variant ON curation.proposal (run_id, variant_id)")


def downgrade() -> None:
    op.execute("DROP TABLE curation.proposal")
