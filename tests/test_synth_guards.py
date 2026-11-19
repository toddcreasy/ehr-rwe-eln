"""The real-data guards (docs/nih_hhs_requirements.md, items 2 and 7): a controlled-access source
runs the privacy attacks only with approval, and its releases go only to approved users."""

import pytest
from pydantic import ValidationError

from ehr_rwe_eln.synth.bayes_net import plan, synthesize
from ehr_rwe_eln.synth.card import render_card
from ehr_rwe_eln.synth.distribution import ReleaseUnavailable, record_export
from ehr_rwe_eln.synth.privacy import AttacksNotApproved, privacy_report
from ehr_rwe_eln.synth.release import save_release
from ehr_rwe_eln.synth.spec import Spec

from .test_synth import AGE, DRUG, FLAG, spec, toy
from .test_synth_card import release_record


def controlled(**fields) -> Spec:
    base = spec(AGE, FLAG, DRUG).model_dump() | {"source_access": "controlled", "seed": None}
    return Spec(**base | {"approved_users": ["Lab A"]} | fields)


def test_every_spec_must_say_where_its_source_comes_from():
    fields = spec(AGE).model_dump()
    del fields["source_access"]
    with pytest.raises(ValidationError, match="source_access"):
        Spec(**fields)


def test_a_controlled_source_refuses_a_seed_and_needs_approved_users():
    with pytest.raises(ValidationError, match="leave seed unset"):
        controlled(seed=0)
    with pytest.raises(ValidationError, match="approved_users"):
        controlled(approved_users=[])
    assert controlled(approved_users=[], dac_sharing_approval="DAC letter 2027-01").may_receive("x")


def test_who_may_receive_a_release():
    assert spec(AGE).may_receive("anyone")  # synthetic sources have no participants
    s = controlled()
    assert s.may_receive("Lab A") and not s.may_receive("Lab B")


def test_attacks_on_a_controlled_source_need_approval():
    train, holdout = toy(600, 1), toy(300, 2)
    with pytest.raises(AttacksNotApproved, match="attack_approval"):
        privacy_report(train, holdout, train, controlled())
    approved = controlled(attack_approval="Data access request 12345, section 4")
    assert "membership_inference" in privacy_report(train, holdout, train, approved)


def test_export_of_a_controlled_release_goes_only_to_approved_users(pg, dq_schema):
    s = controlled()
    out, measurements = synthesize(toy(1000), s, s.releases[0])
    release_id = save_release(pg, s, s.releases[0], plan(measurements), out, 1000, 0)
    assert record_export(pg, release_id, "Lab A", "a@example.org", "pipeline tests", "p") > 0
    with pytest.raises(ReleaseUnavailable, match="Lab B is not an approved user"):
        record_export(pg, release_id, "Lab B", "b@example.org", "a demo", "p")


def test_card_states_the_sharing_rule_and_why_attacks_did_not_run():
    s = controlled(approved_users=["Lab A", "Lab C"])
    out, measurements = synthesize(toy(1000), s, s.releases[0])
    record = release_record(s, s.releases[0], measurements, len(out), 300, seed=None)
    card = render_card(record, {})
    assert "named in the data access request (Lab A, Lab C)" in card
    assert "unless the DAC approves wider sharing." in card
    assert "the data access request has not approved them" in card
    synthetic = release_record(spec(AGE, FLAG, DRUG), s.releases[0], measurements, len(out), 300)
    assert "approved users" not in render_card(synthetic, {})
