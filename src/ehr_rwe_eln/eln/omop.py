"""Write stored ELN extractions to OMOP: specimen and measurement rows, linked through
fact_relationship, for the subjects in the eln.subject registry.

Each run replaces every ELN-derived row, so it can be rerun after more extractions land and gives
the same ids for the same samples. ELN rows take ids from ID_OFFSET up, a range the Synthea ETL
(which numbers rows from 1) never reaches. Concepts are looked up by code, never hard-coded ids.
"""

import psycopg

# Above every Synthea ETL id; leaves room for about 147 million ELN rows in an integer column.
ID_OFFSET = 2_000_000_000
LAB = 32856  # Type Concept: Lab
MEASUREMENT_DOMAIN, SPECIMEN_DOMAIN = 21, 36
MEASUREMENT_TO_SPECIMEN, SPECIMEN_TO_MEASUREMENT = 32668, 32669

# SNOMED codes for the specimen types.
SPECIMEN_SNOMED = {
    "serum": "119364003",
    "plasma": "119361006",
    "whole blood": "119297000",
    "urine": "122575003",
}
# LOINC codes by analyte and unit: the unit decides the property (mass vs substance concentration).
# A pair missing here maps to concept 0, as OMOP specifies for an unmapped source value.
ANALYTE_LOINC = {
    ("creatinine", "mg/dL"): "2160-0",
    ("creatinine", "umol/L"): "14682-9",
    ("hba1c", "%"): "4548-4",
    ("hba1c", "mmol/mol"): "59261-8",
    ("crp", "mg/L"): "1988-5",
    ("hs_crp", "mg/L"): "30522-7",
    ("il6", "pg/mL"): "26881-3",
    ("nt_probnp", "pg/mL"): "33762-6",
}

SAMPLES_SQL = """
CREATE TEMP TABLE eln_samples AS
WITH extracted AS (
    SELECT x.entry_id, e.created, s
    FROM eln.extraction x
    JOIN eln.entry e USING (entry_id)
    CROSS JOIN jsonb_array_elements(x.extraction -> 'samples') s
    WHERE x.extraction IS NOT NULL
),
-- A sample reported in two entries is one specimen: keep its first entry.
first AS (
    SELECT DISTINCT ON (s ->> 'sample_id') entry_id, created, s
    FROM extracted ORDER BY s ->> 'sample_id', entry_id
)
SELECT %(offset)s + row_number() OVER (ORDER BY f.s ->> 'sample_id') AS specimen_id,
       f.s ->> 'sample_id' AS sample_id,
       f.s ->> 'subject_id' AS subject_id,
       f.s ->> 'specimen_type' AS specimen_type,
       sub.person_id,
       -- The entry's date when the collection date is not stated: the specimen existed by then.
       coalesce((f.s ->> 'collection_date')::date, f.created) AS specimen_date,
       f.s ->> 'collection_date' IS NULL AS date_from_entry
FROM first f
JOIN eln.subject sub ON sub.subject_id = f.s ->> 'subject_id'
"""

RESULTS_SQL = """
CREATE TEMP TABLE eln_results AS
WITH extracted AS (
    SELECT DISTINCT ON (r ->> 'sample_id', r ->> 'analyte') r
    FROM eln.extraction x CROSS JOIN jsonb_array_elements(x.extraction -> 'results') r
    WHERE x.extraction IS NOT NULL
    ORDER BY r ->> 'sample_id', r ->> 'analyte', x.entry_id
)
SELECT r ->> 'sample_id' AS sample_id, r ->> 'analyte' AS analyte,
       (r ->> 'value')::numeric AS value, r ->> 'unit' AS unit
FROM extracted
"""


def stage(con: psycopg.Connection) -> None:
    """Temp tables eln_samples and eln_results: one row per sample (with its OMOP specimen id)
    and per result, deduplicated across entries. The OMOP and FHIR outputs both read these."""
    con.execute("DROP TABLE IF EXISTS eln_samples, eln_results")
    con.execute(SAMPLES_SQL, {"offset": ID_OFFSET})
    con.execute(RESULTS_SQL)


