import csv
import datetime
from decimal import Decimal

import pytest

from ehr_rwe_eln.cohort.cdm import create_cdm
from ehr_rwe_eln.cohort.etl import run_etl

# Invented patients and an invented mini vocabulary. Codes and concept ids match nothing real.
P1, P2 = "patient-a", "patient-b"
E1, E2 = "enc-1", "enc-2"

SYNTHEA = {
    "patients": [
        {
            "Id": P1,
            "BIRTHDATE": "1980-02-03",
            "DEATHDATE": "",
            "RACE": "white",
            "ETHNICITY": "nonhispanic",
            "GENDER": "M",
        },
        {
            "Id": P2,
            "BIRTHDATE": "1950-07-08",
            "DEATHDATE": "2024-05-01",
            "RACE": "hawaiian",
            "ETHNICITY": "hispanic",
            "GENDER": "F",
        },
    ],
    "encounters": [
        {
            "Id": E1,
            "START": "2020-01-01T09:00:00Z",
            "STOP": "2020-01-01T10:00:00Z",
            "PATIENT": P1,
            "ENCOUNTERCLASS": "ambulatory",
        },
        {
            "Id": E2,
            "START": "2024-04-01T09:00:00Z",
            "STOP": "2024-04-02T09:00:00Z",
            "PATIENT": P2,
            "ENCOUNTERCLASS": "virtual",
        },
    ],
    "conditions": [
        {
            "START": "2020-01-01",
            "STOP": "",
            "PATIENT": P1,
            "ENCOUNTER": E1,
            "SYSTEM": "SNOMED-CT",
            "CODE": "C-COND",
        },
        {
            "START": "2020-01-01",
            "STOP": "",
            "PATIENT": P1,
            "ENCOUNTER": E1,
            "SYSTEM": "SNOMED-CT",
            "CODE": "C-SOCIAL",
        },
        {
            "START": "2024-04-01",
            "STOP": "2024-04-10",
            "PATIENT": P2,
            "ENCOUNTER": E2,
            "SYSTEM": "ICD10",
            "CODE": "Z99.9",
        },
        {
            "START": "2024-04-01",
            "STOP": "",
            "PATIENT": P2,
            "ENCOUNTER": E2,
            "SYSTEM": "SNOMED-CT",
            "CODE": "C-NOMAP",
        },
    ],
    "procedures": [
        {
            "START": "2024-04-01T09:00:00Z",
            "STOP": "",
            "PATIENT": P2,
            "ENCOUNTER": E2,
            "SYSTEM": "CDT",
            "CODE": "D9999",
        },
    ],
    "medications": [
        {
            "START": "2020-01-01T09:00:00Z",
            "STOP": "",
            "PATIENT": P1,
            "ENCOUNTER": E1,
            "CODE": "R-DRUG",
        },
    ],
    "immunizations": [],
    "observations": [
        {
            "DATE": "2020-01-01T09:00:00Z",
            "PATIENT": P1,
            "ENCOUNTER": E1,
            "CATEGORY": "laboratory",
            "CODE": "L-LAB",
            "VALUE": "0.0045",
            "UNITS": "mg/dL",
            "TYPE": "numeric",
        },
        {
            "DATE": "2020-01-01T09:00:00Z",
            "PATIENT": P1,
            "ENCOUNTER": E1,
            "CATEGORY": "survey",
            "CODE": "L-TEXT",
            "VALUE": "Never smoked",
            "UNITS": "",
            "TYPE": "text",
        },
    ],
    "devices": [],
}
HEADERS = {
    "patients": ["Id", "BIRTHDATE", "DEATHDATE", "RACE", "ETHNICITY", "GENDER"],
    "encounters": ["Id", "START", "STOP", "PATIENT", "ENCOUNTERCLASS"],
    "conditions": ["START", "STOP", "PATIENT", "ENCOUNTER", "SYSTEM", "CODE"],
    "procedures": ["START", "STOP", "PATIENT", "ENCOUNTER", "SYSTEM", "CODE"],
    "medications": ["START", "STOP", "PATIENT", "ENCOUNTER", "CODE"],
    "immunizations": ["DATE", "PATIENT", "ENCOUNTER", "CODE"],
    "observations": ["DATE", "PATIENT", "ENCOUNTER", "CATEGORY", "CODE", "VALUE", "UNITS", "TYPE"],
    "devices": ["START", "STOP", "PATIENT", "ENCOUNTER", "CODE"],
}
# (concept_id, vocabulary_id, code, domain_id, standard)
CONCEPTS = [
    (910001, "SNOMED", "C-COND", "Condition", "S"),
    (910002, "SNOMED", "C-SOCIAL", "Observation", "S"),
    (910003, "ICD10CM", "Z99.9", "Condition", None),
    (910004, "SNOMED", "C-NOMAP", "Condition", None),
    (910005, "RxNorm", "R-DRUG", "Drug", "S"),
    (910006, "LOINC", "L-LAB", "Measurement", "S"),
    (910007, "LOINC", "L-TEXT", "Observation", "S"),
    (910008, "UCUM", "mg/dL", "Unit", "S"),
]
MAPS_TO = [(910003, 910001)] + [(c, c) for c, *_, s in CONCEPTS if s == "S"]


