"""Build a protocol's analysis table: one row per eligible person, with arm and follow-up.

Time zero is each person's first day on either strategy; their arm is whichever they started.
Eligibility is checked on that same day, so eligibility, assignment, and the start of follow-up
line up and no person-time is counted before treatment starts (immortal time). Rules apply in
order and are counted as they go, the attrition table a trial report starts with.
"""

import pandas as pd

from ehr_rwe_eln.tte.protocol import ConceptSet, Protocol

# The SQL here runs unchanged on Postgres (staging, tests) and Redshift (the lake): no arrays,
# DISTINCT ON, FILTER, make_date, or correlated EXISTS, and no bind parameters. Every value
# written into it is forced through int() first.


def ids(values: list[int]) -> str:
    return ", ".join(str(int(v)) for v in values)


def concept_set_sql(concept_set: ConceptSet, cdm: str = "cdm") -> str:
    """A one-column (concept_id) query for the set's concepts, with their descendants if asked."""
    sql = " UNION ".join(f"SELECT {int(c)} AS concept_id" for c in concept_set.concept_ids)
    if concept_set.include_descendants:
        sql += (
            f" UNION SELECT descendant_concept_id FROM {cdm}.concept_ancestor"
            f" WHERE ancestor_concept_id IN ({ids(concept_set.concept_ids)})"
        )
    return sql


def age_sql(on: str, person: str = "p") -> str:
    """Whole years from birth (month and day default to 1, as OMOP leaves them optional) to the
    date `on`: the year difference, less one if the birthday has not come yet that year."""
    return (
        f"CAST(EXTRACT(YEAR FROM {on}) AS INTEGER) - {person}.year_of_birth"
        f" - CASE WHEN CAST(EXTRACT(MONTH FROM {on}) AS INTEGER) * 100"
        f" + CAST(EXTRACT(DAY FROM {on}) AS INTEGER)"
        f" < coalesce({person}.month_of_birth, 1) * 100 + coalesce({person}.day_of_birth, 1)"
        " THEN 1 ELSE 0 END"
    )


