"""Build a protocol's analysis table: one row per eligible person, with arm and follow-up.

Time zero is each person's first day on either strategy; their arm is whichever they started.
Eligibility is checked on that same day, so eligibility, assignment, and the start of follow-up
line up and no person-time is counted before treatment starts (immortal time). Rules apply in
order and are counted as they go, the attrition table a trial report starts with.
"""

import pandas as pd
import psycopg

from ehr_rwe_eln.tte.protocol import ConceptSet, Protocol


def _concepts(concept_set: ConceptSet) -> tuple[str, list]:
    sql = "SELECT unnest(%s::integer[])"
    params: list = [concept_set.concept_ids]
    if concept_set.include_descendants:
        sql += (
            " UNION SELECT descendant_concept_id FROM cdm.concept_ancestor"
            " WHERE ancestor_concept_id = ANY(%s::integer[])"
        )
        params.append(concept_set.concept_ids)
    return sql, params


def build_analysis_table(
    con: psycopg.Connection, protocol: Protocol
) -> tuple[list[tuple[str, int]], pd.DataFrame]:
    """Returns the attrition table, (rule, persons remaining) pairs, and the analysis table."""
    treatment, treatment_params = _concepts(protocol.strategies.treatment.drugs)
    comparator, comparator_params = _concepts(protocol.strategies.comparator.drugs)
    diagnosis, diagnosis_params = _concepts(protocol.eligibility.diagnosis)
    outcome, outcome_params = _concepts(protocol.outcome.conditions)

    con.execute("DROP TABLE IF EXISTS tte_candidates")
    con.execute(
        f"""
        CREATE TEMP TABLE tte_candidates AS
        WITH treatment AS ({treatment}), comparator AS ({comparator}),
        diagnosis AS ({diagnosis}), outcome AS ({outcome}),
        first_use AS (
            SELECT person_id,
                   min(drug_exposure_start_date) FILTER (
                       WHERE drug_concept_id IN (SELECT * FROM treatment)) AS treatment_start,
                   min(drug_exposure_start_date) FILTER (
                       WHERE drug_concept_id IN (SELECT * FROM comparator)) AS comparator_start
            FROM cdm.drug_exposure
            WHERE drug_concept_id IN (SELECT * FROM treatment UNION SELECT * FROM comparator)
            GROUP BY person_id
        ),
        starts AS (
            SELECT person_id,
                   least(treatment_start, comparator_start) AS time_zero,
                   -- 1 treatment, 0 comparator; NULL when both start the same day
                   CASE WHEN comparator_start IS NULL OR treatment_start < comparator_start THEN 1
                        WHEN treatment_start IS NULL OR comparator_start < treatment_start THEN 0
                   END AS arm
            FROM first_use
        )
        SELECT s.person_id, s.time_zero, s.arm, p.gender_concept_id,
               extract(year FROM age(s.time_zero, make_date(p.year_of_birth,
                   coalesce(p.month_of_birth, 1), coalesce(p.day_of_birth, 1))))::integer AS age,
               op.observation_period_start_date AS op_start,
               op.observation_period_end_date AS op_end,
               (SELECT min(co.condition_start_date) FROM cdm.condition_occurrence co
                WHERE co.person_id = s.person_id
                  AND co.condition_concept_id IN (SELECT * FROM diagnosis)) AS diagnosis_date,
               EXISTS (SELECT FROM cdm.condition_occurrence co
                       WHERE co.person_id = s.person_id AND co.condition_start_date <= s.time_zero
                         AND co.condition_concept_id IN (SELECT * FROM outcome)) AS prior_outcome,
               (SELECT min(co.condition_start_date) FROM cdm.condition_occurrence co
                WHERE co.person_id = s.person_id AND co.condition_start_date > s.time_zero
                  AND co.condition_concept_id IN (SELECT * FROM outcome)) AS outcome_date,
               d.death_date
        FROM starts s
        JOIN cdm.person p USING (person_id)
        LEFT JOIN cdm.observation_period op
          ON op.person_id = s.person_id
         AND s.time_zero BETWEEN op.observation_period_start_date
                             AND op.observation_period_end_date
        LEFT JOIN cdm.death d ON d.person_id = s.person_id
        """,
        treatment_params + comparator_params + diagnosis_params + outcome_params,
    )

    rule = protocol.eligibility
    rules = [
        ("started one strategy before the other", "arm IS NOT NULL", []),
        ("time zero inside an observation period", "op_start IS NOT NULL", []),
        (
            f"at least {rule.prior_observation_days} days of prior observation",
            "time_zero - op_start >= %s",
            [rule.prior_observation_days],
        ),
        (f"age {rule.min_age} or older at time zero", "age >= %s", [rule.min_age]),
        ("diagnosed on or before time zero", "diagnosis_date <= time_zero", []),
        (
            f"time zero within {rule.max_days_from_diagnosis} days of diagnosis",
            "time_zero - diagnosis_date <= %s",
            [rule.max_days_from_diagnosis],
        ),
        ("no outcome on or before time zero", "NOT prior_outcome", []),
    ]
    count = "SELECT count(*) FROM tte_candidates WHERE {}"
    attrition = [("first use of either strategy", con.execute(count.format("TRUE")).fetchone()[0])]
    where, where_params = "TRUE", []
    for label, condition, values in rules:
        where += f" AND {condition}"
        where_params += values
        attrition.append((label, con.execute(count.format(where), where_params).fetchone()[0]))

    # Follow-up ends at the first of outcome, death, end of observation, or max_days. On a tie the
    # outcome counts: an outcome on the day of death is still an event.
    cursor = con.execute(
        f"""
        WITH eligible AS (
            SELECT *, least(death_date, op_end, time_zero + %s) AS censor_date
            FROM tte_candidates WHERE {where}
        )
        SELECT person_id, arm, time_zero, age, gender_concept_id,
               (outcome_date IS NOT NULL AND outcome_date <= censor_date)::integer AS event,
               least(outcome_date, censor_date) - time_zero AS days,
               CASE WHEN outcome_date <= censor_date THEN 'outcome'
                    WHEN censor_date = death_date THEN 'death'
                    WHEN censor_date = op_end THEN 'end_of_observation'
                    ELSE 'administrative' END AS end_reason
        FROM eligible ORDER BY person_id
        """,
        [protocol.follow_up.max_days, *where_params],
    )
    columns = [c.name for c in cursor.description]
    return attrition, pd.DataFrame(cursor.fetchall(), columns=columns)
