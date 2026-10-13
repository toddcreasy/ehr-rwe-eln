import datetime
from dataclasses import replace

import pytest

from ehr_rwe_eln.cohort.cdm import create_cdm
from ehr_rwe_eln.dq.checks import load_checks, matches
from ehr_rwe_eln.dq.run import run_checks, save_run
from ehr_rwe_eln.dq.scoring import Result, evaluate, summarize
from ehr_rwe_eln.dq.sql import check_sql

CHECKS = {c.check_id: c for c in load_checks()}


def test_check_list_matches_dqd():
    # DQD v2.9.0's own sqlOnly run expands to the same 1,912 TABLE and FIELD checks.
    assert len(CHECKS) == 1912
    assert sum(c.level == "TABLE" for c in CHECKS.values()) == 50
    check = CHECKS["field_plausiblestartbeforeend_drug_exposure_drug_exposure_start_date"]
    assert check.threshold == 1
    assert check.params["plausibleStartBeforeEndFieldName"] == "DRUG_EXPOSURE_END_DATE"
    assert all(check_sql(c) for c in CHECKS.values())


def test_filters_treat_empty_cells_as_na():
    assert matches({"a": "Yes", "b": "x"}, "a=='Yes' & b!= ''")
    assert not matches({"a": "Yes"}, "a=='Yes' & b!= ''")
    assert not matches({"a": "No"}, "a=='Yes'")
    with pytest.raises(ValueError):
        matches({"a": "Yes"}, "a %in% c('Yes')")


def result(check_id, violated=0, denominator=10, error=None, **changes):
    check = replace(CHECKS[check_id], **changes)
    return Result(check, violated, denominator, error, 0.0, "")


def test_thresholds_fail_only_above_the_percent():
    field = "field_measurevaluecompleteness_measurement_value_as_number"
    results = [
        result(field, violated=1, threshold=0.0),
        result(field, violated=5, threshold=50.0),
        result(field, violated=6, threshold=50.0),
        result(field, violated=0, threshold=None),
    ]
    evaluate(results)
    assert [r.failed for r in results] == [True, False, True, False]


def test_missing_field_fails_cdm_field_and_makes_its_checks_not_applicable():
    results = [
        result("field_cdmfield_note_note_text", error='column "note_text" does not exist'),
        result("field_measurevaluecompleteness_note_note_text", error="column does not exist"),
        result("field_measurevaluecompleteness_note_note_date", violated=1),
        result("field_isrequired_person_year_of_birth", error="division by zero"),
    ]
    evaluate(results)
    cdm_field, missing, other, broken = results
    assert (cdm_field.failed, cdm_field.is_error, cdm_field.not_applicable) == (True, False, False)
    assert missing.not_applicable and not missing.passed
    assert missing.not_applicable_reason == "Field NOTE.NOTE_TEXT does not exist."
    assert other.failed
    assert (broken.is_error, broken.failed, broken.not_applicable) == (True, False, False)


def test_empty_table_checks_are_not_applicable_except_presence_and_completeness():
    table = "SPECIMEN"
    results = [
        result("table_cdmtable_specimen", denominator=1),
        # Shipped at 100% for SPECIMEN, which nothing can exceed; 0 makes any gap fail.
        result("table_measurepersoncompleteness_specimen", violated=10, threshold=0.0),
        result("field_measurevaluecompleteness_specimen_specimen_date", denominator=0),
        result("field_isrequired_specimen_specimen_date", denominator=0),
    ]
    evaluate(results)
    present, persons, completeness, required = results
    assert present.passed and not present.not_applicable
    assert persons.failed and not persons.not_applicable
    assert completeness.not_applicable and required.not_applicable
    assert required.not_applicable_reason == f"Table {table} is empty."


def test_summary_keeps_dqds_pass_count_and_adds_a_strict_rate():
    results = [
        result("table_cdmtable_person", denominator=1),
        result("field_measurevaluecompleteness_specimen_specimen_date", denominator=0),
        result("field_isrequired_specimen_specimen_date", denominator=0),
        result("field_isrequired_person_year_of_birth", violated=1),
    ]
    evaluate(results)
    overview = summarize(results)
    # Two not applicable checks count as passed in DQD's numbers.
    assert overview["countPassed"] == 3
    assert overview["percentPassed"] == 75.0
    assert overview["countNotApplicable"] == 2
    assert overview["strictPercentPassed"] == 50.0


def test_run_on_a_small_cdm(pg, dq_schema):
    create_cdm(pg)
    pg.execute(
        "INSERT INTO cdm.person (person_id, gender_concept_id, year_of_birth, race_concept_id,"
        " ethnicity_concept_id) VALUES (1, 0, 1980, 0, 0)"
    )
    pg.execute(
        "INSERT INTO cdm.drug_exposure (drug_exposure_id, person_id, drug_concept_id,"
        " drug_exposure_start_date, drug_exposure_end_date, drug_type_concept_id)"
        " VALUES (1, 1, 0, %s, %s, 32817)",
        [datetime.date(2020, 3, 1), datetime.date(2020, 2, 1)],
    )
    pg.execute("ALTER TABLE cdm.note DROP COLUMN note_text")

    results = {r.check.check_id: r for r in run_checks(pg)}

    reversed_dates = results["field_plausiblestartbeforeend_drug_exposure_drug_exposure_start_date"]
    assert (reversed_dates.num_violated_rows, reversed_dates.num_denominator_rows) == (1, 1)
    assert reversed_dates.failed
    dropped = results["field_cdmfield_note_note_text"]
    assert dropped.failed and not dropped.is_error
    assert results["field_isrequired_specimen_specimen_date"].not_applicable
    # The other checks on the dropped column error, and DQD scores them not applicable.
    errored = {r.check.check_id for r in results.values() if r.is_error}
    assert errored == {
        "field_isrequired_note_note_text",
        "field_measurevaluecompleteness_note_note_text",
    }
    assert all(results[i].not_applicable for i in errored)

    run_id = save_run(pg, list(results.values()), datetime.datetime.now(datetime.UTC))
    stored = pg.execute(
        "SELECT count(*), count(*) FILTER (WHERE failed) FROM dq.result WHERE run_id = %s",
        [run_id],
    ).fetchone()
    assert stored == (1912, sum(r.failed for r in results.values()))
