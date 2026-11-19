"""Export a synthetic release for a recipient, and record who received it.

Usage: uv run python scripts/export_release.py --release 3 --recipient "Pipeline team"
           --contact team@example.org --purpose "testing the cohort pipeline"

Writes data/synth/exports/release_<id>_<distribution id>/ with rows.csv and card.md (the data
card, which states the release's intended use and limitations). Records the export in
synth.distribution, so a later withdrawal knows whom to notify. Refuses a withdrawn release.
"""

import argparse
from pathlib import Path

from psycopg.rows import dict_row

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.synth.card import render_card
from ehr_rwe_eln.synth.distribution import ReleaseUnavailable, record_export
from ehr_rwe_eln.synth.release import load_release

OUT = Path(__file__).resolve().parent.parent / "data" / "synth" / "exports"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=int, required=True)
    parser.add_argument("--recipient", required=True, help="the person or team receiving it")
    parser.add_argument("--contact", required=True, help="how to reach them if it is withdrawn")
    parser.add_argument("--purpose", required=True, help="what they will use it for")
    args = parser.parse_args()

    with DatabaseSettings().connect() as con:
        try:
            distribution_id = record_export(
                con, args.release, args.recipient, args.contact, args.purpose, ""
            )
        except ReleaseUnavailable as e:
            raise SystemExit(str(e)) from None
        folder = OUT / f"release_{args.release}_{distribution_id}"
        folder.mkdir(parents=True)
        load_release(con, args.release).to_csv(folder / "rows.csv", index=False)
        release = (
            con.cursor(row_factory=dict_row)
            .execute("SELECT * FROM synth.release WHERE release_id = %s", [args.release])
            .fetchone()
        )
        reports = dict(
            con.execute(
                "SELECT kind, report FROM synth.report WHERE release_id = %s", [args.release]
            ).fetchall()
        )
        (folder / "card.md").write_text(render_card(release, reports))
        con.execute(
            "UPDATE synth.distribution SET path = %s WHERE distribution_id = %s",
            [str(folder), distribution_id],
        )
        con.commit()
    print(f"release {args.release} exported to {folder} for {args.recipient} ({args.purpose})")


if __name__ == "__main__":
    main()
