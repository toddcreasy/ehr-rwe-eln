import datetime

import duckdb
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
def con():
    con = duckdb.connect()
    create_cdm(con)
    return con


def test_create_cdm_builds_all_v54_tables(con):
    tables = {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'cdm'"
        ).fetchall()
    }
    assert len(tables) == 39
    assert {"person", "condition_occurrence", "measurement", "cohort", "concept"} <= tables


def test_load_vocabulary_parses_athena_format(con, tmp_path):
    for table in VOCABULARY_TABLES:
        lines = FAKE_ATHENA.get(table.upper())
        if lines is None:
            header = [
                row[0]
                for row in con.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'cdm' AND table_name = ? ORDER BY ordinal_position",
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
