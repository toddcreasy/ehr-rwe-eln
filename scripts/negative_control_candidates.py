"""Candidate negative control outcomes for a trial emulation protocol.

Usage: uv run python scripts/negative_control_candidates.py PROTOCOL [--min-events 10]

Lists every condition that starts after time zero and within follow-up (new onset: no record of
it on or before time zero) in each arm of the protocol's analysis table, with counts per arm.
Choosing negative controls from the list is a judgment: a control must be an outcome neither
strategy plausibly causes or prevents. The choice and its reasons go in the protocol's
negative_controls. Reads OMOP through connect_omop(); OMOP_SOURCE=staging costs nothing.
"""

import argparse
from pathlib import Path

from ehr_rwe_eln.omop import connect_omop
from ehr_rwe_eln.tte.cohort import build_analysis_table
from ehr_rwe_eln.tte.protocol import load_protocol

PROTOCOLS = Path(__file__).resolve().parents[1] / "src/ehr_rwe_eln/tte/protocols"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("protocol", help="protocol name, e.g. lisinopril_vs_amlodipine_ckd")
    parser.add_argument("--min-events", type=int, default=10, help="across both arms")
    args = parser.parse_args()
    protocol = load_protocol(PROTOCOLS / f"{args.protocol}.yaml")

    omop, cdm = connect_omop()
    with omop as con:
        _, table = build_analysis_table(con, protocol, cdm)
        con.execute("DROP TABLE IF EXISTS nc_cohort")
        con.execute("CREATE TEMP TABLE nc_cohort (person_id BIGINT, arm INTEGER, time_zero DATE)")
        # The SQL below is built as in tte/cohort.py: every value is forced through int() or is a
        # date the database returned, and cdm is a fixed prefix.
        rows = [
            f"({int(r.person_id)}, {int(r.arm)}, DATE '{r.time_zero}')" for r in table.itertuples()
        ]
        for i in range(0, len(rows), 1000):
            con.execute(f"INSERT INTO nc_cohort VALUES {', '.join(rows[i : i + 1000])}")  # noqa: S608
        candidates = con.execute(
            f"""
            SELECT * FROM (
                WITH followed AS (
                    SELECT n.person_id, n.arm, n.time_zero,
                           least(d.death_date, op.observation_period_end_date,
                                 n.time_zero + {int(protocol.follow_up.max_days)}) AS censor_date
                    FROM nc_cohort n
                    JOIN {cdm}.observation_period op
                      ON op.person_id = n.person_id
                     AND n.time_zero BETWEEN op.observation_period_start_date
                                         AND op.observation_period_end_date
                    LEFT JOIN {cdm}.death d ON d.person_id = n.person_id
                ),
                first_record AS (
                    SELECT person_id, condition_concept_id, min(condition_start_date) AS first_date
                    FROM {cdm}.condition_occurrence
                    WHERE condition_concept_id <> 0
                    GROUP BY person_id, condition_concept_id
                )
                SELECT f.condition_concept_id, c.concept_name,
                       sum(CASE WHEN p.arm = 1 THEN 1 ELSE 0 END) AS treatment,
                       sum(CASE WHEN p.arm = 0 THEN 1 ELSE 0 END) AS comparator
                FROM followed p
                JOIN first_record f
                  ON f.person_id = p.person_id
                 AND f.first_date > p.time_zero AND f.first_date <= p.censor_date
                JOIN {cdm}.concept c ON c.concept_id = f.condition_concept_id
                GROUP BY f.condition_concept_id, c.concept_name
            ) counts
            WHERE treatment >= 1 AND comparator >= 1
              AND treatment + comparator >= {int(args.min_events)}
            ORDER BY treatment + comparator DESC
            """  # noqa: S608
        ).fetchall()

    strategies = protocol.strategies
    print(
        f"{protocol.name}: {int((table.arm == 1).sum()):,} {strategies.treatment.name},"
        f" {int((table.arm == 0).sum()):,} {strategies.comparator.name}; {len(candidates)}"
        f" new-onset conditions with cases in both arms and {args.min_events}+ in all"
    )
    treatment, comparator = strategies.treatment.name, strategies.comparator.name
    print(f"{'concept':>10}  {treatment:>10}  {comparator:>10}  name")
    for concept_id, name, in_treatment, in_comparator in candidates:
        print(f"{concept_id:>10}  {in_treatment:>10}  {in_comparator:>10}  {name}")


if __name__ == "__main__":
    main()