@pytest.fixture(scope="module")
def etl(pg_module, tmp_path_factory):
    folder = tmp_path_factory.mktemp("synthea")
    for name, rows in SYNTHEA.items():
        with (folder / f"{name}.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, HEADERS[name])
            writer.writeheader()
            writer.writerows(rows)
    con = pg_module
    create_cdm(con)
    for cid, vocab, code, domain, standard in CONCEPTS:
        con.execute(
            "INSERT INTO cdm.concept VALUES (%s, %s, %s, %s, 'x', %s, %s, DATE '1970-01-01', "
            "DATE '2099-12-31', NULL)",
            [cid, code, domain, vocab, standard, code],
        )
    con.execute(
        "INSERT INTO cdm.vocabulary VALUES ('None', 'OMOP Standardized Vocabularies', NULL, "
        "'v5.0 TEST', 0)"
    )
    for source, target in MAPS_TO:
        con.execute(
            "INSERT INTO cdm.concept_relationship VALUES (%s, %s, 'Maps to', DATE '1970-01-01', "
            "DATE '2099-12-31', NULL)",
            [source, target],
        )
    return con, run_etl(con, folder)


@pytest.fixture
def con(etl):
    return etl[0]


def one(con, sql):
    return con.execute(sql).fetchall()


def test_person_demographics_and_death(con):
    assert one(
        con,
        "SELECT person_source_value, gender_concept_id, race_concept_id, "
        "ethnicity_concept_id, year_of_birth FROM cdm.person ORDER BY 1",
    ) == [
        (P1, 8507, 8527, 38003564, 1980),
        (P2, 8532, 8557, 38003563, 1950),
    ]
    assert one(con, "SELECT death_date FROM cdm.death") == [(datetime.date(2024, 5, 1),)]


def test_visits_and_observation_periods(con):
    assert one(
        con, "SELECT visit_source_value, visit_concept_id FROM cdm.visit_occurrence ORDER BY 1"
    ) == [("ambulatory", 9202), ("virtual", 722455)]
    assert one(
        con,
        "SELECT observation_period_start_date, observation_period_end_date "
        "FROM cdm.observation_period ORDER BY 1",
    ) == [
        (datetime.date(2020, 1, 1), datetime.date(2020, 1, 1)),
        (datetime.date(2024, 4, 1), datetime.date(2024, 4, 2)),
    ]


def test_events_route_by_standard_domain(con):
    conditions = one(
        con,
        "SELECT condition_source_value, condition_concept_id, "
        "condition_source_concept_id FROM cdm.condition_occurrence ORDER BY 1",
    )
    assert conditions == [
        ("C-COND", 910001, 910001),
        ("C-NOMAP", 0, 910004),
        ("Z99.9", 910001, 910003),
    ]
    # A Synthea "condition" whose standard concept is an Observation goes to observation.
    assert ("C-SOCIAL", 910002) in one(
        con, "SELECT observation_source_value, observation_concept_id FROM cdm.observation"
    )
    assert one(con, "SELECT drug_concept_id, drug_exposure_end_date FROM cdm.drug_exposure") == [
        (910005, datetime.date(2020, 1, 1))
    ]


def test_unmapped_codes_are_kept_with_concept_zero(con):
    assert one(
        con, "SELECT procedure_concept_id, procedure_source_value FROM cdm.procedure_occurrence"
    ) == [(0, "D9999")]


def test_values_and_units(con):
    assert one(
        con, "SELECT value_as_number, unit_concept_id, unit_source_value FROM cdm.measurement"
    ) == [(Decimal("0.0045"), 910008, "mg/dL")]
    assert one(
        con, "SELECT value_as_string FROM cdm.observation WHERE observation_source_value = 'L-TEXT'"
    ) == [("Never smoked",)]


def test_cdm_source_describes_the_build(con):
    assert one(
        con,
        "SELECT cdm_version, cdm_version_concept_id, vocabulary_version, source_release_date, "
        "cdm_release_date = CURRENT_DATE FROM cdm.cdm_source",
    ) == [("5.4", 902983, "v5.0 TEST", datetime.date(2024, 4, 2), True)]


def test_every_source_row_lands(etl):
    counts = etl[1]
    events = sum(
        len(SYNTHEA[n]) for n in ("conditions", "procedures", "medications", "observations")
    )
    loaded = sum(
        counts[t]
        for t in (
            "condition_occurrence",
            "procedure_occurrence",
            "drug_exposure",
            "measurement",
            "observation",
            "device_exposure",
        )
    )
    assert loaded + counts["unrouted"] == events
