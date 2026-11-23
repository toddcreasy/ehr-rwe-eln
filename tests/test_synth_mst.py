import math

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from ehr_rwe_eln.synth.card import _spend
from ehr_rwe_eln.synth.mst import cdp_delta, cdp_rho, synthesize
from ehr_rwe_eln.synth.spec import Spec

AGE = {"name": "age", "demographic": "age", "numeric": {"low": 0, "high": 100, "bins": 10}}
SEX = {"name": "sex", "demographic": "sex", "categories": ["female", "male"]}
FLAG = {"name": "hypertension", "condition": {"concept_ids": [1]}}
DRUG = {"name": "lisinopril", "drug": {"concept_ids": [2]}}


def spec(*columns, seed=0, epsilon=10) -> Spec:
    return Spec(
        name="t",
        description="t",
        data_use_limitations="None: synthetic test data.",
        source_access="synthetic",
        seed=seed,
        releases=[{"method": "mst", "epsilon": epsilon}],
        pgm={"iters": 2000},
        columns=list(columns),
    )


def toy(n=20_000, seed=1) -> pd.DataFrame:
    """Hypertension rises with age; lisinopril goes almost only to people with hypertension;
    sex is independent of everything."""
    rng = np.random.default_rng(seed)
    age = rng.integers(20, 90, n)
    hypertension = (rng.random(n) < age / 100).astype(int)
    lisinopril = (rng.random(n) < np.where(hypertension == 1, 0.7, 0.02)).astype(int)
    sex = rng.choice(["female", "male"], n)
    return pd.DataFrame(
        {"age": age, "sex": sex, "hypertension": hypertension, "lisinopril": lisinopril}
    )


def test_rho_is_the_largest_that_meets_epsilon_and_delta():
    rho = cdp_rho(1.0, 1e-9)
    assert cdp_delta(rho, 1.0) <= 1e-9
    assert cdp_delta(rho * 1.01, 1.0) > 1e-9
    assert cdp_rho(4.0, 1e-9) > rho


def test_mst_finds_the_pairs_and_keeps_the_relationship():
    s = spec(AGE, SEX, FLAG, DRUG)
    out, spend = synthesize(toy(), s, s.releases[0])
    pairs = {frozenset(p) for p in spend[2]["pairs"]}
    assert len(pairs) == 3  # a tree over four columns
    assert frozenset({"hypertension", "lisinopril"}) in pairs
    assert frozenset({"age", "hypertension"}) in pairs
    given = out.groupby("hypertension").lisinopril.mean()
    assert given[1] == pytest.approx(0.7, abs=0.03)
    assert given[0] == pytest.approx(0.02, abs=0.02)
    assert abs(len(out) - 20_000) < 200  # the row count is the model's, from noisy counts
    assert set(out.sex) == {"female", "male"}


def test_spend_is_three_equal_thirds_of_rho():
    s = spec(AGE, FLAG, DRUG, epsilon=1)
    _, spend = synthesize(toy(2000), s, s.releases[0])
    steps = ["one-way histograms", "pair selection", "two-way histograms"]
    assert [e["of"] for e in spend] == steps
    assert math.fsum(e["rho"] for e in spend) == pytest.approx(cdp_rho(1, s.pgm.delta))
    assert len({round(e["rho"], 12) for e in spend}) == 1
    assert _spend(spend[0]).startswith("| One-way histograms: age, hypertension, lisinopril |")
    assert " x " in _spend(spend[2])


def test_same_seed_same_release():
    table, s = toy(2000), spec(AGE, FLAG, DRUG)
    first, _ = synthesize(table, s, s.releases[0])
    again, _ = synthesize(table, s, s.releases[0])
    pd.testing.assert_frame_equal(first, again)


def test_mst_needs_a_seed():
    with pytest.raises(ValidationError, match="mst releases need a seed"):
        spec(AGE, FLAG, seed=None)
