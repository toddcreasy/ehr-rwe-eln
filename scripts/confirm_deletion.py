"""Record that a recipient of a withdrawn release deleted it, or list who has not yet.

Usage:
    uv run python scripts/confirm_deletion.py
        lists every recipient of a withdrawn release who has not confirmed deletion
    uv run python scripts/confirm_deletion.py --export 3 --evidence "Dana's reply, 2026-11-20"
        records the confirmation for export 3 (the distribution_id; the list shows it)

The withdrawal notice asks each recipient to delete every copy and reply. This is where that
reply is recorded. Nothing is sent from here: a follow-up to anyone still listed is yours to
write and send.
"""

import argparse
from datetime import UTC, datetime

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.synth.distribution import ReleaseUnavailable, awaiting_deletion, confirm_deletion


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", type=int, help="the distribution_id to confirm")
    parser.add_argument("--evidence", help="how deletion was confirmed: whose reply, and when")
    args = parser.parse_args()
    if (args.export is None) != (args.evidence is None):
        parser.error("give --export and --evidence together, or neither to list")

    with DatabaseSettings().connect() as con:
        if args.export is not None:
            try:
                confirm_deletion(con, args.export, args.evidence)
            except (ReleaseUnavailable, ValueError) as e:
                raise SystemExit(str(e)) from None
            con.commit()
            print(f"export {args.export}: deletion confirmed")
        waiting = awaiting_deletion(con)

    if not waiting:
        print("every recipient of a withdrawn release has confirmed deletion")
        return
    print(f"{len(waiting)} export(s) of withdrawn releases with no deletion confirmed:")
    now = datetime.now(UTC)
    for w in waiting:
        days = (now - w["withdrawn_at"]).days
        print(
            f"  export {w['distribution_id']}: release {w['release_id']} to {w['recipient']}"
            f" <{w['contact']}>, withdrawn {days} day(s) ago"
        )


if __name__ == "__main__":
    main()
