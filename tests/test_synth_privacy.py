import numpy as np
import pandas as pd
import pytest

from ehr_rwe_eln.synth.privacy import _nearest, privacy_report, uniqueness
from tests.test_synth import AGE, DRUG, FLAG, SBP, SEX, spec

# One-year age bins and 1 mmHg blood pressure bins: 100 x 120 x 2 x 2 x 2 cells, so few of
# 3,000 people share every code and a copy can stand out.
FINE_AGE = {**AGE, "numeric": {"low": 0, "high": 100, "bins": 100, "integer": True}}
FINE_SBP = {**SBP, "numeric": {"low": 70, "high": 190, "bins": 120}}
SPEC = spec(FINE_AGE, SEX, FLAG, DRUG, FINE_SBP)


def people(n, seed):
    rng = np.random.default_rng(seed)
    age = rng.integers(0, 100, n)
    hypertension = (rng.random(n) < age / 100).astype(int)
    return pd.DataFrame(
        {
            "age": age,
            "sex": rng.choice(["female", "male"], n),
            "hypertension": hypertension,
            "lisinopril": (rng.random(n) < np.where(hypertension == 1, 0.7, 0.02)).astype(int),
            "systolic_bp": rng.normal(125, 15, n).round(),
        },
        index=pd.RangeIndex(seed * 10**6, seed * 10**6 + n, name="person_id"),
    )


def test_nearest_counts_differing_columns_and_ties():
    a = np.array([[0, 0, 0], [1, 1, 1]])
    b = np.array([[0, 0, 1], [0, 1, 1], [1, 1, 1]])
    distance, count = _nearest(a, b)
    assert distance.tolist() == [1, 0] and count.tolist() == [1, 1]


def test_fresh_draws_from_the_population_show_no_leak():
    train, holdout, fresh = people(3000, 1), people(3000, 2), people(3000, 3)
    report = privacy_report(train, holdout, fresh, SPEC)
    assert report["distance_to_closest_record"]["closer_to_member"] == pytest.approx(0.5, abs=0.05)
    assert report["membership_inference"]["auc"] == pytest.approx(0.5, abs=0.05)
    assert abs(report["attribute_inference"]["gap_mean"]) < 0.03


def test_a_copy_of_the_training_data_leaks():
    train, holdout = people(3000, 1), people(3000, 2)
    report = privacy_report(train, holdout, train, SPEC)
    dcr = report["distance_to_closest_record"]
    assert dcr["exact_match_member"] == 1  # every copied row is a training person
    assert dcr["exact_match_member"] > dcr["exact_match_non_member"]
    assert report["membership_inference"]["auc"] > 0.6
    assert "AUC" in report["summary"] and "lower bound" in report["summary"]


def test_uniqueness_counts_people_alone_on_their_quasi_identifiers():
    train = pd.DataFrame(
        {"age": [30, 30, 31, 70], "sex": ["male", "male", "male", "female"]},
        index=pd.RangeIndex(4, name="person_id"),
    )
    result = uniqueness(train, spec(AGE, SEX))
    assert result["exact_age"] == 0.5  # 31 and 70 are alone
    assert result["age_group"] == 0.25  # 30, 30, 31 share the 30s; 70 is alone
