"""Read and write the eln schema: subjects, entries, and extractions."""

from datetime import UTC, date, datetime

import psycopg
from psycopg.types.json import Jsonb

from ehr_rwe_eln.eln.models import Extraction


def load_subjects(con: psycopg.Connection, registry: dict[str, int]) -> None:
    with con.cursor() as cur:
        cur.executemany(
            "INSERT INTO eln.subject VALUES (%s, %s)"
            " ON CONFLICT (subject_id) DO UPDATE SET person_id = excluded.person_id",
            list(registry.items()),
        )


def load_entries(con: psycopg.Connection, entries: list[tuple[str, str, str, date, str]]) -> None:
    """(entry_id, title, author, created, body) rows; an entry already loaded is left as is."""
    with con.cursor() as cur:
        cur.executemany(
            "INSERT INTO eln.entry VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", entries
        )


def pending(con: psycopg.Connection) -> dict[str, str]:
    """{entry id: body} for entries with no extraction yet, or whose extraction failed."""
    rows = con.execute(
        "SELECT e.entry_id, e.body FROM eln.entry e LEFT JOIN eln.extraction x USING (entry_id)"
        " WHERE x.entry_id IS NULL OR x.error IS NOT NULL ORDER BY e.entry_id"
    ).fetchall()
    return dict(rows)


def save_extraction(
    con: psycopg.Connection,
    entry_id: str,
    model: str,
    batch_id: str | None,
    extraction: Extraction | None,
    error: str | None,
) -> None:
    con.execute(
        "INSERT INTO eln.extraction VALUES (%s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (entry_id) DO UPDATE SET model = excluded.model,"
        " batch_id = excluded.batch_id, extracted_at = excluded.extracted_at,"
        " extraction = excluded.extraction, error = excluded.error",
        [
            entry_id,
            model,
            batch_id,
            datetime.now(UTC),
            Jsonb(extraction.model_dump(mode="json")) if extraction else None,
            error,
        ],
    )


def extractions(con: psycopg.Connection) -> dict[str, Extraction]:
    rows = con.execute(
        "SELECT entry_id, extraction FROM eln.extraction WHERE extraction IS NOT NULL"
    ).fetchall()
    return {entry_id: Extraction.model_validate(data) for entry_id, data in rows}
