"""Synthea CSV to OMOP CDM v5.4 in DuckDB.

Follows OHDSI ETL-Synthea (the correctness reference) for ids, type concepts, and observation
periods, with three deliberate differences:
- Codes with no standard concept are kept with concept_id 0 and their source value. ETL-Synthea
  drops them, which loses every dental procedure (CDT is not in the free Athena download).
- One visit per encounter. ETL-Synthea merges overlapping encounters.
- Visit classes and races that ETL-Synthea leaves at 0 get their standard concept.

Not converted yet: allergies, care plans, imaging studies, supplies, and the billing files.
"""

from pathlib import Path

import duckdb

SOURCES = (
    "patients",
    "encounters",
    "conditions",
    "procedures",
    "medications",
    "immunizations",
    "observations",
    "devices",
)

EHR = 32817
EHR_ENCOUNTER_RECORD = 32827
EHR_PRESCRIPTION = 32838
PERIOD_FROM_EHR = 32882

# Standard domain of the mapped concept -> target table, concept column, id column, date column.
DOMAIN_TABLES = {
    "Condition": (
        "condition_occurrence",
        "condition",
        "condition_occurrence_id",
        "condition_start",
    ),
    "Procedure": ("procedure_occurrence", "procedure", "procedure_occurrence_id", "procedure"),
    "Drug": ("drug_exposure", "drug", "drug_exposure_id", "drug_exposure_start"),
    "Measurement": ("measurement", "measurement", "measurement_id", "measurement"),
    "Observation": ("observation", "observation", "observation_id", "observation"),
    "Device": ("device_exposure", "device", "device_exposure_id", "device_exposure_start"),
}

# One row per clinical fact, in a common shape. Synthea's SYSTEM column names the code system
# for conditions and procedures; the other files use one system each.
EVENTS_SQL = f"""
CREATE TEMP TABLE events AS
SELECT 'Condition' AS default_domain, PATIENT, ENCOUNTER, START AS start_ts, STOP AS end_ts,
       CASE SYSTEM WHEN 'SNOMED-CT' THEN 'SNOMED' WHEN 'ICD10' THEN 'ICD10CM' ELSE SYSTEM END
           AS vocabulary_id,
       CODE AS code, NULL AS value_text, NULL AS units, {EHR_ENCOUNTER_RECORD} AS type_concept_id
FROM src_conditions
UNION ALL
SELECT 'Procedure', PATIENT, ENCOUNTER, START, STOP,
       CASE SYSTEM WHEN 'SNOMED-CT' THEN 'SNOMED' ELSE SYSTEM END,
       CODE, NULL, NULL, {EHR_ENCOUNTER_RECORD}
FROM src_procedures
UNION ALL
SELECT 'Drug', PATIENT, ENCOUNTER, START, STOP, 'RxNorm', CODE, NULL, NULL, {EHR_PRESCRIPTION}
FROM src_medications
UNION ALL
SELECT 'Drug', PATIENT, ENCOUNTER, DATE, DATE, 'CVX', CODE, NULL, NULL, {EHR_ENCOUNTER_RECORD}
FROM src_immunizations
UNION ALL
SELECT CASE TYPE WHEN 'numeric' THEN 'Measurement' ELSE 'Observation' END,
       PATIENT, ENCOUNTER, DATE, DATE, 'LOINC', CODE, VALUE, UNITS, {EHR_ENCOUNTER_RECORD}
FROM src_observations
UNION ALL
SELECT 'Device', PATIENT, ENCOUNTER, START, STOP, 'SNOMED', CODE, NULL, NULL, {EHR_ENCOUNTER_RECORD}
FROM src_devices
"""

# Source code -> source concept -> standard concept via "Maps to". A code can map to several
# standard concepts; each becomes its own row, which is the OMOP convention.
CODE_MAP_SQL = """
CREATE TEMP TABLE code_map AS
WITH codes AS (SELECT DISTINCT vocabulary_id, code FROM events),
targets AS (
    SELECT r.concept_id_1, t.concept_id, t.domain_id
    FROM cdm.concept_relationship r
    JOIN cdm.concept t ON t.concept_id = r.concept_id_2
    WHERE r.relationship_id = 'Maps to' AND r.invalid_reason IS NULL
      AND t.standard_concept = 'S' AND t.invalid_reason IS NULL
)
SELECT codes.vocabulary_id, codes.code,
       coalesce(src.concept_id, 0) AS source_concept_id,
       coalesce(targets.concept_id, 0) AS concept_id,
       targets.domain_id
FROM codes
LEFT JOIN cdm.concept src
  ON src.vocabulary_id = codes.vocabulary_id AND src.concept_code = codes.code
LEFT JOIN targets ON targets.concept_id_1 = src.concept_id
"""

