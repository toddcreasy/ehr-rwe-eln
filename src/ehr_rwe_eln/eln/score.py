"""Score extractions against the known truth: precision, recall, and F1 for samples and results.

Precision is the share of extracted items that are correct; recall is the share of true items
that were extracted; F1 is their harmonic mean. A sample counts as correct when its sample id,
subject, specimen type, and collection date all match. A result counts when its sample, analyte,
value, and unit all match. Counts add up across entries before dividing (micro-averaging), so
an entry with many results weighs more than one with few.
"""

from dataclasses import dataclass, field

from ehr_rwe_eln.eln.models import Extraction


@dataclass
class Counts:
    true_positive: int = 0
    extracted: int = 0
    expected: int = 0

    @property
    def precision(self) -> float:
        return self.true_positive / self.extracted if self.extracted else 1.0

    @property
    def recall(self) -> float:
        return self.true_positive / self.expected if self.expected else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class Score:
    samples: Counts = field(default_factory=Counts)
    results: Counts = field(default_factory=Counts)
    # (entry id, what went wrong), for reading the misses.
    errors: list[tuple[str, str]] = field(default_factory=list)


def _sample_key(s) -> tuple:
    return (s.sample_id, s.subject_id, s.specimen_type, s.collection_date)


def _result_key(r) -> tuple:
    return (r.sample_id, r.analyte, round(r.value, 6), r.unit)


def add(score: Score, entry_id: str, got: Extraction, truth: Extraction) -> None:
    for counts, key, got_items, true_items in (
        (score.samples, _sample_key, got.samples, truth.samples),
        (score.results, _result_key, got.results, truth.results),
    ):
        got_keys, true_keys = {key(i) for i in got_items}, {key(i) for i in true_items}
        counts.true_positive += len(got_keys & true_keys)
        counts.extracted += len(got_items)
        counts.expected += len(true_items)
        score.errors += [(entry_id, f"extra {k}") for k in sorted(got_keys - true_keys, key=str)]
        score.errors += [(entry_id, f"missed {k}") for k in sorted(true_keys - got_keys, key=str)]
