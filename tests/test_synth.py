import math

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from ehr_rwe_eln.cohort.cdm import create_cdm
from ehr_rwe_eln.synth.bayes_net import decode, encode, plan, synthesize
from ehr_rwe_eln.synth.release import load_release, save_release
from ehr_rwe_eln.synth.source import build_source, split
from ehr_rwe_eln.synth.spec import SPECS, Column, Release, Spec, load_spec

AGE = {"name": "age", "demographic": "age", "numeric": {"low": 0, "high": 100, "bins": 10}}
SEX = {"name": "sex", "demographic": "sex", "categories": ["female", "male"]}
FLAG = {"name": "hypertension", "condition": {"concept_ids": [1]}, "parents": ["age"]}
DRUG = {"name": "lisinopril", "drug": {"concept_ids": [2]}, "parents": ["hypertension"]}
SBP = {
    "name": "systolic_bp",
    "measurement": {"concept_ids": [3]},
    "numeric": {"low": 70, "high": 190, "bins": 12},
}


def spec(*columns, seed=0, releases=None) -> Spec:
    return Spec(
        name="t",
        description="t",
        data_use_limitations="None: synthetic test data.",
        source_access="synthetic",
        seed=seed,
        releases=releases or [{"method": "bayes_net", "epsilon": 1}],
        columns=list(columns),
    )


def test_the_shipped_spec_loads():
    s = load_spec(SPECS / "person_summary.yaml")
    assert len(s.columns) == 21
    assert {r.method for r in s.releases} == {"bayes_net", "independent", "vae", "mst", "aim"}


@pytest.mark.parametrize(
    ("columns", "message"),
    [
        ([FLAG, AGE], "must be listed before"),
        ([AGE, AGE], "duplicate"),
        ([{**SEX, "numeric": {"low": 0, "high": 1, "bins": 1}}], "not both"),
        ([{**SBP, "numeric": None}], "needs numeric"),
        ([{**SEX, "condition": {"concept_ids": [1]}}], "exactly one source"),
        ([{**AGE, "numeric": {"low": 5, "high": 5, "bins": 1}}], "below high"),
        ([AGE, SEX, {**DRUG, "parents": ["age", "sex", "age"]}], "at most 2"),
    ],
)
def test_bad_specs_are_refused(columns, message):
    with pytest.raises(ValidationError, match=message):
        spec(*columns)


def test_data_use_limitations_are_required():
    fields = spec(AGE).model_dump()
    for value in (None, ""):
        with pytest.raises(ValidationError, match="data_use_limitations"):
            Spec.model_validate({**fields, "data_use_limitations": value})
    del fields["data_use_limitations"]
    with pytest.raises(ValidationError, match="data_use_limitations"):
        Spec.model_validate(fields)


def test_flags_default_to_zero_and_one():
    assert Column.model_validate(DRUG).categories == [0, 1]


def test_encode_clamps_bins_and_codes_missing():
    columns = spec(AGE, SEX, SBP).columns
    table = pd.DataFrame(
        {"age": [0, 15, 99, 130], "sex": ["male"] * 4, "systolic_bp": [50, 100, np.nan, 300]}
    )
    codes = encode(table, columns)
    assert codes[:, 0].tolist() == [0, 1, 9, 9]  # 130 clamps into the last bin
    assert codes[:, 1].tolist() == [1, 1, 1, 1]
    assert codes[:, 2].tolist() == [0, 3, 12, 11]  # 12 is the missing code


def test_encode_refuses_values_outside_the_spec():
    with pytest.raises(ValueError, match="outside the spec"):
        encode(pd.DataFrame({"sex": ["unknown"]}), spec(SEX).columns)
    with pytest.raises(ValueError, match="allows none"):
        encode(pd.DataFrame({"age": [np.nan]}), spec(AGE).columns)


def test_decode_draws_inside_the_bin():
    columns = spec({**AGE, "numeric": {**AGE["numeric"], "integer": True}}, SBP).columns
    codes = np.array([[3, 12]] * 200)
    out = decode(codes, columns, np.random.default_rng(0))
    assert out.age.between(30, 39).all() and (out.age == out.age.round()).all()
    assert out.systolic_bp.isna().all()


