"""Condition and drug eras: spans of continuous exposure, built from the event tables.

Same eras as the OHDSI era scripts ETL-Synthea runs (the correctness reference): records for one
person and concept merge when the next starts at most 30 days after the latest end so far. Drugs
roll up to their RxNorm ingredient first, and overlapping exposures merge before the 30-day window
applies, so gap_days counts only days no exposure covers.

Two deliberate differences:
- Conditions with concept_id 0 get no era. ETL-Synthea's script has that filter commented out,
  which would merge every unmapped condition a person has into one era.
- A drug exposure that ends before it starts (Synthea writes 104 of them) adds no coverage here.
  The OHDSI script subtracts its length, inflating gap_days. Every other era column matches.
"""

import psycopg

PERSISTENCE_DAYS = 30


def _islands(source: str, gap: int) -> str:
    """Number each row's island within its person and concept: a row joins the island before it
    when it starts at most `gap` days after the latest end so far."""
    return f"""
        SELECT *, sum(new_island) OVER (
            PARTITION BY person_id, concept_id ORDER BY start_date, end_date
            ROWS UNBOUNDED PRECEDING) AS island
        FROM (
            SELECT *, CASE WHEN start_date <= max(end_date) OVER (
                PARTITION BY person_id, concept_id ORDER BY start_date, end_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) + {gap}
                THEN 0 ELSE 1 END AS new_island
            FROM {source}
        ) flagged
    """


CONDITION_ERA_SQL = f"""
WITH target AS (
    SELECT person_id, condition_concept_id AS concept_id, condition_start_date AS start_date,
        COALESCE(condition_end_date, condition_start_date + 1) AS end_date
    FROM cdm.condition_occurrence
    WHERE condition_concept_id <> 0
),
eras AS ({_islands("target", PERSISTENCE_DAYS)})
INSERT INTO cdm.condition_era (condition_era_id, person_id, condition_concept_id,
    condition_era_start_date, condition_era_end_date, condition_occurrence_count)
SELECT row_number() OVER (ORDER BY person_id, concept_id, min(start_date)), person_id, concept_id,
    min(start_date), max(end_date), count(*)
FROM eras
GROUP BY person_id, concept_id, island
"""

DRUG_ERA_SQL = f"""
WITH target AS (
    SELECT d.person_id, c.concept_id, d.drug_exposure_start_date AS start_date,
        COALESCE(
            d.drug_exposure_end_date,
            NULLIF(d.drug_exposure_start_date + d.days_supply, d.drug_exposure_start_date),
            d.drug_exposure_start_date + 1
        ) AS end_date
    FROM cdm.drug_exposure d
    JOIN cdm.concept_ancestor ca ON ca.descendant_concept_id = d.drug_concept_id
    JOIN cdm.concept c ON c.concept_id = ca.ancestor_concept_id
    WHERE c.vocabulary_id = 'RxNorm' AND c.concept_class_id = 'Ingredient'
        AND d.drug_concept_id <> 0
        AND COALESCE(d.days_supply, 0) >= 0
),
sub_islands AS ({_islands("target", 0)}),
sub_exposures AS (
    SELECT person_id, concept_id, min(start_date) AS start_date, max(end_date) AS end_date,
        count(*) AS exposure_count, max(end_date) - min(start_date) AS days_exposed
    FROM sub_islands
    GROUP BY person_id, concept_id, island
),
eras AS ({_islands("sub_exposures", PERSISTENCE_DAYS)})
INSERT INTO cdm.drug_era (drug_era_id, person_id, drug_concept_id, drug_era_start_date,
    drug_era_end_date, drug_exposure_count, gap_days)
SELECT row_number() OVER (ORDER BY person_id, concept_id, min(start_date)), person_id, concept_id,
    min(start_date), max(end_date), sum(exposure_count),
    max(end_date) - min(start_date) - sum(days_exposed)
FROM eras
GROUP BY person_id, concept_id, island
"""


def build_eras(con: psycopg.Connection) -> dict:
    """Fill condition_era and drug_era from the event tables. Returns row counts."""
    con.execute(CONDITION_ERA_SQL)
    con.execute(DRUG_ERA_SQL)
    return {
        t: con.execute(f"SELECT count(*) FROM cdm.{t}").fetchone()[0]
        for t in ("condition_era", "drug_era")
    }
