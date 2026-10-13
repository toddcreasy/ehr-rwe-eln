import numpy as np
import pandas as pd
import pytest

from ehr_rwe_eln.tte.survival import _risk, analyze, estimate

from .test_tte import PROTOCOL


def test_kaplan_meier_matches_a_hand_calculation():
    days = pd.Series([1, 2, 2, 3, 4])
    event = pd.Series([1, 1, 0, 1, 0])
    # Day 1: 1 of 5 at risk -> 0.8. Day 2: the event counts before the tied censoring, 1 of 4 ->
    # 0.6. Day 3: 1 of 2 left -> 0.3. Day 4: censored, no change.
    risk = _risk(days, event, pd.Series(1.0, index=days.index), [1, 2, 3, 4])
    assert risk == pytest.approx([0.2, 0.4, 0.7, 0.7])


def test_a_weight_of_two_counts_like_two_people():
    days, event = pd.Series([1, 2, 3, 5]), pd.Series([1, 0, 1, 1])
    weighted = _risk(days, event, pd.Series([2.0, 1.0, 1.0, 1.0]), [1, 3, 5])
    doubled = _risk(
        pd.Series([1, 1, 2, 3, 5]),
        pd.Series([1, 1, 0, 1, 1]),
        pd.Series(1.0, index=range(5)),
        [1, 3, 5],
    )
    assert weighted == pytest.approx(doubled)


def confounded(n=2000, seed=1) -> pd.DataFrame:
    """Older people are more often treated and have more events. The true hazard ratio is 0.5."""
    rng = np.random.default_rng(seed)
    age = rng.normal(50, 10, n)
    male = rng.binomial(1, 0.5, n)
    arm = rng.binomial(1, 1 / (1 + np.exp(-0.08 * (age - 50))))
    hazard = 0.0004 * np.exp(0.06 * (age - 50)) * np.where(arm == 1, 0.5, 1.0)
    event_day = rng.exponential(1 / hazard)
    days = np.minimum(np.ceil(event_day), 1825)
    return pd.DataFrame(
        {
            "arm": arm,
            "age": age,
            "male": male,
            "days": days,
            "event": (event_day <= 1825).astype(int),
        }
    )


def protocol(replicates: int):
    return PROTOCOL.model_copy(
        update={"analysis": PROTOCOL.analysis.model_validate({"bootstrap_replicates": replicates})}
    )


def test_weighting_removes_the_confounding_and_recovers_the_true_hazard_ratio():
    result = analyze(confounded(), protocol(30))
    # Without adjustment the treated look worse than they are: they are older.
    assert result.crude.hazard_ratio > 0.6
    assert result.weighted.hazard_ratio == pytest.approx(0.5, abs=0.08)
    low, high = result.hazard_ratio_robust_ci
    assert low < 0.5 < high
    hr = result.bootstrap.loc["hazard_ratio"]
    assert hr["low"] < result.weighted.hazard_ratio < hr["high"]
    assert result.replicates_used == 30


def test_bootstrap_is_reproducible_with_the_seed():
    table = confounded(n=400)
    first, second = analyze(table, protocol(10)), analyze(table, protocol(10))
    pd.testing.assert_frame_equal(first.bootstrap, second.bootstrap)


def test_no_events_in_an_arm_gives_no_hazard_ratio():
    table = confounded(n=400)
    table.loc[table.arm == 0, "event"] = 0
    result = estimate(table, [365])
    assert result.hazard_ratio is None
    assert np.isnan(result.risks.risk_ratio[0])