def build_analysis_table(
    con, protocol: Protocol, cdm: str = "cdm"
) -> tuple[list[tuple[str, int]], pd.DataFrame]:
    """Returns the attrition table, (rule, persons remaining) pairs, and the analysis table.
    con is a psycopg connection or a lake.RedshiftSession; cdm is the OMOP tables' prefix."""
    treatment = concept_set_sql(protocol.strategies.treatment.drugs, cdm)
    comparator = concept_set_sql(protocol.strategies.comparator.drugs, cdm)
    diagnosis = concept_set_sql(protocol.eligibility.diagnosis, cdm)
    outcome = concept_set_sql(protocol.outcome.conditions, cdm)

    con.execute("DROP TABLE IF EXISTS tte_candidates")
    con.execute(
        f"""
        CREATE TEMP TABLE tte_candidates AS
        WITH treatment AS ({treatment}), comparator AS ({comparator}),
        diagnosis AS ({diagnosis}), outcome AS ({outcome}),
        first_use AS (
            SELECT de.person_id,
                   min(CASE WHEN t.concept_id IS NOT NULL
                            THEN de.drug_exposure_start_date END) AS treatment_start,
                   min(CASE WHEN c.concept_id IS NOT NULL
                            THEN de.drug_exposure_start_date END) AS comparator_start
            FROM {cdm}.drug_exposure de
            LEFT JOIN treatment t ON t.concept_id = de.drug_concept_id
            LEFT JOIN comparator c ON c.concept_id = de.drug_concept_id
            WHERE t.concept_id IS NOT NULL OR c.concept_id IS NOT NULL
            GROUP BY de.person_id
        ),
        starts AS (
            SELECT person_id,
                   least(treatment_start, comparator_start) AS time_zero,
                   -- 1 treatment, 0 comparator; NULL when both start the same day
                   CASE WHEN comparator_start IS NULL OR treatment_start < comparator_start THEN 1
                        WHEN treatment_start IS NULL OR comparator_start < treatment_start THEN 0
                   END AS arm
            FROM first_use
        ),
        diagnosed AS (
            SELECT co.person_id, min(co.condition_start_date) AS diagnosis_date
            FROM {cdm}.condition_occurrence co
            JOIN diagnosis dx ON dx.concept_id = co.condition_concept_id
            GROUP BY co.person_id
        ),
        outcomes AS (
            SELECT s.person_id,
                   max(CASE WHEN co.condition_start_date <= s.time_zero THEN 1 ELSE 0 END)
                       AS prior_outcome,
                   min(CASE WHEN co.condition_start_date > s.time_zero
                            THEN co.condition_start_date END) AS outcome_date
            FROM starts s
            JOIN {cdm}.condition_occurrence co ON co.person_id = s.person_id
            JOIN outcome o ON o.concept_id = co.condition_concept_id
            GROUP BY s.person_id
        )
        SELECT s.person_id, s.time_zero, s.arm, p.gender_concept_id,
               {age_sql("s.time_zero")} AS age,
               op.observation_period_start_date AS op_start,
               op.observation_period_end_date AS op_end,
               dg.diagnosis_date,
               coalesce(oc.prior_outcome, 0) AS prior_outcome,
               oc.outcome_date,
               d.death_date
        FROM starts s
        JOIN {cdm}.person p ON p.person_id = s.person_id
        LEFT JOIN {cdm}.observation_period op
          ON op.person_id = s.person_id
         AND s.time_zero BETWEEN op.observation_period_start_date
                             AND op.observation_period_end_date
        LEFT JOIN diagnosed dg ON dg.person_id = s.person_id
        LEFT JOIN outcomes oc ON oc.person_id = s.person_id
        LEFT JOIN {cdm}.death d ON d.person_id = s.person_id
        """
    )

    rule = protocol.eligibility
    rules = [
        ("started one strategy before the other", "arm IS NOT NULL"),
        ("time zero inside an observation period", "op_start IS NOT NULL"),
        (
            f"at least {rule.prior_observation_days} days of prior observation",
            f"time_zero - op_start >= {int(rule.prior_observation_days)}",
        ),
        (f"age {rule.min_age} or older at time zero", f"age >= {int(rule.min_age)}"),
        ("diagnosed on or before time zero", "diagnosis_date <= time_zero"),
        (
            f"time zero within {rule.max_days_from_diagnosis} days of diagnosis",
            f"time_zero - diagnosis_date <= {int(rule.max_days_from_diagnosis)}",
        ),
        ("no outcome on or before time zero", "prior_outcome = 0"),
    ]
    count = "SELECT count(*) FROM tte_candidates WHERE {}"
    attrition = [("first use of either strategy", con.execute(count.format("TRUE")).fetchone()[0])]
    where = "TRUE"
    for label, condition in rules:
        where += f" AND {condition}"
        attrition.append((label, con.execute(count.format(where)).fetchone()[0]))

    # Follow-up ends at the first of outcome, death, end of observation, or max_days. On a tie the
    # outcome counts: an outcome on the day of death is still an event.
    cursor = con.execute(
        f"""
        WITH eligible AS (
            SELECT *,
                   least(death_date, op_end, time_zero + {int(protocol.follow_up.max_days)})
                       AS censor_date
            FROM tte_candidates WHERE {where}
        )
        SELECT person_id, arm, time_zero, age, gender_concept_id,
               CASE WHEN outcome_date IS NOT NULL AND outcome_date <= censor_date
                    THEN 1 ELSE 0 END AS event,
               least(outcome_date, censor_date) - time_zero AS days,
               CASE WHEN outcome_date <= censor_date THEN 'outcome'
                    WHEN censor_date = death_date THEN 'death'
                    WHEN censor_date = op_end THEN 'end_of_observation'
                    ELSE 'administrative' END AS end_reason,
               censor_date
        FROM eligible ORDER BY person_id
        """
    )
    columns = [c.name for c in cursor.description]
    return attrition, pd.DataFrame(cursor.fetchall(), columns=columns)