def test_open_top_bin_decodes_to_its_edge():
    numeric = {**AGE["numeric"], "integer": True, "open_top": True}
    columns = spec({**AGE, "numeric": numeric}).columns
    codes = encode(pd.DataFrame({"age": [85, 90, 104]}), columns)
    assert codes[:, 0].tolist() == [8, 9, 9]
    out = decode(np.array([[8]] * 200 + [[9]] * 200), columns, np.random.default_rng(0))
    assert out.age[:200].between(80, 89).all()
    assert (out.age[200:] == 90).all()


def test_shipped_specs_top_code_age_at_90():
    for name in ("person_summary.yaml", "trial_lisinopril_amlodipine_ckd.yaml"):
        age = next(c for c in load_spec(SPECS / name).columns if c.name == "age")
        assert age.numeric is not None and age.numeric.open_top
        assert age.numeric.high - (age.numeric.high - age.numeric.low) / age.numeric.bins == 90


def toy(n=20_000, seed=1) -> pd.DataFrame:
    """Hypertension rises with age; lisinopril goes almost only to people with hypertension."""
    rng = np.random.default_rng(seed)
    age = rng.integers(20, 90, n)
    hypertension = (rng.random(n) < age / 100).astype(int)
    lisinopril = (rng.random(n) < np.where(hypertension == 1, 0.7, 0.02)).astype(int)
    return pd.DataFrame({"age": age, "hypertension": hypertension, "lisinopril": lisinopril})


def test_bayes_net_keeps_the_relationship_and_independent_loses_it():
    table = toy()
    rates = {}
    for method in ("bayes_net", "independent"):
        s = spec(AGE, FLAG, DRUG, releases=[{"method": method, "epsilon": 10}])
        out, measurements = synthesize(table, s, s.releases[0])
        given = out.groupby("hypertension").lisinopril.mean()
        rates[method] = (given[1], given[0])
        assert abs(len(out) - len(table)) < 100  # the row count is noisy, not exact
        assert math.fsum(m.epsilon for m in measurements) <= 10
    assert rates["bayes_net"][0] == pytest.approx(0.7, abs=0.03)
    assert rates["bayes_net"][1] == pytest.approx(0.02, abs=0.01)
    # Without the parent the drug is given at its overall rate, whatever the condition.
    assert rates["independent"][0] == pytest.approx(rates["independent"][1], abs=0.03)


def test_measurements_cover_each_column_with_its_parents():
    s = spec(AGE, FLAG, DRUG)
    _, measurements = synthesize(toy(1000), s, Release(method="bayes_net", epsilon=3))
    assert [(m.columns, m.cells) for m in measurements] == [
        (["age"], 10),
        (["age", "hypertension"], 20),
        (["hypertension", "lisinopril"], 4),
    ]
    assert all(m.epsilon == pytest.approx(1) for m in measurements)


def test_same_seed_same_release_and_no_seed_differs():
    table, s = toy(2000), spec(AGE, FLAG, DRUG)
    first, _ = synthesize(table, s, s.releases[0])
    again, _ = synthesize(table, s, s.releases[0])
    pd.testing.assert_frame_equal(first, again)
    unseeded = spec(AGE, FLAG, DRUG, seed=None)
    a, _ = synthesize(table, unseeded, unseeded.releases[0])
    b, _ = synthesize(table, unseeded, unseeded.releases[0])
    assert not a.equals(b)


@pytest.fixture
def con(pg, dq_schema):
    create_cdm(pg)
    # person: (sex, born, observed until, hypertension, lisinopril, sbp readings, died)
    people = {
        1: (8532, 1950, "2020-06-30", True, True, [("2019-01-01", 150), ("2020-01-01", 140)], True),
        2: (8507, 1990, "2022-12-31", False, False, [], False),
    }
    for person, (sex, born, until, htn, drug, readings, died) in people.items():
        pg.execute(
            "INSERT INTO cdm.person (person_id, gender_concept_id, year_of_birth, race_concept_id,"
            " ethnicity_concept_id, race_source_value, ethnicity_source_value)"
            " VALUES (%s, %s, %s, 0, 0, 'white', 'nonhispanic')",
            [person, sex, born],
        )
        pg.execute(
            "INSERT INTO cdm.observation_period VALUES (%s, %s, '2000-01-01', %s, 32817)",
            [person, person, until],
        )
        if htn:
            pg.execute(
                "INSERT INTO cdm.condition_occurrence (condition_occurrence_id, person_id,"
                " condition_concept_id, condition_start_date, condition_type_concept_id)"
                " VALUES (%s, %s, 1, '2015-01-01', 32817)",
                [person, person],
            )
        if drug:
            pg.execute(
                "INSERT INTO cdm.drug_exposure (drug_exposure_id, person_id, drug_concept_id,"
                " drug_exposure_start_date, drug_exposure_end_date, drug_type_concept_id)"
                " VALUES (%s, %s, 2, '2016-01-01', '2016-02-01', 32817)",
                [person, person],
            )
        for i, (day, value) in enumerate(readings):
            pg.execute(
                "INSERT INTO cdm.measurement (measurement_id, person_id, measurement_concept_id,"
                " measurement_date, measurement_type_concept_id, value_as_number)"
                " VALUES (%s, %s, 3, %s, 32817, %s)",
                [person * 10 + i, person, day, value],
            )
        if died:
            pg.execute(
                "INSERT INTO cdm.death (person_id, death_date) VALUES (%s, %s)", [person, until]
            )
    return pg


