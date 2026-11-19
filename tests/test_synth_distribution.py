import pytest

from ehr_rwe_eln.synth.bayes_net import plan, synthesize
from ehr_rwe_eln.synth.card import render_card
from ehr_rwe_eln.synth.distribution import (
    ReleaseUnavailable,
    notice,
    privacy_flags,
    record_export,
    withdraw,
)
from ehr_rwe_eln.synth.release import save_release

from .test_synth import AGE, DRUG, FLAG, spec, toy
from .test_synth_card import release_record


@pytest.fixture
def release_id(pg, dq_schema):
    s = spec(AGE, FLAG, DRUG)
    train = toy(1000)
    out, measurements = synthesize(train, s, s.releases[0])
    return save_release(pg, s, s.releases[0], plan(measurements), out, len(train), 0)


def test_withdrawal_names_every_recipient_and_stops_exports(pg, release_id):
    record_export(pg, release_id, "Pipeline team", "team@example.org", "pipeline tests", "a")
    record_export(pg, release_id, "Dana", "dana@example.org", "a demo", "b")
    recipients = withdraw(pg, release_id, "membership inference no longer at chance")
    assert [r["recipient"] for r in recipients] == ["Pipeline team", "Dana"]
    reason = pg.execute(
        "SELECT withdrawn_reason FROM synth.release WHERE release_id = %s", [release_id]
    ).fetchone()[0]
    assert reason == "membership inference no longer at chance"
    with pytest.raises(ReleaseUnavailable, match="was withdrawn"):
        record_export(pg, release_id, "Late", "late@example.org", "anything", "c")
    with pytest.raises(ReleaseUnavailable, match="already withdrawn"):
        withdraw(pg, release_id, "again")


def test_withdrawal_needs_a_reason_and_a_release(pg, release_id):
    with pytest.raises(ValueError, match="needs a reason"):
        withdraw(pg, release_id, "  ")
    with pytest.raises(ReleaseUnavailable, match="no synthetic release"):
        withdraw(pg, 999_999, "gone")


def test_notice_tells_the_recipient_what_to_do(pg, release_id):
    record_export(pg, release_id, "Dana", "dana@example.org", "a demo", "b")
    (recipient,) = withdraw(pg, release_id, "a bug in the synthesizer")
    text = notice(release_id, "a bug in the synthesizer", recipient)
    assert text.startswith("To: Dana <dana@example.org>")
    assert f"Synthetic release {release_id}" in text and "for a demo" in text
    assert "Reason: a bug in the synthesizer" in text
    assert "delete every copy" in text


def test_card_of_a_withdrawn_release_says_so_first():
    s = spec(AGE, FLAG, DRUG)
    out, measurements = synthesize(toy(1000), s, s.releases[0])
    record = release_record(s, s.releases[0], measurements, len(out), 0)
    assert "Withdrawn" not in render_card(record, {})
    record |= {"withdrawn_at": record["created_at"], "withdrawn_reason": "a bug."}
    lines = render_card(record, {}).splitlines()
    assert lines[2] == (
        "**Withdrawn 2026-10-13: a bug.** Do not use this release. Delete every copy, and recheck"
        " any result computed from it."
    )


def privacy(auc: float, nearer: float) -> dict:
    return {
        "membership_inference": {"auc": auc},
        "distance_to_closest_record": {"closer_to_member": nearer},
        "copy_of_training_data": {
            "membership_inference": {"auc": 0.65},
            "distance_to_closest_record": {"closer_to_member": 0.63},
        },
    }


def test_privacy_flags_fire_only_past_halfway_to_the_copy():
    assert privacy_flags(privacy(0.51, 0.51)) == []
    assert privacy_flags(privacy(0.574, 0.56)) == []  # limits are 0.575 and 0.565
    flags = privacy_flags(privacy(0.60, 0.58))
    assert len(flags) == 2 and flags[0].startswith("membership inference AUC 0.600, past 0.575")
    assert privacy_flags({"membership_inference": {"auc": 0.9}}) == []  # no copy to compare
