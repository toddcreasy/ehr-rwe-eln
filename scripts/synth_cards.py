"""Write a data card for every synthetic release, from its record and stored reports.

Usage: DB_NAME=ehr_rwe_eln_tte uv run python scripts/synth_cards.py

Run scripts/evaluate_synth.py first so the reports exist. Writes data/synth/cards/
release_<id>.md (gitignored, like all local data), replacing what is there.
"""

from pathlib import Path

from psycopg.rows import dict_row

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.synth.card import render_card

OUT = Path(__file__).resolve().parent.parent / "data" / "synth" / "cards"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with DatabaseSettings().connect() as con:
        releases = (
            con.cursor(row_factory=dict_row)
            .execute("SELECT * FROM synth.release ORDER BY release_id")
            .fetchall()
        )
        for release in releases:
            reports = dict(
                con.execute(
                    "SELECT kind, report FROM synth.report WHERE release_id = %s",
                    [release["release_id"]],
                ).fetchall()
            )
            path = OUT / f"release_{release['release_id']}.md"
            path.write_text(render_card(release, reports))
            print(f"  {path.name}: {', '.join(sorted(reports)) or 'no reports'}")
    print(f"written to {OUT}")


if __name__ == "__main__":
    main()
