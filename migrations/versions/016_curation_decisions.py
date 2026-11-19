"""curation: curator decisions, with who and when

Revision ID: 016
Revises: 015
Create Date: 2026-11-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "016"
down_revision: str | Sequence[str] | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Append only: a new decision on a variant adds a row, so the history of who decided what
    # and when is kept. The latest row per (run_id, variant_id) is the current decision.
    # accepted lists the curation.proposal rows the curator accepted; criteria is every
    # criterion the class rests on (the rules' plus the accepted proposals'); points and
    # computed are what those criteria score. classification is the curator's call, which
    # differs from computed only with a note saying why.
    op.execute("""
        CREATE TABLE curation.decision (
            decision_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            run_id integer NOT NULL,
            variant_id text NOT NULL,
            curator text NOT NULL CHECK (length(trim(curator)) > 0),
            decided_at timestamptz NOT NULL DEFAULT now(),
            accepted integer[] NOT NULL,
            criteria jsonb NOT NULL,
            points integer,
            computed text NOT NULL,
            classification text NOT NULL,
            note text,
            FOREIGN KEY (run_id, variant_id) REFERENCES curation.assessment ON DELETE CASCADE,
            CHECK (classification = computed OR length(trim(coalesce(note, ''))) > 0)
        )
    """)
    op.execute("CREATE INDEX decision_variant ON curation.decision (run_id, variant_id)")


def downgrade() -> None:
    op.execute("DROP TABLE curation.decision")
