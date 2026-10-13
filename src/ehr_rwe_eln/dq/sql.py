"""Postgres ports of DQD v2.9.0's check SQL (inst/sql/sql_server), one function per check type.

Each query returns num_violated_rows and num_denominator_rows. DQD's templates are written in
SqlRender's SQL Server dialect; these keep their logic and use the Postgres translations
SqlRender would produce. Cohort filtering is not ported. Table, field, and value text all come
from the vendored CSVs, never from user input.
"""

import re
from collections.abc import Callable

from ehr_rwe_eln.dq.checks import Check

# The CSV writes some plausible value bounds in SQL Server's dialect. These are all of them.
BOUNDS = {
    "DATEADD(dd,1,GETDATE())": "CURRENT_DATE + 1",
    "YEAR(GETDATE())+1": "EXTRACT(YEAR FROM CURRENT_DATE) + 1",
}

# Concept checks put the CSV's comma separated id lists straight into IN (...).
ID_LIST = re.compile(r"-?\d+(\s*,\s*-?\d+)*")

# DQD's plausible gender values, as the gender concepts its templates compare against.
GENDER_CONCEPTS = {"Male": 8507, "Female": 8532}

# SqlRender's Postgres translation of ISNUMERIC.
NUMERIC = r"'^[\-\+]?([0-9]+\.?[0-9]*|\.[0-9]+)$'"

# For these concept fields, a NULL concept next to a filled source value also counts as missing.
SOURCE_VALUE_COLUMNS = {
    "ADMITTED_FROM_CONCEPT_ID": "admitted_from_source_value",
    "ADMITTING_SOURCE_CONCEPT_ID": "admitting_source_value",
    "DISCHARGED_TO_CONCEPT_ID": "discharged_to_source_value",
    "DISCHARGE_TO_CONCEPT_ID": "discharge_to_source_value",
    "CONDITION_STATUS_CONCEPT_ID": "condition_status_source_value",
    "ROUTE_CONCEPT_ID": "route_source_value",
    "MODIFIER_CONCEPT_ID": "modifier_source_value",
    "QUALIFIER_CONCEPT_ID": "qualifier_source_value",
    "CAUSE_CONCEPT_ID": "cause_source_value",
    "CAUSE_SOURCE_CONCEPT_ID": "cause_source_value",
    "ANATOMIC_SITE_CONCEPT_ID": "anatomic_site_source_value",
    "DISEASE_STATUS_CONCEPT_ID": "disease_status_source_value",
    "COUNTRY_CONCEPT_ID": "country_source_value",
    "PLACE_OF_SERVICE_CONCEPT_ID": "place_of_service_source_value",
    "SPECIALTY_CONCEPT_ID": "specialty_source_value",
    "SPECIALTY_SOURCE_CONCEPT_ID": "specialty_source_value",
    "PAYER_CONCEPT_ID": "payer_source_value",
    "PAYER_SOURCE_CONCEPT_ID": "payer_source_value",
    "PLAN_CONCEPT_ID": "plan_source_value",
    "PLAN_SOURCE_CONCEPT_ID": "plan_source_value",
    "SPONSOR_CONCEPT_ID": "sponsor_source_value",
    "SPONSOR_SOURCE_CONCEPT_ID": "sponsor_source_value",
    "STOP_REASON_CONCEPT_ID": "stop_reason_source_value",
    "STOP_REASON_SOURCE_CONCEPT_ID": "stop_reason_source_value",
}


def _query(violated: str, denominator: str) -> str:
    return f"SELECT ({violated}) AS num_violated_rows, ({denominator}) AS num_denominator_rows"


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _ids(value: str) -> str:
    if not ID_LIST.fullmatch(value.strip()):
        raise ValueError(f"not a concept id list: {value!r}")
    return value


def _source_value_column(table: str, field: str) -> str | None:
    if field in ("UNIT_CONCEPT_ID", "UNIT_SOURCE_CONCEPT_ID"):
        return None if table == "DOSE_ERA" else "unit_source_value"
    if field in ("GENDER_CONCEPT_ID", "GENDER_SOURCE_CONCEPT_ID"):
        return "gender_source_value" if table == "PROVIDER" else None
    return SOURCE_VALUE_COLUMNS.get(field)


def cdm_table(s: str, t: str, f: str, p: dict) -> str:
    return _query(f"SELECT CASE WHEN count(*) = 0 THEN 0 ELSE 0 END FROM {s}.{t}", "SELECT 1")


def cdm_field(s: str, t: str, f: str, p: dict) -> str:
    return _query(f"SELECT CASE WHEN count({f}) = 0 THEN 0 ELSE 0 END FROM {s}.{t}", "SELECT 1")


