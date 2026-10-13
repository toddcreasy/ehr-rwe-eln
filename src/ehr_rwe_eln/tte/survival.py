"""Survival estimates: weighted Kaplan-Meier risks, risk differences and ratios, a weighted Cox
hazard ratio, and bootstrap confidence intervals.

A Kaplan-Meier curve is the share of people still free of the outcome over time, accounting for
people whose follow-up ended early (censoring). One minus the curve at a given day is the risk by
that day; comparing the arms' risks gives the risk difference and risk ratio a trial reports. A
Cox model summarizes the gap between the curves as one hazard ratio, the ratio of the arms'
instantaneous outcome rates, assumed constant over time. Weighting by the propensity weights
estimates what would have happened had both arms had the same covariate mix.

Confidence intervals come from the bootstrap: resample people with replacement, rerun everything
from the propensity score on, and take the middle 95% of the results. That carries the propensity
model's own uncertainty, which formulas applied to the weighted data would leave out.
"""

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from lifelines import CoxPHFitter, KaplanMeierFitter
from lifelines.exceptions import StatisticalWarning

from ehr_rwe_eln.tte.propensity import NotEstimable, fit_propensity
from ehr_rwe_eln.tte.protocol import Protocol


@dataclass
class Estimates:
    # One row per reporting day: each arm's risk, their difference, and their ratio.
    risks: pd.DataFrame
    # None when an arm has no events: the ratio of rates is then 0 or infinite.
    hazard_ratio: float | None


@dataclass
class Survival:
    crude: Estimates
    weighted: Estimates
    # Weighted Cox hazard ratio interval from the robust (sandwich) standard error.
    hazard_ratio_robust_ci: tuple[float, float] | None
    # 95% percentile bootstrap intervals for the weighted estimates.
    bootstrap: pd.DataFrame
    replicates_used: int
    replicates_not_estimable: int


def _risk(days: pd.Series, event: pd.Series, weights: pd.Series, at: list[int]) -> np.ndarray:
    with warnings.catch_warnings():
        # lifelines warns that weighted Greenwood intervals are off; ours come from the bootstrap.
        warnings.simplefilter("ignore", StatisticalWarning)
        fit = KaplanMeierFitter().fit(days, event, weights=weights)
    return 1 - fit.survival_function_at_times(at).to_numpy()


def estimate(table: pd.DataFrame, at: list[int], weight: str | None = None) -> Estimates:
    w = table[weight] if weight else pd.Series(1.0, index=table.index)
    treated, control = table["arm"] == 1, table["arm"] == 0
    risk_t = _risk(table.days[treated], table.event[treated], w[treated], at)
    risk_c = _risk(table.days[control], table.event[control], w[control], at)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(risk_c > 0, risk_t / risk_c, np.nan)
    risks = pd.DataFrame(
        {
            "day": at,
            "risk_treatment": risk_t,
            "risk_comparator": risk_c,
            "risk_difference": risk_t - risk_c,
            "risk_ratio": ratio,
        }
    )
    hazard_ratio = None
    if table.event[treated].sum() and table.event[control].sum():
        hazard_ratio = float(np.exp(_cox(table, w).params_["arm"]))
    return Estimates(risks, hazard_ratio)


def _cox(table: pd.DataFrame, weights: pd.Series, robust: bool = False) -> CoxPHFitter:
    data = table[["days", "event", "arm"]].assign(w=weights.to_numpy())
    with warnings.catch_warnings():
        # Non-integer weights are expected with inverse probability weighting.
        warnings.simplefilter("ignore", StatisticalWarning)
        return CoxPHFitter().fit(
            data, duration_col="days", event_col="event", weights_col="w", robust=robust
        )


def analyze(table: pd.DataFrame, protocol: Protocol) -> Survival:
    """Crude and weighted estimates with bootstrap intervals. The table needs its covariates."""
    at = protocol.analysis.risk_days
    weighted_table = fit_propensity(table, protocol).table
    weighted = estimate(weighted_table, at, "weight")

    robust_ci = None
    if weighted.hazard_ratio is not None:
        cox = _cox(weighted_table, weighted_table["weight"], robust=True)
        low, high = cox.confidence_intervals_.loc["arm"]
        robust_ci = (float(np.exp(low)), float(np.exp(high)))

    rng = np.random.default_rng(protocol.analysis.seed)
    replicates, not_estimable = [], 0
    for _ in range(protocol.analysis.bootstrap_replicates):
        sample = table.iloc[rng.integers(0, len(table), len(table))].reset_index(drop=True)
        try:
            result = estimate(fit_propensity(sample, protocol).table, at, "weight")
        except NotEstimable:
            # A resample can lose all of one covariate pattern; it holds no comparison.
            not_estimable += 1
            continue
        risks = result.risks.set_index("day")
        replicates.append(
            {
                **{f"{c}_{d}": risks.loc[d, c] for d in at for c in risks.columns},
                "hazard_ratio": result.hazard_ratio,
            }
        )
    draws = pd.DataFrame(replicates, dtype=float)
    bootstrap = pd.DataFrame(
        {"low": draws.quantile(0.025), "high": draws.quantile(0.975)}
        if len(draws)
        else {"low": [], "high": []}
    )
    return Survival(
        crude=estimate(table, at),
        weighted=weighted,
        hazard_ratio_robust_ci=robust_ci,
        bootstrap=bootstrap,
        replicates_used=len(replicates),
        replicates_not_estimable=not_estimable,
    )
