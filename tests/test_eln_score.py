from datetime import date

import pytest

from ehr_rwe_eln.eln.models import Extraction, Result, Sample
from ehr_rwe_eln.eln.score import Score, add

S1 = Sample(
    sample_id="S-1", subject_id="HTN-1", specimen_type="serum", collection_date=date(2020, 1, 2)
)
S2 = Sample(sample_id="S-2", subject_id="HTN-2", specimen_type="serum")
R1 = Result(sample_id="S-1", analyte="crp", value=2.2, unit="mg/L")
R2 = Result(sample_id="S-2", analyte="crp", value=13.6, unit="mg/L")
TRUTH = Extraction(samples=[S1, S2], results=[R1, R2])


def test_a_perfect_extraction_scores_1():
    score = Score()
    add(score, "e", TRUTH, TRUTH)
    assert (score.samples.f1, score.results.f1, score.errors) == (1.0, 1.0, [])


def test_a_wrong_field_is_both_a_miss_and_an_extra():
    got = Extraction(
        samples=[S1.model_copy(update={"collection_date": None}), S2],
        results=[R1, R2.model_copy(update={"unit": "mg/dL"})],
    )
    score = Score()
    add(score, "e", got, TRUTH)
    assert (score.samples.precision, score.samples.recall) == (0.5, 0.5)
    assert (score.results.precision, score.results.recall) == (0.5, 0.5)
    assert len(score.errors) == 4


def test_a_qc_value_taken_as_a_result_lowers_precision_only():
    qc = Result(sample_id="S-1", analyte="il6", value=5.0, unit="pg/mL")
    score = Score()
    add(score, "e", TRUTH.model_copy(update={"results": [R1, R2, qc]}), TRUTH)
    assert score.results.precision == pytest.approx(2 / 3)
    assert score.results.recall == 1.0


def test_counts_add_up_across_entries_before_dividing():
    score = Score()
    add(score, "a", TRUTH, TRUTH)
    add(score, "b", Extraction(samples=[], results=[]), TRUTH)
    assert score.results.recall == 0.5
    assert score.results.precision == 1.0