def measure_person_completeness(s: str, t: str, f: str, p: dict) -> str:
    return _query(
        f"SELECT count(p.person_id) FROM {s}.person p"
        f" LEFT JOIN {s}.{t} x ON p.person_id = x.person_id WHERE x.person_id IS NULL",
        f"SELECT count(*) FROM {s}.person",
    )


def measure_condition_era_completeness(s: str, t: str, f: str, p: dict) -> str:
    return _query(
        f"SELECT count(v.person_id) FROM (SELECT DISTINCT co.person_id"
        f" FROM {s}.condition_occurrence co LEFT JOIN {s}.{t} x ON co.person_id = x.person_id"
        f" WHERE x.person_id IS NULL AND co.condition_concept_id <> 0) v",
        f"SELECT count(DISTINCT person_id) FROM {s}.condition_occurrence"
        f" WHERE condition_concept_id <> 0",
    )


def measure_observation_period_overlap(s: str, t: str, f: str, p: dict) -> str:
    return _query(
        f"SELECT count(v.person_id) FROM (SELECT DISTINCT a.person_id"
        f" FROM {s}.observation_period a JOIN {s}.observation_period b"
        f" ON a.person_id = b.person_id AND a.observation_period_id <> b.observation_period_id"
        f" WHERE (a.observation_period_start_date <= b.observation_period_end_date"
        f" AND a.observation_period_end_date >= b.observation_period_start_date)"
        f" OR a.observation_period_end_date + 1 = b.observation_period_start_date"
        f" OR b.observation_period_end_date + 1 = a.observation_period_start_date) v",
        f"SELECT count(DISTINCT person_id) FROM {s}.observation_period",
    )


def is_null(s: str, t: str, f: str, p: dict) -> str:
    return _query(
        f"SELECT count(*) FROM {s}.{t} WHERE {f} IS NULL", f"SELECT count(*) FROM {s}.{t}"
    )


def cdm_datatype(s: str, t: str, f: str, p: dict) -> str:
    return _query(
        f"SELECT count(*) FROM {s}.{t} WHERE {f} IS NOT NULL"
        f" AND (CAST({f} AS VARCHAR) !~ {NUMERIC} OR strpos(CAST(abs({f}) AS VARCHAR), '.') <> 0)",
        f"SELECT count(*) FROM {s}.{t}",
    )


def is_primary_key(s: str, t: str, f: str, p: dict) -> str:
    return _query(
        f"SELECT count(*) FROM {s}.{t}"
        f" WHERE {f} IN (SELECT {f} FROM {s}.{t} GROUP BY {f} HAVING count(*) > 1)",
        f"SELECT count(*) FROM {s}.{t}",
    )


def is_foreign_key(s: str, t: str, f: str, p: dict) -> str:
    fk_table, fk_field = p["fkTableName"].lower(), p["fkFieldName"].lower()
    return _query(
        f"SELECT count(*) FROM {s}.{t} x LEFT JOIN {s}.{fk_table} y ON x.{f} = y.{fk_field}"
        f" WHERE y.{fk_field} IS NULL AND x.{f} IS NOT NULL",
        f"SELECT count(*) FROM {s}.{t}",
    )


def fk_domain(s: str, t: str, f: str, p: dict) -> str:
    return _query(
        f"SELECT count(*) FROM {s}.{t} x LEFT JOIN {s}.concept co ON x.{f} = co.concept_id"
        f" WHERE co.concept_id <> 0 AND co.domain_id NOT IN ({_literal(p['fkDomain'])})",
        f"SELECT count(*) FROM {s}.{t}",
    )


def fk_class(s: str, t: str, f: str, p: dict) -> str:
    return _query(
        f"SELECT count(*) FROM {s}.{t} x LEFT JOIN {s}.concept co ON x.{f} = co.concept_id"
        f" WHERE co.concept_id <> 0 AND co.concept_class_id <> {_literal(p['fkClass'])}",
        f"SELECT count(*) FROM {s}.{t}",
    )


def is_standard_valid_concept(s: str, t: str, f: str, p: dict) -> str:
    return _query(
        f"SELECT count(*) FROM {s}.{t} x JOIN {s}.concept co ON x.{f} = co.concept_id"
        f" WHERE co.concept_id <> 0 AND (co.standard_concept <> 'S'"
        f" OR co.invalid_reason IS NOT NULL OR co.standard_concept IS NULL)",
        f"SELECT count(*) FROM {s}.{t} WHERE {f} IS NOT NULL",
    )


