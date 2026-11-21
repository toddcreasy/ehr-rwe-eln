"""A protocol's cohorts in an OHDSI cohort table, the input CohortMethod and other HADES packages
read (r/run_cohortmethod.R).

A cohort table has four columns: which cohort, which person, and the dates they enter and leave.
Each protocol writes:

- its two arms, from the analysis table build_analysis_table() makes, so eligibility and time
  zero are exactly the Python analysis's: enter at time zero, leave at the end of follow-up
  (death, end of observation, or the protocol's maximum), not at the outcome;
- its outcome and each negative control: every person in either arm with a record of it,
  entering on the first record. CohortMethod itself drops people whose first record is on or
  before time zero, outcome by outcome.

Cohort IDs are the protocol's ID times 100, plus 1 for the treatment arm, 2 for the comparator,
3 for the outcome, and 10 onward for the negative controls in protocol order.
"""

from ehr_rwe_eln.tte.cohort import build_analysis_table, concept_set_sql
from ehr_rwe_eln.tte.protocol import Protocol


def cohort_ids(protocol: Protocol) -> dict:
    base = protocol.id * 100
    return {
        "protocol": protocol.name,
        "treatment": {"id": base + 1, "name": protocol.strategies.treatment.name},
        "comparator": {"id": base + 2, "name": protocol.strategies.comparator.name},
        "outcome": {"id": base + 3, "name": protocol.outcome.name},
        "negative_controls": [
            {"id": base + 10 + i, "name": nc.name}
            for i, nc in enumerate(protocol.negative_controls)
        ],
        # The strategies' own drugs (with descendants) can't be covariates: they decide the arm.
        "excluded_covariate_concept_ids": [
            *protocol.strategies.treatment.drugs.concept_ids,
            *protocol.strategies.comparator.drugs.concept_ids,
        ],
    }


def write_cohorts(con, protocol: Protocol, cdm: str = "cdm", schema: str = "results") -> dict:
    """Replace the protocol's cohorts in {schema}.cohort; returns cohort_ids(protocol) with each
    cohort's person count. con is a psycopg connection (the caller commits) or a RedshiftSession.
    """
    ids = cohort_ids(protocol)
    _, table = build_analysis_table(con, protocol, cdm)
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {schema}.cohort (cohort_definition_id INTEGER,"
        " subject_id BIGINT, cohort_start_date DATE, cohort_end_date DATE)"
    )
    base = protocol.id * 100
    con.execute(
        f"DELETE FROM {schema}.cohort"
        f" WHERE cohort_definition_id BETWEEN {int(base)} AND {int(base) + 99}"
    )

    arm_id = {1: ids["treatment"]["id"], 0: ids["comparator"]["id"]}
    rows = [
        f"({arm_id[int(r.arm)]}, {int(r.person_id)}, DATE '{r.time_zero}', DATE '{r.censor_date}')"
        for r in table.itertuples()
    ]
    for i in range(0, len(rows), 1000):
        con.execute(f"INSERT INTO {schema}.cohort VALUES {', '.join(rows[i : i + 1000])}")

    arms = f"{ids['treatment']['id']}, {ids['comparator']['id']}"
    outcomes = [(ids["outcome"]["id"], protocol.outcome.conditions)] + [
        (entry["id"], nc.conditions)
        for entry, nc in zip(ids["negative_controls"], protocol.negative_controls, strict=True)
    ]
    for cohort_id, concepts in outcomes:
        con.execute(
            f"""
            INSERT INTO {schema}.cohort
            SELECT {int(cohort_id)}, co.person_id,
                   min(co.condition_start_date), min(co.condition_start_date)
            FROM {cdm}.condition_occurrence co
            JOIN ({concept_set_sql(concepts, cdm)}) cs ON cs.concept_id = co.condition_concept_id
            WHERE co.person_id IN (
                SELECT subject_id FROM {schema}.cohort WHERE cohort_definition_id IN ({arms})
            )
            GROUP BY co.person_id
            """
        )

    counts = dict(
        con.execute(
            f"SELECT cohort_definition_id, count(*) FROM {schema}.cohort"
            f" WHERE cohort_definition_id BETWEEN {int(base)} AND {int(base) + 99}"
            " GROUP BY cohort_definition_id"
        ).fetchall()
    )
    for entry in [ids["treatment"], ids["comparator"], ids["outcome"], *ids["negative_controls"]]:
        entry["persons"] = int(counts.get(entry["id"], 0))
    return ids
