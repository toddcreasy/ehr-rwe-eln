import numpy as np
import pandas as pd
import pytest

from ehr_rwe_eln.tte.propensity import NotEstimable, design_matrix, fit_propensity, smd
from ehr_rwe_eln.tte.protocol import Protocol

from .test_tte import PROTOCOL


def protocol(**analysis) -> Protocol:
    return PROTOCOL.model_copy(
        update={
            "covariates": PROTOCOL.covariates.model_validate(
                {"measurements": [{"name": "lab", "measurements": {"concept_ids": [1]}}]}
            ),
            "analysis": PROTOCOL.analysis.model_validate(analysis),
        }
    )


def simulated(n=4000, seed=0) -> pd.DataFrame:
    """Older people and men are more likely to get the treatment: confounded, with overlap."""
    rng = np.random.default_rng(seed)
    age = rng.normal(50, 10, n)
    male = rng.binomial(1, 0.4, n)
    logit = -0.3 + 0.08 * (age - 50) + 0.7 * male
    arm = rng.binomial(1, 1 / (1 + np.exp(-logit)))
    return pd.DataFrame({"arm": arm, "age": age, "male": male, "lab": rng.normal(7, 1, n)})


def test_propensity_model_recovers_the_assignment_and_weighting_balances():
    result = fit_propensity(simulated(), protocol(truncate_percentile=0))
    coef, se = result.coefficients["coefficient"], result.coefficients["std_error"]
    assert abs(coef["age"] - 0.08) < 3 * se["age"]
    assert abs(coef["male"] - 0.7) < 3 * se["male"]
    balance = result.balance.set_index("covariate")
    assert abs(balance.loc["age", "smd_before"]) > 0.3
    assert balance["smd_after"].abs().max() < 0.05
    # Stabilized weights average near 1.
    assert abs(result.diagnostics["weight_mean"] - 1) < 0.05


def test_stabilized_weights_and_truncation():
    table = simulated()
    exact = fit_propensity(table, protocol(truncate_percentile=0)).table
    share = table["arm"].mean()
    expected = np.where(exact.arm == 1, share / exact.ps, (1 - share) / (1 - exact.ps))
    assert np.allclose(exact.weight, expected)
    clipped = fit_propensity(table, protocol(truncate_percentile=5)).table.weight
    assert clipped.min() == pytest.approx(np.quantile(expected, 0.05))
    assert clipped.max() == pytest.approx(np.quantile(expected, 0.95))


def test_missing_measurement_becomes_the_mean_plus_an_indicator():
    table = simulated(n=20)
    table.loc[:5, "lab"] = np.nan
    x, _ = design_matrix(table, protocol())
    observed = table["lab"].dropna().mean()
    assert x.loc[:5, "lab"].tolist() == [observed] * 6
    assert x["lab_missing"].tolist() == [1] * 6 + [0] * 14


def test_measurements_can_share_a_missing_indicator():
    table = simulated(n=20).assign(bp=120.0)
    table.loc[:5, "lab"] = np.nan
    table.loc[4:9, "bp"] = np.nan
    shared = PROTOCOL.covariates.model_validate(
        {
            "measurements": [
                {
                    "name": n,
                    "measurements": {"concept_ids": [1]},
                    "missing_indicator": "vitals_missing",
                }
                for n in ("lab", "bp")
            ]
        }
    )
    x, _ = design_matrix(table, PROTOCOL.model_copy(update={"covariates": shared}))
    assert x["vitals_missing"].tolist() == [1] * 10 + [0] * 10
    assert "lab_missing" not in x and "bp_missing" not in x


def test_rare_and_duplicate_columns_are_dropped():
    table = simulated(n=200).assign(lab_copy=0.0)
    table["lab_copy"] = table["lab"]
    table.loc[:3, "lab"] = np.nan  # 4 persons missing: too few to estimate
    table.loc[:3, "lab_copy"] = np.nan
    table.loc[100:129, "lab_copy"] = np.nan
    both = PROTOCOL.covariates.model_validate(
        {
            "measurements": [
                {"name": "lab", "measurements": {"concept_ids": [1]}},
                {"name": "lab_copy", "measurements": {"concept_ids": [1]}},
            ]
        }
    )
    x, dropped = design_matrix(table, PROTOCOL.model_copy(update={"covariates": both}))
    assert set(dropped) == {"lab_missing"}
    assert "lab_copy_missing" in x

    table["lab_copy"] = table["lab"]
    x, dropped = design_matrix(table, PROTOCOL.model_copy(update={"covariates": both}))
    assert dropped["lab_copy"] == "same values as an earlier column"
    assert "lab" in x and "lab_copy" not in x


def test_a_covariate_that_decides_the_arm_is_not_estimable():
    table = simulated(n=200)
    table["male"] = table["arm"]
    with pytest.raises(NotEstimable, match="male"):
        fit_propensity(table, protocol())


def test_a_covariate_that_nearly_decides_the_arm_is_not_estimable():
    table = simulated(n=200)
    table["male"] = table["arm"]
    table.loc[table.index[table.arm == 0][:5], "male"] = 1
    with pytest.raises(NotEstimable, match="nearly"):
        fit_propensity(table, protocol())


def test_smd_uses_the_unweighted_pooled_sd():
    x = pd.Series([0.0, 2.0, 1.0, 3.0])
    arm = pd.Series([0, 0, 1, 1])
    # Means 1 and 2; each arm's variance is 2, so the pooled SD is sqrt(2).
    assert smd(x, arm) == pytest.approx(1 / np.sqrt(2))
    assert smd(x, arm, pd.Series([1.0, 1.0, 3.0, 1.0])) == pytest.approx(0.5 / np.sqrt(2))
