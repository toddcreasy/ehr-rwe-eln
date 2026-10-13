"""Propensity scores, inverse probability of treatment weights, and covariate balance.

The propensity score is each person's estimated probability of starting the treatment strategy
rather than the comparator, given their baseline covariates, from an unpenalized logistic
regression. Weighting each person by the inverse of the probability of the arm they actually
started makes the two arms resemble each other on those covariates, as randomization would.
Stabilized weights multiply by the arm's overall share, so they average near 1 and the weighted
sample keeps about its real size. Balance is checked with standardized mean differences (SMD),
before and after weighting; below 0.1 is the usual threshold for balanced.
"""

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tools.sm_exceptions import ConvergenceWarning, PerfectSeparationWarning

from ehr_rwe_eln.tte.protocol import Protocol

BALANCED = 0.1
# A 0/1 covariate whose less common value fewer people than this have, across both arms, is
# dropped: the model cannot estimate its effect and chases it toward infinity instead.
MIN_PERSONS = 5


class NotEstimable(Exception):
    """The arms do not overlap: some covariate pattern only ever gets one strategy, so the data
    hold no comparison for those people and no adjustment can create one (positivity fails)."""


@dataclass
class Propensity:
    # The analysis table with ps (propensity score) and weight columns added.
    table: pd.DataFrame
    # Coefficients, standard errors, and p values of the logistic regression.
    coefficients: pd.DataFrame
    # One row per covariate: SMD before and after weighting.
    balance: pd.DataFrame
    # Overlap and weight summaries for the positivity check.
    diagnostics: dict


def design_matrix(table: pd.DataFrame, protocol: Protocol) -> tuple[pd.DataFrame, dict[str, str]]:
    """The covariates as model inputs, and the columns dropped with the reason. A missing
    measurement becomes the mean of the observed values plus a 0/1 column saying it was missing,
    so missingness itself can carry information."""
    columns = ["age", "male", *(c.name for c in protocol.covariates.conditions)]
    x = table[columns].astype(float)
    missing = {}
    for covariate in protocol.covariates.measurements:
        values = table[covariate.name]
        x[covariate.name] = values.fillna(values.mean())
        indicator = covariate.missing_indicator or f"{covariate.name}_missing"
        missing[indicator] = missing.get(indicator, False) | values.isna()
    for indicator, isna in missing.items():
        if isna.any():
            x[indicator] = isna.astype(float)

    dropped = {}
    # A column with one value carries no information and makes the model unsolvable.
    for c in x.columns[x.nunique() <= 1]:
        dropped[c] = "one value"
    binary = [c for c in x.columns if c not in dropped and set(x[c].unique()) <= {0, 1}]
    for c in binary:
        if min((x[c] == 1).sum(), (x[c] == 0).sum()) < MIN_PERSONS:
            dropped[c] = f"fewer than {MIN_PERSONS} persons with one of its values"
    # Two identical columns make the model unsolvable too; keep the first.
    kept = x.drop(columns=list(dropped))
    for c in kept.columns[kept.T.duplicated()]:
        dropped[c] = "same values as an earlier column"
    return x.drop(columns=list(dropped)), dropped


def smd(x: pd.Series, arm: pd.Series, weights: pd.Series | None = None) -> float:
    """Difference in (weighted) means over the pooled standard deviation of the unweighted arms.
    The denominator stays unweighted so before and after compare on the same scale."""
    w = pd.Series(1.0, index=x.index) if weights is None else weights
    treated, control = arm == 1, arm == 0
    mean_t = np.average(x[treated], weights=w[treated])
    mean_c = np.average(x[control], weights=w[control])
    pooled_sd = np.sqrt((x[treated].var() + x[control].var()) / 2)
    return 0.0 if pooled_sd == 0 else float((mean_t - mean_c) / pooled_sd)


def effective_sample_size(weights: pd.Series) -> float:
    """Kish's effective sample size: how many unweighted people the weighted ones are worth."""
    return float(weights.sum() ** 2 / (weights**2).sum())


def fit_propensity(table: pd.DataFrame, protocol: Protocol) -> Propensity:
    x, dropped = design_matrix(table, protocol)
    arm = table["arm"]
    # A covariate with one value in each arm, different between them, predicts the arm exactly.
    separating = [
        c
        for c in x.columns
        if x.loc[arm == 1, c].nunique() == 1
        and x.loc[arm == 0, c].nunique() == 1
        and x.loc[arm == 1, c].iloc[0] != x.loc[arm == 0, c].iloc[0]
    ]
    if separating:
        raise NotEstimable(f"these covariates alone decide the arm: {', '.join(separating)}")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PerfectSeparationWarning)
            # Checked below, so the message names the cause.
            warnings.simplefilter("ignore", ConvergenceWarning)
            model = sm.Logit(arm, sm.add_constant(x)).fit(disp=False)
    except (PerfectSeparationWarning, np.linalg.LinAlgError) as exc:
        raise NotEstimable(f"the covariates together predict the arm exactly ({exc})") from exc
    if not model.mle_retvals["converged"]:
        # Some coefficient keeps growing to push a group of people toward a score of 0 or 1.
        raise NotEstimable("the covariates together nearly predict the arm (no convergence)")
    ps = model.predict(sm.add_constant(x))

    share = arm.mean()
    weight = pd.Series(np.where(arm == 1, share / ps, (1 - share) / (1 - ps)), index=table.index)
    cut = protocol.analysis.truncate_percentile / 100
    weight = weight.clip(weight.quantile(cut), weight.quantile(1 - cut))

    out = table.assign(ps=ps, weight=weight)
    balance = pd.DataFrame(
        {
            "covariate": x.columns,
            "smd_before": [smd(x[c], arm) for c in x.columns],
            "smd_after": [smd(x[c], arm, weight) for c in x.columns],
        }
    )
    coefficients = pd.DataFrame(
        {"coefficient": model.params, "std_error": model.bse, "p_value": model.pvalues}
    )
    diagnostics = {
        "ps_range_treatment": (float(ps[arm == 1].min()), float(ps[arm == 1].max())),
        "ps_range_comparator": (float(ps[arm == 0].min()), float(ps[arm == 0].max())),
        # Near 0 or 1, a person has almost no chance of the other arm: positivity is strained.
        "share_ps_outside_0.05_0.95": float(((ps < 0.05) | (ps > 0.95)).mean()),
        "weight_min": float(weight.min()),
        "weight_max": float(weight.max()),
        "weight_mean": float(weight.mean()),
        "effective_n_treatment": effective_sample_size(weight[arm == 1]),
        "effective_n_comparator": effective_sample_size(weight[arm == 0]),
        "covariates_unbalanced_after": int((balance["smd_after"].abs() >= BALANCED).sum()),
        "covariates_dropped": dropped,
    }
    return Propensity(out, coefficients, balance, diagnostics)