MAPPED_SQL = """
CREATE TEMP TABLE mapped AS
SELECT coalesce(m.domain_id, e.default_domain) AS domain_id,
       p.person_id, v.visit_occurrence_id,
       CAST(e.start_ts AS TIMESTAMP) AS start_datetime,
       CAST(coalesce(e.end_ts, e.start_ts) AS TIMESTAMP) AS end_datetime,
       m.concept_id, m.source_concept_id, e.code AS source_value,
       TRY_CAST(e.value_text AS DOUBLE) AS value_as_number,
       e.value_text, e.units, coalesce(u.concept_id, 0) AS unit_concept_id,
       e.type_concept_id
FROM events e
JOIN person_map p ON p.patient = e.PATIENT
LEFT JOIN visit_map v ON v.encounter = e.ENCOUNTER
JOIN code_map m ON m.vocabulary_id = e.vocabulary_id AND m.code = e.code
LEFT JOIN cdm.concept u
  ON u.vocabulary_id = 'UCUM' AND u.concept_code = e.units AND u.standard_concept = 'S'
"""

# Columns beyond the shared ones, per target table.
EXTRA_COLUMNS = {
    "condition_occurrence": {
        "condition_end_date": "CAST(end_datetime AS DATE)",
        "condition_end_datetime": "end_datetime",
    },
    "drug_exposure": {
        "drug_exposure_end_date": "CAST(end_datetime AS DATE)",
        "drug_exposure_end_datetime": "end_datetime",
    },
    "measurement": {
        "value_as_number": "value_as_number",
        "unit_concept_id": "unit_concept_id",
        "unit_source_value": "units",
        "value_source_value": "value_text",
    },
    "observation": {
        "value_as_number": "value_as_number",
        "value_as_string": "CASE WHEN value_as_number IS NULL THEN value_text END",
        "unit_concept_id": "unit_concept_id",
        "unit_source_value": "units",
        "value_source_value": "value_text",
    },
    "device_exposure": {
        "device_exposure_end_date": "CAST(end_datetime AS DATE)",
        "device_exposure_end_datetime": "end_datetime",
    },
}


