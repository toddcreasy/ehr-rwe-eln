import datetime

import duckdb
import pydantic
import pytest
import yaml

from ehr_rwe_eln.cohort.cdm import create_cdm
from ehr_rwe_eln.cohort.spec import (
    DEFINITIONS,
    CohortDefinition,
    build_cohort,
    load_definition,
)

PARENT, CHILD, OTHER = 920001, 920002, 920003
D = datetime.date

# person_id: (birth year, observation period, [(concept, date)], why)
PEOPLE = {
    1: (1970, (D(2010, 1, 1), D(2025, 1, 1)), [(PARENT, D(2016, 5, 1))], "passes every rule"),
    2: (1970, (D(2010, 1, 1), D(2025, 1, 1)), [(CHILD, D(2017, 1, 1))], "descendant concept"),
    3: (1970, (D(2010, 1, 1), D(2025, 1, 1)), [(PARENT, D(2026, 3, 1))], "outside observation"),
    4: (1970, (D(2016, 1, 1), D(2025, 1, 1)), [(PARENT, D(2016, 4, 1))], "short prior history"),
    5: (2000, (D(2010, 1, 1), D(2025, 1, 1)), [(PARENT, D(2016, 5, 1))], "age 16 at index"),
    6: (
        1970,
        (D(2010, 1, 1), D(2025, 1, 1)),
        [(PARENT, D(2013, 1, 1)), (PARENT, D(2018, 1, 1))],
        "first diagnosis before 2015; the later one does not count",
    ),
    7: (1970, (D(2010, 1, 1), D(2025, 1, 1)), [(OTHER, D(2016, 5, 1))], "unrelated concept"),
}

DEFINITION = {
    "id": 9,
    "name": "test",
    "description": "test",
    "entry": {"domain": "condition", "concept_ids": [PARENT]},
    "inclusion": {"prior_observation_days": 365, "min_age": 18, "index_from": "2015-01-01"},
}


@pytest.fixture
def con():
    con = duckdb.connect()
    create_cdm(con)
    con.execute(
        "INSERT INTO cdm.concept_ancestor VALUES (?, ?, 0, 0), (?, ?, 1, 1)",
        [PARENT, PARENT, PARENT, CHILD],
    )
    event_id = 0
    for person_id, (born, (start, end), events, _) in PEOPLE.items():
        con.execute(
            "INSERT INTO cdm.person (person_id, gender_concept_id, year_of_birth, "
            "month_of_birth, day_of_birth, race_concept_id, ethnicity_concept_id) "
            "VALUES (?, 0, ?, 1, 1, 0, 0)",
            [person_id, born],
        )
        con.execute(
            "INSERT INTO cdm.observation_period VALUES (?, ?, ?, ?, 0)",
            [person_id, person_id, start, end],
        )
        for concept, day in events:
            event_id += 1
            con.execute(
                "INSERT INTO cdm.condition_occurrence (condition_occurrence_id, person_id, "
                "condition_concept_id, condition_start_date, condition_type_concept_id) "
                "VALUES (?, ?, ?, ?, 0)",
                [event_id, person_id, concept, day],
            )
    return con


def test_each_rule_removes_its_person(con):
    attrition = build_cohort(con, CohortDefinition.model_validate(DEFINITION))

    assert attrition == [
        ("first event in concept set", 6),
        ("index date inside an observation period", 5),
        ("at least 365 days of prior observation", 4),
        ("age 18 or older at index", 3),
        ("index on or after 2015-01-01", 2),
    ]
    assert con.execute(
        "SELECT subject_id, cohort_start_date, cohort_end_date FROM cdm.cohort ORDER BY 1"
    ).fetchall() == [(1, D(2016, 5, 1), D(2025, 1, 1)), (2, D(2017, 1, 1), D(2025, 1, 1))]


def test_rebuild_replaces_rows_and_fixed_days_exit(con):
    build_cohort(con, CohortDefinition.model_validate(DEFINITION))
    fixed = {**DEFINITION, "exit": {"strategy": "fixed_days", "days": 30}}
    build_cohort(con, CohortDefinition.model_validate(fixed))

    assert con.execute(
        "SELECT subject_id, cohort_end_date FROM cdm.cohort ORDER BY 1"
    ).fetchall() == [(1, D(2016, 5, 31)), (2, D(2017, 1, 31))]


def test_shipped_definitions_are_valid_and_ids_unique():
    definitions = [load_definition(p) for p in DEFINITIONS.glob("*.yaml")]
    assert definitions
    assert len({d.id for d in definitions}) == len(definitions)


@pytest.mark.parametrize(
    "change",
    [
        {"inclusion": {"min_agee": 18}},  # misspelled rule
        {"entry": {"domain": "conditions", "concept_ids": [1]}},  # unknown domain
        {"exit": {"strategy": "fixed_days"}},  # fixed_days without days
        {"entry": {"domain": "condition", "concept_ids": []}},  # empty concept set
    ],
)
def test_malformed_definitions_are_rejected(tmp_path, change):
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump({**DEFINITION, **change}))
    with pytest.raises(pydantic.ValidationError):
        load_definition(path)
