"""Withdraw a synthetic release and draft a notice for everyone who received it.

Usage: uv run python scripts/withdraw_release.py --release 5 --reason "what is wrong with it"

Marks the release withdrawn in synth.release, rewrites its data card in data/synth/cards/ with
the withdrawal at the top, and writes one draft notice per recipient to
data/synth/withdrawals/release_<id>/. Nothing is sent: review the notices and send them
yourself, and record each recipient's reply with scripts/confirm_deletion.py. The release's
record and reports stay, so the decision can be reviewed later.
"""

import argparse
from pathlib import Path

from psycopg.rows import dict_row

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.synth.card import render_card
from ehr_rwe_eln.synth.distribution import ReleaseUnavailable, notice, withdraw

DATA = Path(__file__).resolve().parent.parent / "data" / "synth"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", type=int, required=True)
    parser.add_argument("--reason", required=True, help="what is wrong, for the card and notices")
    args = parser.parse_args()

    with DatabaseSettings().connect() as con:
        try:
            recipients = withdraw(con, args.release, args.reason)
        except (ReleaseUnavailable, ValueError) as e:
            raise SystemExit(str(e)) from None
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
        cards = DATA / "cards"
        cards.mkdir(parents=True, exist_ok=True)
        (cards / f"release_{args.release}.md").write_text(render_card(release, reports))
        folder = DATA / "withdrawals" / f"release_{args.release}"
        folder.mkdir(parents=True, exist_ok=True)
        for r in recipients:
            path = folder / f"notice_{r['distribution_id']}.txt"
            path.write_text(notice(args.release, release["withdrawn_reason"], r))
        con.commit()

    print(f"release {args.release} withdrawn: {release['withdrawn_reason']}")
    if recipients:
        print(f"{len(recipients)} recipient(s); draft notices in {folder} (not sent):")
        for r in recipients:
            print(
                f"  export {r['distribution_id']}: {r['recipient']} <{r['contact']}>,"
                f" exported {r['exported_at']:%Y-%m-%d}"
            )
        print("record each reply with scripts/confirm_deletion.py --export <id> --evidence ...")
    else:
        print("it was never exported, so there is no one to notify")


if __name__ == "__main__":
    main()
