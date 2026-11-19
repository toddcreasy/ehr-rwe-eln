"""Exporting synthetic releases, withdrawing them, and watching them after release.

A release that leaves the database is recorded with who received it and why. A release from
controlled-access data goes only to the approved users its spec names, unless the spec cites
a DAC decision allowing wider sharing. If a flaw turns up later (a privacy attack that now
succeeds, a misrepresented group, a bug in the synthesizer), the release is withdrawn: it is
marked in the database with the reason, can no longer be exported, its data card says not to
use it, and a notice is drafted for everyone who received it. Notices are drafted, never
sent: a person reviews and sends them.

After release, scripts/evaluate_synth.py rescores every release, and privacy_flags names any
whose privacy attacks have moved more than halfway from chance toward what a plain copy of the
training data leaks. That is a trigger for review, not proof of a leak.
"""

from datetime import UTC, datetime

import psycopg

from ehr_rwe_eln.synth.release import code_version
from ehr_rwe_eln.synth.spec import Spec

# Withdrawal and export need these; the rest of the release record is not needed here.
RELEASE_SQL = """
SELECT release_id, spec_name, method, epsilon, created_at, withdrawn_at, withdrawn_reason, spec
FROM synth.release WHERE release_id = %s
"""


class ReleaseUnavailable(Exception):
    pass


def _release(con: psycopg.Connection, release_id: int) -> tuple:
    found = con.execute(RELEASE_SQL, [release_id]).fetchone()
    if found is None:
        raise ReleaseUnavailable(f"no synthetic release {release_id}")
    return found


def record_export(
    con: psycopg.Connection, release_id: int, recipient: str, contact: str, purpose: str, path: str
) -> int:
    """Record that a release went to a recipient. Refuses a withdrawn release, and a release
    from controlled data to anyone the data access request does not name."""
    found = _release(con, release_id)
    if found[5] is not None:
        raise ReleaseUnavailable(f"release {release_id} was withdrawn on {found[5]:%Y-%m-%d}")
    if not Spec.model_validate(found[7]).may_receive(recipient):
        raise ReleaseUnavailable(
            f"release {release_id} is derived from controlled data; {recipient} is not an approved"
            " user in its spec, and no DAC decision allows wider sharing"
        )
    return con.execute(
        "INSERT INTO synth.distribution (release_id, recipient, contact, purpose, path,"
        " exported_at, code_version) VALUES (%s, %s, %s, %s, %s, %s, %s)"
        " RETURNING distribution_id",
        [release_id, recipient, contact, purpose, path, datetime.now(UTC), code_version()],
    ).fetchone()[0]


def withdraw(con: psycopg.Connection, release_id: int, reason: str) -> list[dict]:
    """Mark a release withdrawn and return everyone it went to, oldest export first."""
    found = _release(con, release_id)
    if found[5] is not None:
        raise ReleaseUnavailable(
            f"release {release_id} was already withdrawn on {found[5]:%Y-%m-%d}"
        )
    if not reason.strip():
        raise ValueError("a withdrawal needs a reason")
    con.execute(
        "UPDATE synth.release SET withdrawn_at = %s, withdrawn_reason = %s WHERE release_id = %s",
        [datetime.now(UTC), reason.strip(), release_id],
    )
    rows = con.execute(
        "SELECT distribution_id, recipient, contact, purpose, path, exported_at"
        " FROM synth.distribution WHERE release_id = %s ORDER BY exported_at, distribution_id",
        [release_id],
    ).fetchall()
    keys = ["distribution_id", "recipient", "contact", "purpose", "path", "exported_at"]
    return [dict(zip(keys, row, strict=True)) for row in rows]


def notice(release_id: int, reason: str, distribution: dict) -> str:
    """A draft notice to one recipient of a withdrawn release, for a person to review and send."""
    return "\n".join(
        [
            f"To: {distribution['recipient']} <{distribution['contact']}>",
            f"Subject: Synthetic release {release_id} withdrawn",
            "",
            f"Synthetic release {release_id}, which you received on"
            f" {distribution['exported_at']:%Y-%m-%d} for {distribution['purpose']}, has been"
            " withdrawn.",
            "",
            f"Reason: {reason}",
            "",
            "Please stop using it, delete every copy you hold or made (including derived tables and"
            " models trained on it), and confirm by reply once that is done. Results already"
            " computed from it should be rechecked before anyone relies on them.",
            "",
        ]
    )


def privacy_flags(report: dict) -> list[str]:
    """Privacy checks in a stored privacy report that have moved more than halfway from chance
    toward what the plain copy of the training data shows."""
    copy = report.get("copy_of_training_data")
    if not copy:
        return []
    checks = [
        (
            "membership inference AUC",
            report["membership_inference"]["auc"],
            copy["membership_inference"]["auc"],
            0.5,
        ),
        (
            "synthetic rows nearer a training person",
            report["distance_to_closest_record"]["closer_to_member"],
            copy["distance_to_closest_record"]["closer_to_member"],
            0.5,
        ),
    ]
    flags = []
    for name, value, leak, chance in checks:
        limit = chance + (leak - chance) / 2
        if leak > chance and value > limit:
            flags.append(f"{name} {value:.3f}, past {limit:.3f} (chance {chance}, copy {leak:.3f})")
    return flags
