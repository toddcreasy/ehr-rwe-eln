import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from ehr_rwe_eln.synth.parity import load_trial, parity_report, repeated_draws, trial_estimate
from ehr_rwe_eln.synth.source import build_source
from ehr_rwe_eln.synth.spec import SPECS, Spec, load_spec
from tests.test_synth import AGE, spec
from tests.test_tte import PROTOCOL as TTE_PROTOCOL
from tests.test_tte import con  # noqa: F401  (module 4's planted cohort)

PROTOCOL = load_trial("lisinopril_vs_amlodipine_ckd")


def analysis_table(n=3000, effect=1.0, seed=0) -> pd.DataFrame:
    """A trial table with the protocol's covariates; the outcome rate is scaled by effect in
    the treated arm."""
    rng = np.random.default_rng(seed)
    table = pd.DataFrame(
        {
            "age": rng.integers(30, 85, n),
            "male": rng.integers(0, 2, n),
            **{c.name: rng.integers(0, 2, n) for c in PROTOCOL.covariates.conditions},
            **{c.name: rng.normal(100, 10, n) for c in PROTOCOL.covariates.measurements},
            "arm": rng.integers(0, 2, n),
        }
    )
    rate = np.where(table.arm == 1, effect, 1.0) / 2000
    event_day = rng.exponential(1 / rate)
    table["days"] = np.minimum(event_day, 1825).astype(int) + 1
    table["event"] = (event_day < 1825).astype(int)
    return table


def test_trial_estimate_recovers_a_planted_effect():
    harm = trial_estimate(analysis_table(effect=2.0), PROTOCOL)
    assert harm["hazard_ratio"] == pytest.approx(2.0, rel=0.25)
    assert harm["robust_ci"][0] > 1
    assert harm["not_estimable"] is None


def test_trial_estimate_reports_not_estimable():
    table = analysis_table()
    table["diabetes"] = table["arm"]  # perfectly separates the arms
    result = trial_estimate(table, PROTOCOL)
    assert result["hazard_ratio"] is None and "diabetes" in result["not_estimable"]


def test_repeated_draws_count_coverage_and_spurious_effects():
    real = trial_estimate(analysis_table(effect=1.0, seed=1), PROTOCOL)
    assert real["robust_ci"][0] < 1 < real["robust_ci"][1]
    s = spec(AGE)

    def null(train, spec, release):  # draws with no effect, like the real data
        return analysis_table(effect=1.0, seed=spec.seed), []

    def harmful(train, spec, release):  # draws that invent a strong effect
        return analysis_table(effect=3.0, seed=spec.seed), []

    faithful = repeated_draws(None, s, s.releases[0], PROTOCOL, null, real, draws=5)
    assert faithful["estimable"] == 1 and faithful["spurious_effect"] <= 0.2
    wrong = repeated_draws(None, s, s.releases[0], PROTOCOL, harmful, real, draws=5)
    assert wrong["spurious_effect"] == 1 and wrong["covers_real"] == 0
    assert wrong["hazard_ratio_median"] > 2
    report = parity_report(real, real, faithful)
    assert report["release_covers_real"]


def test_the_shipped_trial_spec_loads():
    s = load_spec(SPECS / "trial_lisinopril_amlodipine_ckd.yaml")
    assert s.protocol == "lisinopril_vs_amlodipine_ckd" and s.holdout_fraction == 0
    names = {c.name for c in s.columns}
    covariates = {c.name for c in PROTOCOL.covariates.conditions + PROTOCOL.covariates.measurements}
    assert covariates | {"age", "male", "arm", "days", "event"} == names


def test_protocol_and_analysis_columns_go_together():
    with pytest.raises(ValidationError, match="every column is an analysis column"):
        Spec.model_validate({**spec(AGE).model_dump(), "protocol": "lisinopril_vs_amlodipine_ckd"})


def test_analysis_source_takes_the_protocol_table(con, monkeypatch):  # noqa: F811
    """con and its protocol come from module 4's tests: 11 planted people, 4 eligible."""
    monkeypatch.setattr("ehr_rwe_eln.synth.source.load_protocol", lambda path: TTE_PROTOCOL)
    columns = [
        {"name": "age", "analysis": "age", "numeric": {"low": 0, "high": 110, "bins": 11}},
        {"name": "treated", "analysis": "arm", "categories": [0, 1]},
        {"name": "days", "analysis": "days", "numeric": {"low": 0, "high": 2000, "bins": 10}},
        {"name": "event", "analysis": "event", "categories": [0, 1]},
    ]
    s = Spec.model_validate(
        {**spec(AGE).model_dump(), "protocol": "any", "holdout_fraction": 0, "columns": columns}
    )
    source = build_source(con, s)
    assert list(source.columns) == ["age", "treated", "days", "event"]
    assert source.index.name == "person_id" and source.index.is_monotonic_increasing
    assert len(source) == 4
