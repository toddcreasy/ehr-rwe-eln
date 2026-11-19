import numpy as np
import pandas as pd
import pytest

from ehr_rwe_eln.synth.fidelity import fidelity_report, subgroup_report, utility_auc
from tests.test_synth import AGE, DRUG, FLAG, SBP, SEX, spec, toy

COLUMNS = spec(AGE, FLAG, DRUG, SBP).columns


def table(n=4000, seed=1):
    return toy(n, seed).assign(systolic_bp=np.random.default_rng(seed).normal(125, 15, n).round())


def test_identical_tables_score_zero():
    t = table()
    s = fidelity_report(t, t, COLUMNS)["summary"]
    assert s["column_tvd_max"] == 0 and s["pair_tvd_max"] == 0
    assert s["correlation_gap_mean"] == pytest.approx(0)


def test_a_broken_relationship_shows_in_the_pairs_not_the_columns():
    real = table()
    # Shuffle lisinopril: same rate, no longer tied to hypertension.
    broken = real.assign(lisinopril=real.lisinopril.sample(frac=1, random_state=0).to_numpy())
    report = fidelity_report(real, broken, COLUMNS)
    assert report["column_tvd"]["lisinopril"] == 0
    assert report["worst_pairs"][0]["columns"] == ["hypertension", "lisinopril"]
    assert report["worst_pairs"][0]["tvd"] > 0.2


def test_column_tvd_and_ks_by_hand():
    real = pd.DataFrame({"age": [5.0] * 50 + [15.0] * 50, "systolic_bp": [100.0] * 100})
    synthetic = pd.DataFrame({"age": [5.0] * 80 + [15.0] * 20, "systolic_bp": [180.0] * 100})
    report = fidelity_report(real, synthetic, spec(AGE, SBP).columns)
    assert report["column_tvd"]["age"] == pytest.approx(0.3)  # half of |0.5-0.8| + |0.5-0.2|
    assert report["ks"]["systolic_bp"] == 1  # no overlap
    assert report["summary"]["correlation_gap_mean"] is None  # blood pressure is constant


def test_utility_auc_beats_guessing_on_a_real_relationship_and_not_on_noise():
    train, test = table(4000, 1), table(2000, 2)
    assert utility_auc(train, test, COLUMNS, "lisinopril") > 0.8
    shuffled = train.assign(lisinopril=train.lisinopril.sample(frac=1, random_state=0).to_numpy())
    assert utility_auc(shuffled, test, COLUMNS, "lisinopril") < 0.6
    assert utility_auc(train.assign(lisinopril=0), test, COLUMNS, "lisinopril") is None


def with_sex(t: pd.DataFrame, seed: int) -> pd.DataFrame:
    return t.assign(sex=np.random.default_rng(seed).choice(["female", "male"], len(t)))


def test_subgroups_find_the_group_a_release_distorts():
    columns = spec(AGE, SEX, FLAG, DRUG).columns
    train, holdout = with_sex(toy(6000, 1), 1), with_sex(toy(3000, 2), 2)
    # A release that drops half the men and never gives a man lisinopril.
    release = with_sex(toy(6000, 3), 3)
    release = release[(release.sex == "female") | (np.arange(len(release)) % 2 == 0)]
    release = release.assign(lisinopril=np.where(release.sex == "male", 0, release.lisinopril))
    rows = subgroup_report(train, holdout, release, columns, ["sex", "age"], "hypertension")
    by = {(r["column"], r["group"]): r for r in rows}
    men, women = by[("sex", "male")], by[("sex", "female")]
    assert men["share_ratio"] == pytest.approx(2 / 3, abs=0.05)
    assert women["share_ratio"] == pytest.approx(4 / 3, abs=0.05)
    assert men["excess"] > 0.05 > women["excess"]
    assert men["noise_floor"] < 0.03  # two real samples of thousands of men barely differ
    assert men["tstr_auc"] is not None and men["trtr_auc"] > 0.5
    # Ages 20 to 89: the empty bins below 20 are left out, not reported as zero.
    assert [g for c, g in by if c == "age"][0] == "20 to 30"


def test_subgroups_without_a_holdout_have_no_floor():
    columns = spec(AGE, SEX, FLAG).columns
    train = with_sex(toy(2000, 1), 1)
    rows = subgroup_report(train, train.iloc[:0], train, columns, ["sex"], "hypertension")
    assert all(r["noise_floor"] is None and r["excess"] is None for r in rows)
    assert all(r["column_tvd_mean"] == 0 and "tstr_auc" not in r for r in rows)
