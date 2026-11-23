import math

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from ehr_rwe_eln.synth.aim import candidates, synthesize, workload
from ehr_rwe_eln.synth.card import _spend
from ehr_rwe_eln.synth.mst import cdp_rho
from ehr_rwe_eln.synth.spec import Spec

AGE = {"name": "age", "demographic": "age", "numeric": {"low": 0, "high": 100, "bins": 10}}
SEX = {"name": "sex", "demographic": "sex", "categories": ["female", "male"]}
FLAG = {"name": "hypertension", "condition": {"concept_ids": [1]}}
DRUG = {"name": "lisinopril", "drug": {"concept_ids": [2]}}
QUERY = {"columns": ["lisinopril", "hypertension"], "weight": 10}


def spec(*columns, seed=0, epsilon=10, queries=(QUERY,)) -> Spec:
    return Spec(
        name="t",
        description="t",
        data_use_limitations="None: synthetic test data.",
        source_access="synthetic",
        seed=seed,
        releases=[{"method": "aim", "epsilon": epsilon}],
        pgm={"iters": 1000, "rounds": 8, "round_iters": 200},
        workload=list(queries),
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


def test_workload_is_every_pair_plus_the_queries_in_column_order():
    s = spec(AGE, SEX, FLAG, DRUG, queries=[QUERY, {"columns": ["age", "sex", "hypertension"]}])
    w = workload(s)
    assert len(w) == 6 + 1  # six pairs of four columns, and the triple
    assert w["hypertension", "lisinopril"] == 10
    assert w["age", "sex"] == 1
    assert w["age", "sex", "hypertension"] == 1


def test_candidates_include_every_smaller_marginal_scored_by_overlap():
    c = candidates({("a", "b"): 2.0, ("b", "c"): 1.0})
    assert set(c) == {("a",), ("b",), ("c",), ("a", "b"), ("b", "c")}
    assert c["b",] == 3.0  # in both
    assert c["a", "b"] == 2 * 2 + 1 * 1


def test_aim_keeps_the_relationship_the_workload_asks_for():
    s = spec(AGE, SEX, FLAG, DRUG)
    out, spend = synthesize(toy(), s, s.releases[0])
    chosen = [tuple(e["pairs"][0]) for e in spend[1:]]
    assert ("hypertension", "lisinopril") in chosen
    given = out.groupby("hypertension").lisinopril.mean()
    assert given[1] == pytest.approx(0.7, abs=0.03)
    assert given[0] == pytest.approx(0.02, abs=0.02)
    assert abs(len(out) - 20_000) < 200
    assert set(out.sex) == {"female", "male"}


def test_spend_adds_up_to_rho():
    s = spec(AGE, FLAG, DRUG, epsilon=1)
    _, spend = synthesize(toy(2000), s, s.releases[0])
    assert spend[0]["of"] == "one-way histograms"
    assert all(e["of"] == f"round {i}" for i, e in enumerate(spend) if i)
    assert math.fsum(e["rho"] for e in spend) == pytest.approx(cdp_rho(1, s.pgm.delta))
    assert _spend(spend[1]).startswith("| Round 1: ")


def test_same_seed_same_release():
    table, s = toy(2000), spec(AGE, FLAG, DRUG)
    first, _ = synthesize(table, s, s.releases[0])
    again, _ = synthesize(table, s, s.releases[0])
    pd.testing.assert_frame_equal(first, again)


def test_aim_needs_a_seed_and_known_columns():
    with pytest.raises(ValidationError, match="aim releases need a seed"):
        spec(AGE, FLAG, DRUG, seed=None)
    with pytest.raises(ValidationError, match="workload column bmi is not a column"):
        spec(AGE, FLAG, DRUG, queries=[{"columns": ["age", "bmi"]}])
