import datetime

import pandas as pd
import pytest

from ehr_rwe_eln.cohort.cdm import create_cdm
from ehr_rwe_eln.tte.cohort import build_analysis_table
from ehr_rwe_eln.tte.covariates import add_covariates
from ehr_rwe_eln.tte.protocol import PROTOCOLS, ConceptSet, Protocol, load_protocol

D = datetime.date
# Invented concept ids, matching nothing real.
DIAGNOSIS, DIAGNOSIS_CHILD, TREATMENT, COMPARATOR, OUTCOME = 920001, 920002, 920010, 920020, 920030

PROTOCOL = Protocol.model_validate(
    {
        "id": 1,
        "name": "test",
        "description": "test",
        # The diagnosis is recorded as a child concept, so it only counts through descendants.
        "eligibility": {"diagnosis": {"concept_ids": [DIAGNOSIS]}, "max_days_from_diagnosis": 365},
        "strategies": {
            "treatment": {"name": "a", "drugs": {"concept_ids": [TREATMENT]}},
            "comparator": {"name": "b", "drugs": {"concept_ids": [COMPARATOR]}},
        },
        "outcome": {"name": "o", "conditions": {"concept_ids": [OUTCOME]}},
        "follow_up": {"max_days": 1825},
    }
)

# person: (born, observation period, diagnosis, drug starts, outcome, death)
PEOPLE = {
    1: (
        1960,
        (D(2000, 1, 1), D(2030, 1, 1)),
        D(2019, 6, 1),
        [(TREATMENT, D(2020, 1, 1))],
        D(2021, 1, 1),
        None,
    ),  # eligible; outcome after 366 days
    2: (
        1960,
        (D(2000, 1, 1), D(2030, 1, 1)),
        D(2019, 6, 1),
        [(COMPARATOR, D(2020, 1, 1))],
        None,
        D(2022, 1, 1),
    ),  # eligible; dies after 731 days
    3: (
        1960,
        (D(2000, 1, 1), D(2030, 1, 1)),
        D(2019, 6, 1),
        [(TREATMENT, D(2020, 1, 1)), (COMPARATOR, D(2020, 1, 1))],
        None,
        None,
    ),  # both same day
    4: (
        1960,
        (D(2021, 1, 1), D(2030, 1, 1)),
        D(2019, 6, 1),
        [(TREATMENT, D(2020, 1, 1))],
        None,
        None,
    ),  # starts before any observation period
    5: (
        1960,
        (D(2019, 6, 1), D(2030, 1, 1)),
        D(2019, 6, 1),
        [(TREATMENT, D(2020, 1, 1))],
        None,
        None,
    ),  # 214 days of prior observation
    6: (
        2005,
        (D(2000, 1, 1), D(2030, 1, 1)),
        D(2019, 6, 1),
        [(TREATMENT, D(2020, 1, 1))],
        None,
        None,
    ),  # 14 at time zero
    7: (
        1960,
        (D(2000, 1, 1), D(2030, 1, 1)),
        D(2021, 6, 1),
        [(TREATMENT, D(2020, 1, 1))],
        None,
        None,
    ),  # diagnosed after starting
    8: (
        1960,
        (D(2000, 1, 1), D(2030, 1, 1)),
        D(2010, 6, 1),
        [(TREATMENT, D(2020, 1, 1))],
        None,
        None,
    ),  # diagnosed nearly 10 years before starting
    9: (
        1960,
        (D(2000, 1, 1), D(2030, 1, 1)),
        D(2019, 6, 1),
        [(TREATMENT, D(2020, 1, 1))],
        D(2020, 1, 1),
        None,
    ),  # outcome on time zero
    10: (
        1960,
        (D(2000, 1, 1), D(2030, 1, 1)),
        D(2019, 6, 1),
        [(TREATMENT, D(2020, 1, 1)), (COMPARATOR, D(2021, 1, 1))],
        None,
        None,
    ),  # switches later
    11: (
        1960,
        (D(2000, 1, 1), D(2021, 6, 30)),
        D(2019, 6, 1),
        [(COMPARATOR, D(2020, 1, 1))],
        None,
        None,
    ),  # records end after 546 days
}


