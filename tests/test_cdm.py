import datetime
from decimal import Decimal

import pytest

from ehr_rwe_eln.cohort.cdm import VOCABULARY_TABLES, create_cdm, load_vocabulary

# Invented rows in Athena's format. Not real vocabulary content: CLAUDE.md forbids committing that.
FAKE_ATHENA = {
    "CONCEPT": [
        "concept_id\tconcept_name\tdomain_id\tvocabulary_id\tconcept_class_id\tstandard_concept"
        "\tconcept_code\tvalid_start_date\tvalid_end_date\tinvalid_reason",
        '900000001\tFake "quoted" condition\tCondition\tFAKE\tClinical Finding\tS\tF1\t19700101'
        "\t20991231\t",
        "900000002\tFake source code\tCondition\tFAKESRC\tDiagnosis\t\tS1\t19700101\t20991231\t",
    ],
    "VOCABULARY": [
        "vocabulary_id\tvocabulary_name\tvocabulary_reference\tvocabulary_version"
        "\tvocabulary_concept_id",
        "FAKE\tFake vocabulary\tnone\tv1\t900000001",
    ],
    "CONCEPT_RELATIONSHIP": [
        "concept_id_1\tconcept_id_2\trelationship_id\tvalid_start_date\tvalid_end_date"
        "\tinvalid_reason",
        "900000002\t900000001\tMaps to\t19700101\t20991231\t",
    ],
}


@pytest.fixture
def con(pg):
    create_cdm(pg)
    return pg


def test_create_cdm_builds_all_v54_tables(con):
    tables = {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'cdm'"
        ).fetchall()
    }
    assert len(tables) == 39
    assert {"person", "condition_occurrence", "measurement", "cohort", "concept"} <= tables


def test_numeric_columns_keep_small_and_large_values(con):
    con.execute(
        "INSERT INTO cdm.drug_strength (drug_concept_id, ingredient_concept_id, "
        "numerator_value, valid_start_date, valid_end_date) "
        "VALUES (1, 2, 2340000000000000, DATE '1970-01-01', DATE '2099-12-31')"
    )
    con.execute(
        "INSERT INTO cdm.measurement (measurement_id, person_id, measurement_concept_id, "
        "measurement_date, measurement_type_concept_id, value_as_number) "
        "VALUES (1, 1, 1, DATE '2020-01-01', 1, 0.0045)"
    )
    assert con.execute("SELECT numerator_value FROM cdm.drug_strength").fetchone()[0] == Decimal(
        2340000000000000
    )
    assert con.execute("SELECT value_as_number FROM cdm.measurement").fetchone()[0] == Decimal(
        "0.0045"
    )


def test_load_vocabulary_parses_athena_format(con, tmp_path):
    for table in VOCABULARY_TABLES:
        lines = FAKE_ATHENA.get(table.upper())
        if lines is None:
            header = [
                row[0]
                for row in con.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'cdm' AND table_name = %s ORDER BY ordinal_position",
                    [table],
                ).fetchall()
            ]
            lines = ["\t".join(header)]
        (tmp_path / f"{table.upper()}.csv").write_text("\n".join(lines) + "\n")

    counts = load_vocabulary(con, tmp_path)

    assert counts["concept"] == 2
    assert counts["concept_relationship"] == 1
    name, start, standard = con.execute(
        "SELECT concept_name, valid_start_date, standard_concept FROM cdm.concept "
        "WHERE concept_id = 900000001"
    ).fetchone()
    assert name == 'Fake "quoted" condition'
    assert start == datetime.date(1970, 1, 1)
    assert standard == "S"
    mapped = con.execute(
        "SELECT concept_id_2 FROM cdm.concept_relationship "
        "WHERE concept_id_1 = 900000002 AND relationship_id = 'Maps to'"
    ).fetchone()[0]
    assert mapped == 900000001


def test_later_downloads_only_add_missing_rows(con, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    for folder, rows in (
        (first, ["900000001\tKept from the first download"]),
        (second, ["900000001\tDuplicate, skipped", "900000003\tNew in the second download"]),
    ):
        folder.mkdir()
        for table in VOCABULARY_TABLES:
            header = [
                row[0]
                for row in con.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'cdm' AND table_name = %s ORDER BY ordinal_position",
                    [table],
                ).fetchall()
            ]
            lines = ["\t".join(header)]
            if table == "concept":
                lines += [f"{r}\tCondition\tFAKE\tx\tS\tc\t19700101\t20991231\t" for r in rows]
            (folder / f"{table.upper()}.csv").write_text("\n".join(lines) + "\n")

    load_vocabulary(con, first, second)

    assert con.execute(
        "SELECT concept_id, concept_name FROM cdm.concept ORDER BY 1"
    ).fetchall() == [
        (900000001, "Kept from the first download"),
        (900000003, "New in the second download"),
    ]
