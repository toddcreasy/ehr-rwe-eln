from datetime import date

import pytest

from ehr_rwe_eln.cohort.cdm import create_cdm
from ehr_rwe_eln.eln.models import Extraction, Result, Sample
from ehr_rwe_eln.eln.omop import ID_OFFSET, write_omop
from ehr_rwe_eln.eln.store import load_entries, load_subjects, save_extraction

CONCEPTS = [
    (4001181, "SNOMED", "119364003"),  # Serum specimen
    (3020460, "LOINC", "1988-5"),  # CRP, mass/volume
    (3016723, "LOINC", "2160-0"),  # creatinine, mass/volume
    (8751, "UCUM", "mg/L"),
    (8840, "UCUM", "mg/dL"),
]
EXTRACTION = Extraction(
    samples=[
        Sample(
            sample_id="S-A",
            subject_id="HTN-0001",
            specimen_type="serum",
            collection_date=date(2021, 1, 5),
        ),
        Sample(sample_id="S-B", subject_id="HTN-0002", specimen_type="serum"),
        Sample(sample_id="S-C", subject_id="HTN-9999", specimen_type="serum"),
    ],
    results=[
        Result(sample_id="S-A", analyte="crp", value=2.2, unit="mg/L"),
        Result(sample_id="S-A", analyte="creatinine", value=1.1, unit="mg/dL"),
        Result(sample_id="S-B", analyte="crp", value=5.0, unit="mg/L"),
        # IL-6's LOINC and pg/mL are not in this test vocabulary: concept 0.
        Result(sample_id="S-B", analyte="il6", value=3.0, unit="pg/mL"),
        Result(sample_id="S-Z", analyte="crp", value=1.0, unit="mg/L"),
    ],
)


@pytest.fixture
def con(pg, dq_schema):
    create_cdm(pg)
    for concept_id, vocabulary, code in CONCEPTS:
        pg.execute(
            "INSERT INTO cdm.concept VALUES (%s, 'x', 'x', %s, 'x', 'S', %s, '2000-01-01',"
            " '2099-12-31', NULL)",
            [concept_id, vocabulary, code],
        )
    # A Synthea ETL row the ELN load must never touch.
    pg.execute(
        "INSERT INTO cdm.measurement (measurement_id, person_id, measurement_concept_id,"
        " measurement_date, measurement_type_concept_id) VALUES (5, 1, 0, '2020-01-01', 32817)"
    )
    load_subjects(pg, {"HTN-0001": 1, "HTN-0002": 2})
    load_entries(pg, [("E1", "t", "a", date(2021, 2, 1), "body")])
    save_extraction(pg, "E1", "m", "b", EXTRACTION, None)
    return pg


def test_specimens_measurements_and_links(con):
    counts = write_omop(con)
    assert counts == {
        "specimens": 2,
        "measurements": 4,
        "specimen_dates_from_entry": 1,
        "unmapped_measurements": 1,
        "samples_of_unknown_subjects": 1,
        "results_without_a_sample": 1,
    }
    specimens = con.execute(
        "SELECT specimen_id, person_id, specimen_concept_id, specimen_date, specimen_source_id"
        " FROM cdm.specimen ORDER BY specimen_id"
    ).fetchall()
    assert specimens == [
        (ID_OFFSET + 1, 1, 4001181, date(2021, 1, 5), "S-A"),
        # No collection date: the entry's date.
        (ID_OFFSET + 2, 2, 4001181, date(2021, 2, 1), "S-B"),
    ]
    measurements = con.execute(
        "SELECT measurement_id, person_id, measurement_concept_id, measurement_date,"
        " value_as_number, unit_concept_id, measurement_source_value FROM cdm.measurement"
        " WHERE measurement_id >= %s ORDER BY measurement_id",
        [ID_OFFSET],
    ).fetchall()
    assert [(m[2], float(m[4]), m[5], m[6]) for m in measurements] == [
        (3016723, 1.1, 8840, "creatinine"),
        (3020460, 2.2, 8751, "crp"),
        (3020460, 5.0, 8751, "crp"),
        (0, 3.0, 0, "il6"),
    ]
    assert [m[3] for m in measurements] == [date(2021, 1, 5)] * 2 + [date(2021, 2, 1)] * 2
    links = con.execute(
        "SELECT domain_concept_id_1, fact_id_1, domain_concept_id_2, fact_id_2,"
        " relationship_concept_id FROM cdm.fact_relationship ORDER BY 1, 2"
    ).fetchall()
    assert len(links) == 8
    assert (21, ID_OFFSET + 1, 36, ID_OFFSET + 1, 32668) in links
    assert (36, ID_OFFSET + 2, 21, ID_OFFSET + 4, 32669) in links


def test_rerun_replaces_with_the_same_rows_and_leaves_etl_rows(con):
    write_omop(con)
    first = con.execute("SELECT * FROM cdm.measurement ORDER BY measurement_id").fetchall()
    write_omop(con)
    assert con.execute("SELECT * FROM cdm.measurement ORDER BY measurement_id").fetchall() == first
    assert con.execute("SELECT count(*) FROM cdm.fact_relationship").fetchone()[0] == 8
    assert (
        con.execute("SELECT count(*) FROM cdm.measurement WHERE measurement_id = 5").fetchone()[0]
        == 1
    )