def write_omop(con: psycopg.Connection) -> dict[str, int]:
    """Replace the ELN rows in cdm.specimen, cdm.measurement, and cdm.fact_relationship.
    Returns counts, including what was skipped and why."""
    con.execute("DROP TABLE IF EXISTS eln_specimen_codes, eln_analyte_codes, eln_measurements")
    con.execute(
        "DELETE FROM cdm.fact_relationship WHERE (domain_concept_id_1 = %s AND fact_id_1 >= %s)"
        " OR (domain_concept_id_1 = %s AND fact_id_1 >= %s)",
        [MEASUREMENT_DOMAIN, ID_OFFSET, SPECIMEN_DOMAIN, ID_OFFSET],
    )
    con.execute("DELETE FROM cdm.measurement WHERE measurement_id >= %s", [ID_OFFSET])
    con.execute("DELETE FROM cdm.specimen WHERE specimen_id >= %s", [ID_OFFSET])

    stage(con)
    con.execute("CREATE TEMP TABLE eln_specimen_codes (specimen_type text, code text)")
    con.execute("CREATE TEMP TABLE eln_analyte_codes (analyte text, unit text, code text)")
    with con.cursor() as cur:
        cur.executemany("INSERT INTO eln_specimen_codes VALUES (%s, %s)", SPECIMEN_SNOMED.items())
        cur.executemany(
            "INSERT INTO eln_analyte_codes VALUES (%s, %s, %s)",
            [(a, u, code) for (a, u), code in ANALYTE_LOINC.items()],
        )

    specimens = con.execute(
        """
        INSERT INTO cdm.specimen (specimen_id, person_id, specimen_concept_id,
            specimen_type_concept_id, specimen_date, specimen_source_id, specimen_source_value)
        SELECT s.specimen_id, s.person_id, coalesce(c.concept_id, 0), %s, s.specimen_date,
               s.sample_id, s.specimen_type
        FROM eln_samples s
        LEFT JOIN eln_specimen_codes m USING (specimen_type)
        LEFT JOIN cdm.concept c ON c.vocabulary_id = 'SNOMED' AND c.concept_code = m.code
        """,
        [LAB],
    ).rowcount
    # Each measurement with its specimen, so both tables fill from one place.
    con.execute(
        """
        CREATE TEMP TABLE eln_measurements AS
        SELECT %s + row_number() OVER (ORDER BY r.sample_id, r.analyte) AS measurement_id,
               s.specimen_id, s.person_id, coalesce(lc.concept_id, 0) AS concept_id,
               s.specimen_date, r.value, coalesce(uc.concept_id, 0) AS unit_concept_id,
               r.analyte, r.unit
        FROM eln_results r
        JOIN eln_samples s USING (sample_id)
        LEFT JOIN eln_analyte_codes m USING (analyte, unit)
        LEFT JOIN cdm.concept lc ON lc.vocabulary_id = 'LOINC' AND lc.concept_code = m.code
        LEFT JOIN cdm.concept uc ON uc.vocabulary_id = 'UCUM' AND uc.concept_code = r.unit
        """,
        [ID_OFFSET],
    )
    measurements = con.execute(
        """
        INSERT INTO cdm.measurement (measurement_id, person_id, measurement_concept_id,
            measurement_date, measurement_type_concept_id, value_as_number, unit_concept_id,
            measurement_source_value, unit_source_value)
        SELECT measurement_id, person_id, concept_id, specimen_date, %s, value, unit_concept_id,
               analyte, unit
        FROM eln_measurements
        """,
        [LAB],
    ).rowcount
    # OMOP records a relationship in both directions.
    con.execute(
        """
        INSERT INTO cdm.fact_relationship
        SELECT %(m)s, measurement_id, %(s)s, specimen_id, %(m_to_s)s FROM eln_measurements
        UNION ALL
        SELECT %(s)s, specimen_id, %(m)s, measurement_id, %(s_to_m)s FROM eln_measurements
        """,
        {
            "m": MEASUREMENT_DOMAIN,
            "s": SPECIMEN_DOMAIN,
            "m_to_s": MEASUREMENT_TO_SPECIMEN,
            "s_to_m": SPECIMEN_TO_MEASUREMENT,
        },
    )
    skipped_subjects = con.execute(
        "SELECT count(DISTINCT s ->> 'sample_id') FROM eln.extraction x"
        " CROSS JOIN jsonb_array_elements(x.extraction -> 'samples') s"
        " WHERE x.extraction IS NOT NULL"
        " AND s ->> 'subject_id' NOT IN (SELECT subject_id FROM eln.subject)"
    ).fetchone()[0]
    return {
        "specimens": specimens,
        "measurements": measurements,
        "specimen_dates_from_entry": con.execute(
            "SELECT count(*) FROM eln_samples WHERE date_from_entry"
        ).fetchone()[0],
        "unmapped_measurements": con.execute(
            "SELECT count(*) FROM eln_measurements WHERE concept_id = 0"
        ).fetchone()[0],
        "samples_of_unknown_subjects": skipped_subjects,
        "results_without_a_sample": con.execute(
            "SELECT count(*) FROM eln_results r"
            " WHERE NOT EXISTS (SELECT 1 FROM eln_samples s WHERE s.sample_id = r.sample_id)"
        ).fetchone()[0],
    }