def _quote(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def run_etl(con: duckdb.DuckDBPyConnection, synthea_csv: Path) -> dict:
    """Convert one Synthea CSV export into the empty CDM tables. Returns row counts."""
    for name in SOURCES:
        con.execute(
            f"CREATE OR REPLACE TEMP VIEW src_{name} AS "
            f"SELECT * FROM read_csv({_quote(synthea_csv / f'{name}.csv')}, all_varchar = true)"
        )

    con.execute(
        "CREATE TEMP TABLE person_map AS "
        "SELECT Id AS patient, row_number() OVER (ORDER BY Id) AS person_id FROM src_patients"
    )
    con.execute("""
        INSERT INTO cdm.person (person_id, gender_concept_id, year_of_birth, month_of_birth,
            day_of_birth, birth_datetime, race_concept_id, ethnicity_concept_id,
            person_source_value, gender_source_value, gender_source_concept_id,
            race_source_value, race_source_concept_id, ethnicity_source_value,
            ethnicity_source_concept_id)
        SELECT m.person_id,
               CASE p.GENDER WHEN 'M' THEN 8507 WHEN 'F' THEN 8532 ELSE 0 END,
               year(b), month(b), day(b), CAST(b AS TIMESTAMP),
               CASE p.RACE WHEN 'white' THEN 8527 WHEN 'black' THEN 8516 WHEN 'asian' THEN 8515
                   WHEN 'hawaiian' THEN 8557 WHEN 'native' THEN 8657 ELSE 0 END,
               CASE p.ETHNICITY WHEN 'hispanic' THEN 38003563 WHEN 'nonhispanic' THEN 38003564
                   ELSE 0 END,
               p.Id, p.GENDER, 0, p.RACE, 0, p.ETHNICITY, 0
        FROM (SELECT *, CAST(BIRTHDATE AS DATE) AS b FROM src_patients) p
        JOIN person_map m ON m.patient = p.Id
    """)
    con.execute(f"""
        INSERT INTO cdm.death (person_id, death_date, death_datetime, death_type_concept_id)
        SELECT m.person_id, CAST(p.DEATHDATE AS DATE), CAST(p.DEATHDATE AS TIMESTAMP), {EHR}
        FROM src_patients p JOIN person_map m ON m.patient = p.Id
        WHERE p.DEATHDATE IS NOT NULL
    """)

    con.execute(
        "CREATE TEMP TABLE visit_map AS "
        "SELECT Id AS encounter, row_number() OVER (ORDER BY Id) AS visit_occurrence_id "
        "FROM src_encounters"
    )
    con.execute(f"""
        INSERT INTO cdm.visit_occurrence (visit_occurrence_id, person_id, visit_concept_id,
            visit_start_date, visit_start_datetime, visit_end_date, visit_end_datetime,
            visit_type_concept_id, visit_source_value, visit_source_concept_id,
            admitted_from_concept_id, discharged_to_concept_id, preceding_visit_occurrence_id)
        SELECT v.visit_occurrence_id, p.person_id,
               CASE e.ENCOUNTERCLASS
                   WHEN 'ambulatory' THEN 9202 WHEN 'wellness' THEN 9202
                   WHEN 'outpatient' THEN 9202 WHEN 'emergency' THEN 9203
                   WHEN 'urgentcare' THEN 9203 WHEN 'inpatient' THEN 9201
                   WHEN 'virtual' THEN 722455 WHEN 'home' THEN 581476
                   WHEN 'hospice' THEN 42898160 WHEN 'snf' THEN 42898160
                   ELSE 0 END,
               CAST(e.START AS DATE), CAST(e.START AS TIMESTAMP),
               CAST(e.STOP AS DATE), CAST(e.STOP AS TIMESTAMP),
               {EHR_ENCOUNTER_RECORD}, e.ENCOUNTERCLASS, 0, 0, 0,
               lag(v.visit_occurrence_id) OVER (PARTITION BY p.person_id ORDER BY e.START, e.Id)
        FROM src_encounters e
        JOIN visit_map v ON v.encounter = e.Id
        JOIN person_map p ON p.patient = e.PATIENT
    """)
    con.execute(f"""
        INSERT INTO cdm.observation_period (observation_period_id, person_id,
            observation_period_start_date, observation_period_end_date, period_type_concept_id)
        SELECT row_number() OVER (ORDER BY p.person_id), p.person_id,
               min(CAST(e.START AS DATE)), max(CAST(e.STOP AS DATE)), {PERIOD_FROM_EHR}
        FROM src_encounters e JOIN person_map p ON p.patient = e.PATIENT
        GROUP BY p.person_id
    """)

    con.execute(EVENTS_SQL)
    con.execute(CODE_MAP_SQL)
    con.execute(MAPPED_SQL)
    for domain, (table, prefix, id_column, date_prefix) in DOMAIN_TABLES.items():
        columns = {
            id_column: "row_number() OVER "
            "(ORDER BY person_id, start_datetime, concept_id, source_value)",
            "person_id": "person_id",
            f"{prefix}_concept_id": "concept_id",
            f"{date_prefix}_date": "CAST(start_datetime AS DATE)",
            f"{date_prefix}_datetime": "start_datetime",
            f"{prefix}_type_concept_id": "type_concept_id",
            "visit_occurrence_id": "visit_occurrence_id",
            f"{prefix}_source_value": "source_value",
            f"{prefix}_source_concept_id": "source_concept_id",
            **EXTRA_COLUMNS.get(table, {}),
        }
        con.execute(
            f"INSERT INTO cdm.{table} ({', '.join(columns)}) "
            f"SELECT {', '.join(columns.values())} FROM mapped WHERE domain_id = ?",
            [domain],
        )

    tables = ["person", "death", "visit_occurrence", "observation_period"]
    tables += [table for table, *_ in DOMAIN_TABLES.values()]
    counts = {t: con.execute(f"SELECT count(*) FROM cdm.{t}").fetchone()[0] for t in tables}
    # Mapped to a domain with no target table here (Note, Specimen, ...): counted, not loaded.
    placeholders = ", ".join("?" * len(DOMAIN_TABLES))
    counts["unrouted"] = con.execute(
        f"SELECT count(*) FROM mapped WHERE domain_id NOT IN ({placeholders})", list(DOMAIN_TABLES)
    ).fetchone()[0]
    return counts