def concept_record_completeness(s: str, t: str, f: str, p: dict) -> str:
    violated, counted = f"{f} = 0", f"{f} IS NOT NULL"
    if source := _source_value_column(p["cdmTableName"], p["cdmFieldName"]):
        violated += f" OR ({f} IS NULL AND {source} IS NOT NULL)"
        counted += f" OR {source} IS NOT NULL"
    return _query(
        f"SELECT count(*) FROM {s}.{t} WHERE {violated}",
        f"SELECT count(*) FROM {s}.{t} WHERE {counted}",
    )


def source_value_completeness(s: str, t: str, f: str, p: dict) -> str:
    standard = p["standardConceptFieldName"].lower()
    return _query(
        f"SELECT count(*) FROM (SELECT DISTINCT {f} FROM {s}.{t} WHERE {standard} = 0) v",
        f"SELECT count(DISTINCT {f}) + count(DISTINCT CASE WHEN {f} IS NULL THEN 1 END)"
        f" FROM {s}.{t}",
    )


def _plausible_value(s: str, t: str, f: str, p: dict, op: str, bound: str) -> str:
    bound = BOUNDS.get(bound, bound)
    if p["cdmDatatype"] in ("date", "datetime"):
        condition = f"CAST({f} AS DATE) {op} CAST({bound} AS DATE)"
    else:
        condition = f"{f} {op} {bound}"
    return _query(
        f"SELECT count(*) FROM {s}.{t} WHERE {condition}",
        f"SELECT count(*) FROM {s}.{t} WHERE {f} IS NOT NULL",
    )


def plausible_value_low(s: str, t: str, f: str, p: dict) -> str:
    return _plausible_value(s, t, f, p, "<", p["plausibleValueLow"])


def plausible_value_high(s: str, t: str, f: str, p: dict) -> str:
    return _plausible_value(s, t, f, p, ">", p["plausibleValueHigh"])


def plausible_temporal_after(s: str, t: str, f: str, p: dict) -> str:
    after_table = p["plausibleTemporalAfterTableName"]
    after_field = p["plausibleTemporalAfterFieldName"].lower()
    if after_table == p["cdmTableName"]:
        source, after = f"{s}.{t} x", f"CAST(x.{after_field} AS DATE)"
    elif after_table == "PERSON":
        # With no birth date, DQD assumes the middle of the birth year.
        source = f"{s}.{t} x JOIN {s}.person pt ON x.person_id = pt.person_id"
        after = (
            f"COALESCE(CAST(pt.{after_field} AS DATE),"
            f" CAST(CONCAT(pt.year_of_birth, '0601') AS DATE))"
        )
    else:
        raise ValueError(f"no port for plausibleTemporalAfter against {after_table}")
    return _query(
        f"SELECT count(*) FROM {source} WHERE {after} > CAST(x.{f} AS DATE)",
        f"SELECT count(*) FROM {s}.{t}",
    )


def plausible_during_life(s: str, t: str, f: str, p: dict) -> str:
    return _query(
        f"SELECT count(*) FROM {s}.{t} x JOIN {s}.death de ON x.person_id = de.person_id"
        f" WHERE CAST(x.{f} AS DATE) > CAST(de.death_date AS DATE) + 60",
        f"SELECT count(*) FROM {s}.{t} WHERE person_id IN (SELECT person_id FROM {s}.death)",
    )


def within_visit_dates(s: str, t: str, f: str, p: dict) -> str:
    joined = (
        f"{s}.{t} x JOIN {s}.visit_occurrence vo ON x.visit_occurrence_id = vo.visit_occurrence_id"
    )
    return _query(
        f"SELECT count(*) FROM {joined}"
        f" WHERE x.{f} < vo.visit_start_date - 7 OR x.{f} > vo.visit_end_date + 7",
        f"SELECT count(*) FROM {joined}",
    )


def plausible_after_birth(s: str, t: str, f: str, p: dict) -> str:
    birth = (
        "COALESCE(CAST(pe.birth_datetime AS DATE), make_date(pe.year_of_birth,"
        " COALESCE(pe.month_of_birth, 1), COALESCE(pe.day_of_birth, 1)))"
    )
    return _query(
        f"SELECT count(*) FROM {s}.{t} x JOIN {s}.person pe ON x.person_id = pe.person_id"
        f" WHERE x.{f} IS NOT NULL AND CAST(x.{f} AS DATE) < {birth}",
        f"SELECT count(*) FROM {s}.{t} WHERE {f} IS NOT NULL",
    )


