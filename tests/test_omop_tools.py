import pytest
from psycopg.types.json import Jsonb

from ehr_rwe_eln.agents.omop_tools import (
    SUPPRESSED,
    ToolInputError,
    concept_count,
    concept_search,
    dq_results,
    tte_results,
)
from ehr_rwe_eln.cohort.cdm import create_cdm
from ehr_rwe_eln.omop_stats import build, save

# Invented concept ids. PARENT has two children; RARE is on its own.
PARENT, CHILD_A, CHILD_B, RARE = 930001, 930002, 930003, 930010


@pytest.fixture
def stats(pg, dq_schema):
    create_cdm(pg)
    for concept_id, name in [
        (PARENT, "Test hypertensive disorder"),
        (CHILD_A, "Test essential hypertension"),
        (CHILD_B, "Test secondary hypertension"),
        (RARE, "Test rare condition"),
    ]:
        pg.execute(
            "INSERT INTO cdm.concept VALUES (%s, %s, 'Condition', 'SNOMED', 'Clinical Finding',"
            " 'S', %s, DATE '2000-01-01', DATE '2099-12-31', NULL)",
            [concept_id, name, str(concept_id)],
        )
    for ancestor, descendant in [
        (PARENT, PARENT),
        (PARENT, CHILD_A),
        (PARENT, CHILD_B),
        (CHILD_A, CHILD_A),
        (CHILD_B, CHILD_B),
        (RARE, RARE),
    ]:
        pg.execute("INSERT INTO cdm.concept_ancestor VALUES (%s, %s, 0, 0)", [ancestor, descendant])
    pg.execute(
        "INSERT INTO cdm.cdm_source (cdm_source_name, cdm_source_abbreviation, cdm_holder,"
        " source_release_date, cdm_release_date, cdm_version_concept_id, vocabulary_version)"
        " VALUES ('test', 't', 't', DATE '2026-01-01', DATE '2026-01-01', 0, 'v')"
    )
    # 12 people with CHILD_A; people 1 and 2 also have CHILD_B, so they reach PARENT twice but
    # count once. 3 people with RARE: under the cell size.
    facts = [(p, CHILD_A) for p in range(1, 13)] + [(1, CHILD_B), (2, CHILD_B)]
    facts += [(p, RARE) for p in range(20, 23)]
    for person in {p for p, _ in facts}:
        pg.execute(
            "INSERT INTO cdm.person (person_id, gender_concept_id, year_of_birth, race_concept_id,"
            " ethnicity_concept_id) VALUES (%s, 8507, 1960, 0, 0)",
            [person],
        )
    for i, (person, concept) in enumerate(facts):
        pg.execute(
            "INSERT INTO cdm.condition_occurrence (condition_occurrence_id, person_id,"
            " condition_concept_id, condition_start_date, condition_type_concept_id)"
            " VALUES (%s, %s, %s, DATE '2020-01-01', 32817)",
            [i, person, concept],
        )
    record, rows = build(pg)
    save(pg, record, rows)
    return pg


def test_counts_roll_up_through_descendants_and_suppress_small_ones(stats):
    parent = concept_count(stats, PARENT)
    assert (parent.persons, parent.persons_display) == (12, "12")  # people 1 and 2 count once
    assert concept_count(stats, CHILD_B).persons is None  # 2 people
    rare = concept_count(stats, RARE)
    assert (rare.persons, rare.persons_display) == (None, SUPPRESSED)
    assert concept_count(stats, 999999) is None
    # Suppressed counts are never stored, records included.
    assert (
        stats.execute(
            "SELECT count(*) FROM omop_stats.concept_count"
            " WHERE persons IS NULL AND records IS NOT NULL"
        ).fetchone()[0]
        == 0
    )
    assert stats.execute("SELECT persons, min_cell FROM omop_stats.build").fetchone() == (15, 11)


def test_concept_search_orders_by_persons_and_validates_input(stats):
    found = concept_search(stats, "hypertens")
    assert [c.concept_id for c in found][:2] == [CHILD_A, PARENT]  # 12 each, then by name
    assert [c.concept_id for c in concept_search(stats, str(RARE))] == [RARE]
    assert concept_search(stats, "hypertens", limit=1000)  # capped, not an error
    for bad in [{"text": "h"}, {"text": "x" * 101}, {"text": "rare", "domain": "Person"}]:
        with pytest.raises(ToolInputError):
            concept_search(stats, **bad)


def test_tte_results_summarize_the_newest_run(pg, dq_schema):
    report = {
        "protocol": {"description": "d", "treatment": "a", "comparator": "b", "outcome": "o"},
        "arms": [
            {"name": "a", "persons": 100, "events": 9},
            {"name": "b", "persons": 80, "events": 4},
        ],
        "not_estimable": None,
        "balance": [
            {"smd_before": 0.3, "smd_after": -0.08},
            {"smd_before": 0.1, "smd_after": 0.02},
        ],
        "survival": {
            "hazard_ratio": 1.1,
            "hazard_ratio_robust_ci": [0.5, 2.4],
            "crude_hazard_ratio": 1.3,
        },
        "negative_controls": [{"excludes_null": True}, {"excludes_null": False}],
    }
    for _ in range(2):  # an older run and the newest
        pg.execute(
            "INSERT INTO tte.run (started_at, finished_at, persons) VALUES (now(), now(), 180)"
        )
    newest = pg.execute("SELECT max(run_id) FROM tte.run").fetchone()[0]
    pg.execute("INSERT INTO tte.report VALUES (%s, 3, 'p', %s)", [newest, Jsonb(report)])

    [result] = tte_results(pg, "p")
    assert result.run_id == newest
    assert (result.hazard_ratio, result.hazard_ratio_95ci) == (1.1, (0.5, 2.4))
    assert result.largest_smd_after_weighting == 0.08
    assert (result.negative_controls, result.negative_controls_excluding_1) == (2, 1)
    with pytest.raises(ToolInputError):
        tte_results(pg, "not_a_protocol")


def test_dq_results_count_failures_and_filter(pg, dq_schema):
    run_id = pg.execute(
        "INSERT INTO dq.run (started_at, finished_at, overview) VALUES (now(), now(), '{}')"
        " RETURNING run_id"
    ).fetchone()[0]
    checks = [
        ("c1", "measurement", "Plausibility", True, 12.5),
        ("c2", "measurement", "Conformance", False, 0.0),
        ("c3", "person", "Plausibility", True, 1.0),
    ]
    for check_id, table, category, failed, pct in checks:
        pg.execute(
            "INSERT INTO dq.result (run_id, check_id, check_name, check_level, check_description,"
            " cdm_table_name, category, context, severity, pct_violated_rows, failed, passed,"
            " is_error, not_applicable, execution_seconds, query_text) VALUES (%s, %s, %s,"
            " 'FIELD', 'd', %s, %s, 'Verification', 'fatal', %s, %s, %s, false, false, 1, 'q')",
            [run_id, check_id, check_id, table, category, pct, failed, not failed],
        )
    every = dq_results(pg)
    assert (every.checks, every.failed) == (3, 2)
    assert [c.check for c in every.failed_checks] == ["c1", "c3"]  # worst first
    plausibility = dq_results(pg, table="MEASUREMENT", category="Plausibility")
    assert (plausibility.checks, plausibility.failed) == (1, 1)
    with pytest.raises(ToolInputError):
        dq_results(pg, table="person; drop table x")