@pytest.fixture
def con(pg):
    create_cdm(pg)
    for ancestor, descendant in [(DIAGNOSIS, DIAGNOSIS), (DIAGNOSIS, DIAGNOSIS_CHILD)]:
        pg.execute("INSERT INTO cdm.concept_ancestor VALUES (%s, %s, 0, 0)", [ancestor, descendant])
    rows = 0
    for person, (born, (op_start, op_end), diagnosis, starts, outcome, death) in PEOPLE.items():
        pg.execute(
            "INSERT INTO cdm.person (person_id, gender_concept_id, year_of_birth, race_concept_id,"
            " ethnicity_concept_id) VALUES (%s, 8507, %s, 0, 0)",
            [person, born],
        )
        pg.execute(
            "INSERT INTO cdm.observation_period VALUES (%s, %s, %s, %s, 32817)",
            [person, person, op_start, op_end],
        )
        for concept, date in [(DIAGNOSIS_CHILD, diagnosis), (OUTCOME, outcome)]:
            if date:
                rows += 1
                pg.execute(
                    "INSERT INTO cdm.condition_occurrence (condition_occurrence_id, person_id,"
                    " condition_concept_id, condition_start_date, condition_type_concept_id)"
                    " VALUES (%s, %s, %s, %s, 32817)",
                    [rows, person, concept, date],
                )
        for concept, date in starts:
            rows += 1
            pg.execute(
                "INSERT INTO cdm.drug_exposure (drug_exposure_id, person_id, drug_concept_id,"
                " drug_exposure_start_date, drug_exposure_end_date, drug_type_concept_id)"
                " VALUES (%s, %s, %s, %s, %s, 32817)",
                [rows, person, concept, date, date],
            )
        if death:
            pg.execute(
                "INSERT INTO cdm.death (person_id, death_date) VALUES (%s, %s)", [person, death]
            )
    return pg


def test_attrition_drops_one_planted_person_per_rule(con):
    attrition, _ = build_analysis_table(con, PROTOCOL)
    assert attrition == [
        ("first use of either strategy", 11),
        ("started one strategy before the other", 10),
        ("time zero inside an observation period", 9),
        ("at least 365 days of prior observation", 8),
        ("age 18 or older at time zero", 7),
        ("diagnosed on or before time zero", 6),
        ("time zero within 365 days of diagnosis", 5),
        ("no outcome on or before time zero", 4),
    ]


def test_follow_up_ends_at_the_first_of_outcome_death_records_or_max(con):
    _, table = build_analysis_table(con, PROTOCOL)
    rows = table[["person_id", "arm", "event", "days", "end_reason"]].values.tolist()
    assert rows == [
        [1, 1, 1, 366, "outcome"],
        [2, 0, 0, 731, "death"],
        # Intention to treat: still in the treatment arm after adding the comparator drug.
        [10, 1, 0, 1825, "administrative"],
        [11, 0, 0, 546, "end_of_observation"],
    ]


def test_shipped_protocols_load():
    protocols = [load_protocol(p) for p in sorted(PROTOCOLS.glob("*.yaml"))]
    assert [p.name for p in protocols] == [
        "lisinopril_vs_amlodipine_ckd",
        "lisinopril_vs_amlodipine_mi",
        "metformin_vs_insulin_ckd",
        "metformin_vs_insulin_mi",
    ]
    assert len({p.id for p in protocols}) == len(protocols)
    assert all(isinstance(p.outcome.conditions, ConceptSet) for p in protocols)


def test_covariates_use_only_what_is_known_at_time_zero(con):
    lab, history = 920040, 920050
    protocol = PROTOCOL.model_copy(
        update={
            "covariates": PROTOCOL.covariates.model_validate(
                {
                    "conditions": [{"name": "history", "conditions": {"concept_ids": [history]}}],
                    "measurements": [
                        {
                            "name": "lab",
                            "measurements": {"concept_ids": [lab]},
                            "lookback_days": 365,
                        }
                    ],
                }
            )
        }
    )
    # Person 1 starts on 2020-01-01; person 2 too.
    facts = [
        ("condition", 1, history, D(2019, 1, 1), None),  # before time zero: counts
        ("condition", 2, history, D(2020, 2, 1), None),  # after: does not
        ("measurement", 1, lab, D(2019, 3, 1), 6.0),
        ("measurement", 1, lab, D(2019, 12, 1), 7.5),  # latest in the window wins
        ("measurement", 1, lab, D(2020, 1, 2), 9.9),  # after time zero: ignored
        ("measurement", 2, lab, D(2018, 6, 1), 8.0),  # older than 365 days: missing
    ]
    for i, (kind, person, concept, date, value) in enumerate(facts, 100):
        if kind == "condition":
            con.execute(
                "INSERT INTO cdm.condition_occurrence (condition_occurrence_id, person_id,"
                " condition_concept_id, condition_start_date, condition_type_concept_id)"
                " VALUES (%s, %s, %s, %s, 32817)",
                [i, person, concept, date],
            )
        else:
            con.execute(
                "INSERT INTO cdm.measurement (measurement_id, person_id, measurement_concept_id,"
                " measurement_date, measurement_type_concept_id, value_as_number)"
                " VALUES (%s, %s, %s, %s, 32817, %s)",
                [i, person, concept, date, value],
            )
    _, table = build_analysis_table(con, protocol)
    table = add_covariates(con, protocol, table).set_index("person_id")
    assert table.loc[[1, 2], "history"].tolist() == [1, 0]
    assert table.loc[1, "lab"] == 7.5
    assert pd.isna(table.loc[2, "lab"])
    assert table.loc[1, "male"] == 1
