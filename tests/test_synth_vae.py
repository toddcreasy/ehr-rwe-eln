import numpy as np
import pandas as pd
import pytest

from ehr_rwe_eln.synth import vae
from tests.test_synth import AGE, DRUG, FLAG, SBP, spec, toy


def vae_spec(epsilon, epochs=10, **kwargs):
    s = spec(
        *kwargs.pop("columns", (AGE, FLAG, DRUG)), releases=[{"method": "vae", "epsilon": epsilon}]
    )
    return s.model_copy(update={"vae": s.vae.model_copy(update={"epochs": epochs})})


def test_spend_stays_inside_the_budget_and_records_dp_sgd():
    s = vae_spec(1, epochs=2)
    out, spend = vae.synthesize(toy(2000), s, s.releases[0])
    count, sgd = spend
    assert count == {"mechanism": "geometric", "of": "row count", "epsilon": 0.01}
    assert sgd["mechanism"] == "dp_sgd" and sgd["delta"] == 1e-5 and sgd["epochs"] == 2
    assert sgd["noise_multiplier"] > 0 and sgd["steps"] > 0
    assert count["epsilon"] + sgd["epsilon"] <= 1
    assert abs(len(out) - 2000) < 1000  # noisy at epsilon 0.01


def test_values_stay_inside_the_spec_domains():
    s = vae_spec(1, epochs=2, columns=(AGE, FLAG, DRUG, SBP))
    table = toy(2000).assign(systolic_bp=120.0)
    out, _ = vae.synthesize(table, s, s.releases[0])
    assert list(out.columns) == ["age", "hypertension", "lisinopril", "systolic_bp"]
    assert out.age.between(0, 100).all()
    assert set(out.hypertension) <= {0, 1} and set(out.lisinopril) <= {0, 1}
    assert out.systolic_bp.dropna().between(70, 190).all()


def test_learns_the_relationship_with_a_large_budget():
    s = vae_spec(20, epochs=20)
    out, _ = vae.synthesize(toy(10_000), s, s.releases[0])
    given = out.groupby("hypertension").lisinopril.mean()
    assert given[1] - given[0] > 0.3  # source: 0.70 against 0.02


def test_same_seed_same_release():
    s, table = vae_spec(1, epochs=2), toy(2000)
    first, _ = vae.synthesize(table, s, s.releases[0])
    again, _ = vae.synthesize(table, s, s.releases[0])
    pd.testing.assert_frame_equal(first, again)


def test_vae_settings_are_validated():
    with pytest.raises(ValueError, match="less than 1"):
        spec(AGE).model_validate({**spec(AGE).model_dump(), "vae": {"delta": 2}})


def test_unseeded_vae_releases_are_refused():
    with pytest.raises(ValueError, match="vae releases need a seed"):
        spec(AGE, seed=None, releases=[{"method": "vae", "epsilon": 1}])


def conditioned(epsilon, epochs=2):
    s = vae_spec(epsilon, epochs=epochs)
    return s.model_copy(update={"vae": s.vae.model_copy(update={"condition": "age"})})


def test_a_condition_is_measured_with_noise_and_paid_for():
    s = conditioned(1)
    _, spend = vae.synthesize(toy(2000), s, s.releases[0])
    count, histogram, sgd = spend
    assert histogram == {"mechanism": "geometric", "of": "age histogram", "epsilon": 0.1}
    assert count["epsilon"] + histogram["epsilon"] + sgd["epsilon"] <= 1


def test_a_skewed_condition_keeps_its_share():
    # Few old people, unlike the rest: the shape DP-SGD tends to lose (unconditioned, this
    # release has 4.8% old people). Whether their other columns come out right is measured on
    # the real data by scripts/evaluate_synth.py, not here.
    rng = np.random.default_rng(2)
    n = 10_000
    age = np.where(rng.random(n) < 0.1, rng.integers(80, 100, n), rng.integers(20, 60, n))
    hypertension = (rng.random(n) < np.where(age >= 80, 0.8, 0.05)).astype(int)
    lisinopril = (rng.random(n) < np.where(hypertension == 1, 0.7, 0.02)).astype(int)
    table = pd.DataFrame({"age": age, "hypertension": hypertension, "lisinopril": lisinopril})
    s = conditioned(8, epochs=10)
    out, _ = vae.synthesize(table, s, s.releases[0])
    old = out.age >= 80
    assert abs(old.mean() - 0.1) < 0.02  # the share comes from the noisy histogram


def test_a_condition_must_be_a_column():
    with pytest.raises(ValueError, match="vae.condition height is not a column"):
        spec(AGE).model_validate({**spec(AGE).model_dump(), "vae": {"condition": "height"}})