def plausible_before_death(s: str, t: str, f: str, p: dict) -> str:
    joined = f"{s}.{t} x JOIN {s}.death de ON x.person_id = de.person_id"
    return _query(
        f"SELECT count(*) FROM {joined}"
        f" WHERE x.{f} IS NOT NULL AND CAST(x.{f} AS DATE) > de.death_date + 60",
        f"SELECT count(*) FROM {joined} WHERE x.{f} IS NOT NULL",
    )


def plausible_start_before_end(s: str, t: str, f: str, p: dict) -> str:
    end = p["plausibleStartBeforeEndFieldName"].lower()
    both = f"{f} IS NOT NULL AND {end} IS NOT NULL"
    return _query(
        f"SELECT count(*) FROM {s}.{t} WHERE {both} AND CAST({f} AS DATE) > CAST({end} AS DATE)",
        f"SELECT count(*) FROM {s}.{t} WHERE {both}",
    )


def plausible_gender(s: str, t: str, f: str, p: dict) -> str:
    gender = GENDER_CONCEPTS[p["plausibleGender"]]
    concepts = _ids(p["conceptId"])
    return _query(
        f"SELECT count(*) FROM {s}.{t} x JOIN {s}.person pe ON x.person_id = pe.person_id"
        f" WHERE x.{f} IN ({concepts}) AND pe.gender_concept_id <> {gender}",
        f"SELECT count(*) FROM {s}.{t} WHERE {f} IN ({concepts})",
    )


def plausible_gender_use_descendants(s: str, t: str, f: str, p: dict) -> str:
    gender = GENDER_CONCEPTS[p["plausibleGenderUseDescendants"]]
    joined = f"{s}.{t} x JOIN {s}.concept_ancestor ca ON ca.descendant_concept_id = x.{f}"
    within = f"ca.ancestor_concept_id IN ({_ids(p['conceptId'])})"
    return _query(
        f"SELECT count(*) FROM {joined} JOIN {s}.person pe ON x.person_id = pe.person_id"
        f" WHERE {within} AND pe.gender_concept_id <> {gender}",
        f"SELECT count(*) FROM {joined} WHERE {within}",
    )


def plausible_unit_concept_ids(s: str, t: str, f: str, p: dict) -> str:
    units = _ids(p["plausibleUnitConceptIds"])
    concept = _ids(p["conceptId"])
    # A list of -1 means no unit is plausible: any mapped unit violates.
    return _query(
        f"SELECT count(*) FROM {s}.{t} WHERE {f} = {concept} AND unit_concept_id IS NOT NULL"
        f" AND (({_literal(units)} = '-1' AND unit_concept_id <> 0)"
        f" OR unit_concept_id NOT IN ({units}, 0))",
        f"SELECT count(*) FROM {s}.{t} WHERE {f} = {concept}"
        f" AND (unit_concept_id <> 0 OR unit_concept_id IS NULL)",
    )


PORTS: dict[str, Callable[[str, str, str, dict], str]] = {
    "cdmTable": cdm_table,
    "measurePersonCompleteness": measure_person_completeness,
    "measureConditionEraCompleteness": measure_condition_era_completeness,
    "measureObservationPeriodOverlap": measure_observation_period_overlap,
    "cdmField": cdm_field,
    "isRequired": is_null,
    "cdmDatatype": cdm_datatype,
    "isPrimaryKey": is_primary_key,
    "isForeignKey": is_foreign_key,
    "fkDomain": fk_domain,
    "fkClass": fk_class,
    "isStandardValidConcept": is_standard_valid_concept,
    "measureValueCompleteness": is_null,
    "standardConceptRecordCompleteness": concept_record_completeness,
    "sourceConceptRecordCompleteness": concept_record_completeness,
    "sourceValueCompleteness": source_value_completeness,
    "plausibleValueLow": plausible_value_low,
    "plausibleValueHigh": plausible_value_high,
    "plausibleTemporalAfter": plausible_temporal_after,
    "plausibleDuringLife": plausible_during_life,
    "withinVisitDates": within_visit_dates,
    "plausibleAfterBirth": plausible_after_birth,
    "plausibleBeforeDeath": plausible_before_death,
    "plausibleStartBeforeEnd": plausible_start_before_end,
    "plausibleGender": plausible_gender,
    "plausibleGenderUseDescendants": plausible_gender_use_descendants,
    "plausibleUnitConceptIds": plausible_unit_concept_ids,
}


def check_sql(check: Check, schema: str = "cdm") -> str:
    field = check.field.lower() if check.field else ""
    return PORTS[check.name](schema, check.table.lower(), field, check.params)
