"""Downstream parity: run a module 4 trial's own analysis on a synthetic analysis table and set
the result beside the same analysis on the real table.

The analysis is module 4's, unchanged: propensity score weights, then a weighted Cox model for
the hazard ratio of the treatment arm, with a robust 95% interval. Bootstrap intervals are
skipped (as for negative controls): the robust interval is enough to compare.

Parity is judged over repeated draws, not one release: with few events, a single synthetic
table varies like a fresh small sample. Each draw is made with its own seed and asked:

- Is it estimable at all? A table the pipeline cannot run on is no use for prototyping it.
- Does its interval cover the real hazard ratio?
- Does it show a spurious effect: an interval that excludes 1 when the real interval does not?
  That is a confident wrong answer, the outcome most to be avoided.
"""

from collections.abc import Callable

import numpy as np
import pandas as pd

from ehr_rwe_eln.synth.spec import Release, Spec
from ehr_rwe_eln.tte.propensity import NotEstimable
from ehr_rwe_eln.tte.protocol import PROTOCOLS, Protocol, load_protocol
from ehr_rwe_eln.tte.survival import analyze, estimate

DRAWS = 20


def load_trial(name: str) -> Protocol:
    protocol = load_protocol(PROTOCOLS / f"{name}.yaml")
    return protocol.model_copy(
        update={"analysis": protocol.analysis.model_copy(update={"bootstrap_replicates": 0})}
    )


def trial_estimate(table: pd.DataFrame, protocol: Protocol) -> dict:
    treated = table["arm"] == 1
    out = {
        "persons": len(table),
        "treated": int(treated.sum()),
        "events_treated": int(table.event[treated].sum()),
        "events_comparator": int(table.event[~treated].sum()),
        "crude_hazard_ratio": estimate(table, protocol.analysis.risk_days).hazard_ratio,
        "hazard_ratio": None,
        "robust_ci": None,
        "not_estimable": None,
    }
    try:
        survival = analyze(table, protocol)
    except NotEstimable as exc:
        out["not_estimable"] = str(exc)
        return out
    out["hazard_ratio"] = survival.weighted.hazard_ratio
    out["robust_ci"] = survival.hazard_ratio_robust_ci
    return out


def _covers(ci, value: float | None) -> bool:
    return ci is not None and value is not None and ci[0] <= value <= ci[1]


def repeated_draws(
    train: pd.DataFrame,
    spec: Spec,
    release: Release,
    protocol: Protocol,
    synthesize: Callable,
    real: dict,
    draws: int = DRAWS,
) -> dict:
    """The release's method and epsilon, redrawn with seeds spec.seed + 1 onward (secure
    noise each time when the spec has no seed), each table run through the trial."""
    results = []
    for k in range(draws):
        seed = None if spec.seed is None else spec.seed + 1 + k
        table, _ = synthesize(train, spec.model_copy(update={"seed": seed}), release)
        results.append(trial_estimate(table, protocol))
    estimable = [r for r in results if r["hazard_ratio"] is not None and r["robust_ci"]]
    real_null = _covers(real["robust_ci"], 1.0)
    ratios = [r["hazard_ratio"] for r in estimable]
    return {
        "draws": draws,
        "estimable": len(estimable) / draws,
        "covers_real": sum(_covers(r["robust_ci"], real["hazard_ratio"]) for r in estimable)
        / draws,
        # Only meaningful when the real interval includes 1, as it does for this trial.
        "spurious_effect": sum(real_null and not _covers(r["robust_ci"], 1.0) for r in estimable)
        / draws,
        "hazard_ratio_median": float(np.median(ratios)) if ratios else None,
        "hazard_ratio_10th_90th": [float(np.percentile(ratios, q)) for q in (10, 90)]
        if ratios
        else None,
        "events_median": float(
            np.median([r["events_treated"] + r["events_comparator"] for r in results])
        ),
    }


def parity_report(real: dict, release_estimate: dict, draws: dict) -> dict:
    return {
        "real": real,
        "release": release_estimate,
        "release_covers_real": _covers(release_estimate["robust_ci"], real["hazard_ratio"]),
        "repeated": draws,
    }
