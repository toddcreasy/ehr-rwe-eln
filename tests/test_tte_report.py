import pytest

from ehr_rwe_eln.tte import report
from ehr_rwe_eln.tte.propensity import NotEstimable
from ehr_rwe_eln.tte.protocol import PROTOCOLS, Outcome, load_protocol
from ehr_rwe_eln.tte.report import NegativeControl, build_report, negative_control

from .test_tte import PROTOCOL, con  # noqa: F401  (con is a fixture)

UNUSED = 920099


def test_a_negative_control_applies_its_own_eligibility(con):  # noqa: F811
    # Nobody has UNUSED, so the person the real outcome excludes for a prior outcome is back.
    outcome = Outcome.model_validate({"name": "nc", "conditions": {"concept_ids": [UNUSED]}})
    result = negative_control(con, PROTOCOL, outcome)
    assert (result.persons, result.events, result.hazard_ratio) == (5, 0, None)


def test_the_report_stops_at_not_estimable(con, monkeypatch):  # noqa: F811
    def not_estimable(table, protocol):
        raise NotEstimable("no overlap")

    monkeypatch.setattr(report, "fit_propensity", not_estimable)
    protocol = PROTOCOL.model_copy(
        update={
            "negative_controls": [
                Outcome.model_validate({"name": "nc", "conditions": {"concept_ids": [UNUSED]}})
            ]
        }
    )
    result = build_report(con, protocol)
    assert result.not_estimable == "no overlap"
    assert result.attrition[-1] == ("no outcome on or before time zero", 4)
    assert [(a.name, a.persons, a.events) for a in result.arms] == [("a", 2, 1), ("b", 2, 0)]
    assert result.survival is None and result.negative_controls == []
    assert report.read_trial(con, protocol)[2] == []


@pytest.mark.parametrize(
    ("ci", "flagged"), [((0.8, 1.2), False), ((1.0, 1.5), False), ((1.1, 1.5), True), (None, False)]
)
def test_a_negative_control_is_flagged_when_its_interval_excludes_1(ci, flagged):
    assert NegativeControl("nc", 10, 2, 1.3, ci).excludes_null is flagged


def test_shipped_negative_controls_are_not_the_outcome():
    for path in PROTOCOLS.glob("*.yaml"):
        protocol = load_protocol(path)
        outcome = set(protocol.outcome.conditions.concept_ids)
        assert protocol.negative_controls
        for control in protocol.negative_controls:
            assert not outcome & set(control.conditions.concept_ids)
