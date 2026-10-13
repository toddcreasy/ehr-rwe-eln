"""Eval for module 2's ELN extraction. Calls the real Anthropic API: slow, costs a few cents.

    uv run pytest evals/test_eln_extraction.py

Entries come from the synthetic generator with a seed the unit tests never use, so the model
sees entries nobody tuned the prompt against, and the generator supplies the right answers.
"""

from datetime import date

import pytest

from ehr_rwe_eln.eln.extract import extract
from ehr_rwe_eln.eln.score import Score, add
from ehr_rwe_eln.eln.synthetic import generate_entries, subject_registry

pytestmark = pytest.mark.evals

ENTRIES = 40
SEED = 2026
# The bar for writing extractions to OMOP without review.
MIN_PRECISION = MIN_RECALL = 0.95


def test_extraction_precision_and_recall():
    windows = {
        code: (date(2015, 1, 1), date(2024, 12, 31)) for code in subject_registry(list(range(60)))
    }
    score = Score()
    for entry in generate_entries(windows, ENTRIES, seed=SEED):
        add(score, entry.entry_id, extract(entry.body), entry.truth)

    for name, counts in (("samples", score.samples), ("results", score.results)):
        print(
            f"{name}: precision {counts.precision:.3f}, recall {counts.recall:.3f},"
            f" f1 {counts.f1:.3f} ({counts.true_positive} of {counts.expected} expected,"
            f" {counts.extracted} extracted)"
        )
    for entry_id, error in score.errors:
        print(f"  {entry_id}: {error}")
    for counts in (score.samples, score.results):
        assert counts.precision >= MIN_PRECISION
        assert counts.recall >= MIN_RECALL
