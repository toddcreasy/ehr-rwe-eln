"""eln schema: study subjects, ELN entries, and their extractions

Revision ID: 006
Revises: 005
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "006"
down_revision: str | Sequence[str] | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Outside the cdm schema, so rebuilding the CDM keeps entries and extractions.
    op.execute("CREATE SCHEMA eln")
    # The study's subject registry: the shared identifier between bench and EHR.
    op.execute("""
        CREATE TABLE eln.subject (
            subject_id text PRIMARY KEY,
            person_id integer NOT NULL UNIQUE
        )
    """)
    op.execute("""
        CREATE TABLE eln.entry (
            entry_id text PRIMARY KEY,
            title text NOT NULL,
            author text NOT NULL,
            created date NOT NULL,
            body text NOT NULL
        )
    """)
    # One extraction per entry: the validated Extraction as JSON, or the error that stopped it.
    op.execute("""
        CREATE TABLE eln.extraction (
            entry_id text PRIMARY KEY REFERENCES eln.entry ON DELETE CASCADE,
            model text NOT NULL,
            batch_id text,
            extracted_at timestamptz NOT NULL,
            extraction jsonb,
            error text,
            CHECK ((extraction IS NULL) <> (error IS NULL))
        )
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA eln CASCADE")
