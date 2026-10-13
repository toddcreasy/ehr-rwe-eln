"""Eval for module 2's ELN extraction. Calls the real Anthropic API: slow, costs a few cents.

    uv run pytest evals/test_eln_extraction.py -s

Entries come from the synthetic generator with seeds the unit tests never use, so the model
sees entries nobody tuned the prompt against, and the generator supplies the right answers.
Two sets: the default entries, and hard ones whose traps need reading the whole entry. Each set
prints its score per trap, so a miss points at the trap behind it.
"""

from collections import defaultdict
from datetime import date

import pytest

from ehr_rwe_eln.eln.extract import extract
from ehr_rwe_eln.eln.score import Score, add
from ehr_rwe_eln.eln.synthetic import generate_entries, subject_registry

pytestmark = pytest.mark.evals

ENTRIES = 40
# The bar for writing extractions to OMOP without review.
MIN_PRECISION = MIN_RECALL = 0.95


def _report(label: str, score: Score) -> None:
    for name, counts in (("samples", score.samples), ("results", score.results)):
        print(
            f"{label:<16}{name}: precision {counts.precision:.3f}, recall {counts.recall:.3f},"
            f" f1 {counts.f1:.3f} ({counts.true_positive} of {counts.expected} expected,"
            f" {counts.extracted} extracted)"
        )


@pytest.mark.parametrize(("seed", "hard"), [(2026, False), (2027, True)], ids=["default", "hard"])
def test_extraction_precision_and_recall(seed, hard):
    windows = {
        code: (date(2015, 1, 1), date(2024, 12, 31)) for code in subject_registry(list(range(60)))
    }
    score, by_trap = Score(), defaultdict(Score)
    for entry in generate_entries(windows, ENTRIES, seed=seed, hard=hard):
        got = extract(entry.body)
        add(score, entry.entry_id, got, entry.truth)
        for trap in entry.traps:
            add(by_trap[trap], entry.entry_id, got, entry.truth)

    _report("all", score)
    for trap in sorted(by_trap):
        _report(trap, by_trap[trap])
    for entry_id, error in score.errors:
        print(f"  {entry_id}: {error}")
    for counts in (score.samples, score.results):
        assert counts.precision >= MIN_PRECISION
        assert counts.recall >= MIN_RECALL
