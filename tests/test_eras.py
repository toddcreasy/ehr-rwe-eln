import datetime

import pytest

from ehr_rwe_eln.cohort.cdm import create_cdm
from ehr_rwe_eln.cohort.eras import build_eras

D = datetime.date
# Invented concept ids, matching nothing real.
CONDITION = 900000010
INGREDIENT, DRUG_A, DRUG_B = 900000020, 900000021, 900000022

CONDITIONS = [
    # person, concept, start, end
    (1, CONDITION, D(2020, 1, 1), D(2020, 1, 10)),
    (1, CONDITION, D(2020, 2, 9), D(2020, 2, 15)),  # starts exactly 30 days later: same era
    (1, CONDITION, D(2020, 3, 20), None),  # 34 days later: new era, ends the next day
    (1, 0, D(2020, 1, 5), D(2020, 1, 6)),  # unmapped: no era
    (2, CONDITION, D(2020, 1, 5), D(2020, 1, 20)),
    (2, CONDITION, D(2020, 1, 10), D(2020, 1, 12)),  # inside the first: same era
]

DRUGS = [
    # person, concept, start, end
    (1, DRUG_A, D(2020, 1, 1), D(2020, 1, 31)),
    (1, DRUG_B, D(2020, 1, 21), D(2020, 2, 10)),  # overlaps: one exposure, Jan 1 to Feb 10
    (1, DRUG_A, D(2020, 3, 1), D(2020, 3, 11)),  # 20 days later: same era, 20 gap days
    (1, DRUG_A, D(2020, 6, 1), D(2020, 6, 5)),  # 82 days later: new era
    (1, 0, D(2020, 1, 1), D(2020, 1, 2)),  # unmapped: no era
]


@pytest.fixture
def con(pg):
    create_cdm(pg)
    for cid, vocab, cls in [
        (CONDITION, "SNOMED", "Clinical Finding"),
        (INGREDIENT, "RxNorm", "Ingredient"),
        (DRUG_A, "RxNorm", "Clinical Drug"),
        (DRUG_B, "RxNorm", "Clinical Drug"),
    ]:
        pg.execute(
            "INSERT INTO cdm.concept VALUES (%s, 'x', 'x', %s, %s, 'S', 'x', DATE '1970-01-01', "
            "DATE '2099-12-31', NULL)",
            [cid, vocab, cls],
        )
    for descendant in (INGREDIENT, DRUG_A, DRUG_B):
        pg.execute(
            "INSERT INTO cdm.concept_ancestor VALUES (%s, %s, 0, 0)", [INGREDIENT, descendant]
        )
    for i, (person, concept, start, end) in enumerate(CONDITIONS, 1):
        pg.execute(
            "INSERT INTO cdm.condition_occurrence (condition_occurrence_id, person_id,"
            " condition_concept_id, condition_start_date, condition_end_date,"
            " condition_type_concept_id) VALUES (%s, %s, %s, %s, %s, 32817)",
            [i, person, concept, start, end],
        )
    for i, (person, concept, start, end) in enumerate(DRUGS, 1):
        pg.execute(
            "INSERT INTO cdm.drug_exposure (drug_exposure_id, person_id, drug_concept_id,"
            " drug_exposure_start_date, drug_exposure_end_date, drug_type_concept_id)"
            " VALUES (%s, %s, %s, %s, %s, 32817)",
            [i, person, concept, start, end],
        )
    return pg


def test_condition_eras_merge_within_30_days(con):
    assert build_eras(con)["condition_era"] == 3
    assert con.execute(
        "SELECT person_id, condition_concept_id, condition_era_start_date,"
        " condition_era_end_date, condition_occurrence_count FROM cdm.condition_era"
        " ORDER BY condition_era_id"
    ).fetchall() == [
        (1, CONDITION, D(2020, 1, 1), D(2020, 2, 15), 2),
        (1, CONDITION, D(2020, 3, 20), D(2020, 3, 21), 1),
        (2, CONDITION, D(2020, 1, 5), D(2020, 1, 20), 2),
    ]


def test_drug_eras_roll_up_to_ingredient_and_count_gap_days(con):
    assert build_eras(con)["drug_era"] == 2
    assert con.execute(
        "SELECT person_id, drug_concept_id, drug_era_start_date, drug_era_end_date,"
        " drug_exposure_count, gap_days FROM cdm.drug_era ORDER BY drug_era_id"
    ).fetchall() == [
        # Jan 1 to Mar 11 2020 is 70 days; exposures cover 40 + 10 of them.
        (1, INGREDIENT, D(2020, 1, 1), D(2020, 3, 11), 3, 20),
        (1, INGREDIENT, D(2020, 6, 1), D(2020, 6, 5), 1, 0),
    ]