def test_source_has_one_row_per_person_and_no_person_id(con):
    deceased = {"name": "deceased", "demographic": "deceased"}
    s = spec(AGE, SEX, FLAG, DRUG, SBP, deceased)
    source = build_source(con, s)
    assert list(source.columns) == [c.name for c in s.columns]
    assert source.index.name == "person_id" and list(source.index) == [1, 2]
    assert source.to_dict("records")[0] == {
        "age": 70,  # 2020 minus 1950
        "sex": "female",
        "hypertension": 1,
        "lisinopril": 1,
        "systolic_bp": 140.0,  # the latest reading
        "deceased": 1,
    }
    second = source.iloc[1]
    assert (second.age, second.hypertension, second.lisinopril, second.deceased) == (32, 0, 0, 0)
    assert math.isnan(second.systolic_bp)


def test_release_round_trips_with_provenance(con):
    s = spec(AGE, FLAG, DRUG, SBP)
    table = toy(500).assign(systolic_bp=np.where(np.arange(500) % 2, 120.0, np.nan))
    out, measurements = synthesize(table, s, s.releases[0])
    release_id = save_release(con, s, s.releases[0], plan(measurements), out, len(table), 200)
    record = con.execute(
        "SELECT spec_name, method, epsilon, seed, source_rows, holdout_rows, rows,"
        " jsonb_array_length(measurements), spec ->> 'name'"
        " FROM synth.release WHERE release_id = %s",
        [release_id],
    ).fetchone()
    assert record == ("t", "bayes_net", 1.0, 0, 500, 200, len(out), 4, "t")
    loaded = load_release(con, release_id)
    pd.testing.assert_frame_equal(loaded, out, check_dtype=False)


def test_split_is_stable_and_near_the_fraction():
    s = spec(AGE).model_copy(update={"holdout_fraction": 0.3})
    table = pd.DataFrame({"age": range(10_000)}, index=pd.Index(range(10_000), name="person_id"))
    train, holdout = split(table, s)
    assert len(train) + len(holdout) == 10_000 and not set(train.index) & set(holdout.index)
    assert 0.28 < len(holdout) / 10_000 < 0.32
    again, _ = split(table.iloc[::-1], s)  # order does not matter, only person_id
    assert set(again.index) == set(train.index)


def test_utility_target_must_be_a_flag():
    with pytest.raises(ValidationError, match="must be a 0/1 column"):
        Spec.model_validate({**spec(AGE).model_dump(), "utility_target": "age"})


def test_subgroups_must_be_columns():
    fields = spec(AGE, SEX).model_dump()
    assert Spec(**{**fields, "subgroups": ["sex", "age"]}).subgroups == ["sex", "age"]
    with pytest.raises(ValidationError, match="subgroup race is not a column"):
        Spec(**{**fields, "subgroups": ["race"]})


def test_intersections_need_two_or_three_different_columns():
    fields = spec(AGE, SEX).model_dump()
    assert Spec(**{**fields, "subgroups": [["age", "sex"]]}).subgroups == [["age", "sex"]]
    for bad in (["age"], ["age", "age"]):
        with pytest.raises(ValidationError, match="two or three different columns"):
            Spec(**{**fields, "subgroups": [bad]})
    with pytest.raises(ValidationError, match="subgroup race is not a column"):
        Spec(**{**fields, "subgroups": [["age", "race"]]})
