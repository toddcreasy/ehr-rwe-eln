import re
from datetime import date

import pytest

from ehr_rwe_eln.eln.synthetic import generate_entries, subject_registry

REGISTRY = subject_registry(list(range(100, 140)))
# Half the subjects are observed early, half late, so the windows matter.
WINDOWS = {
    code: (date(2015, 1, 1), date(2019, 12, 31))
    if i % 2
    else (date(2020, 1, 1), date(2024, 12, 31))
    for i, code in enumerate(REGISTRY)
}
ENTRIES = generate_entries(WINDOWS, 200, seed=7)
HARD = generate_entries(WINDOWS, 200, seed=7, hard=True)
HARD_TRAPS = {"manifest", "units_once", "rejected_sample", "correction", "dilution", "replicates"}


def test_registry_codes_follow_the_given_order():
    assert list(subject_registry([5, 3]).items()) == [("HTN-0001", 5), ("HTN-0002", 3)]


def test_same_seed_same_entries():
    again = generate_entries(WINDOWS, 200, seed=7)
    assert [e.body for e in again] == [e.body for e in ENTRIES]
    assert [e.truth for e in again] == [e.truth for e in ENTRIES]


@pytest.mark.parametrize("entries", [ENTRIES, HARD], ids=["default", "hard"])
def test_the_truth_is_what_the_entry_says(entries):
    for e in entries:
        numbers = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", e.body)}
        for s in e.truth.samples:
            assert s.sample_id in e.body and s.subject_id in e.body
        sample_ids = {s.sample_id for s in e.truth.samples}
        missing = [r for r in e.truth.results if r.value not in numbers]
        assert all(r.sample_id in sample_ids for r in e.truth.results)
        # Only a diluted value is absent: the entry gives it before multiplying.
        assert len(missing) <= ("dilution" in e.traps)


def test_qc_lines_name_no_sample():
    qc = [line for e in ENTRIES for line in e.body.splitlines() if line.startswith("QC level")]
    assert qc
    assert not any(re.search(r"S-\d{4}-\d{2}", line) for line in qc)


@pytest.mark.parametrize("entries", [ENTRIES, HARD], ids=["default", "hard"])
def test_specimens_are_collected_inside_their_subjects_windows(entries):
    for e in entries:
        for s in e.truth.samples:
            if s.collection_date is not None:
                start, end = WINDOWS[s.subject_id]
                assert start <= s.collection_date <= end


@pytest.mark.parametrize("entries", [ENTRIES, HARD], ids=["default", "hard"])
def test_sample_ids_never_repeat(entries):
    ids = [s.sample_id for e in entries for s in e.truth.samples]
    assert len(ids) == len(set(ids))


def test_every_trap_and_style_occurs():
    bodies = "\n".join(e.body for e in ENTRIES)
    for marker in ("failed QC", "QC level", "Reagent lot", "| Subject |", "- S-", "Subject HTN-"):
        assert marker in bodies


def test_default_entries_have_no_hard_traps_and_hard_ones_have_each():
    assert not any(HARD_TRAPS & set(e.traps) for e in ENTRIES)
    assert {t for e in HARD for t in e.traps} >= HARD_TRAPS


def test_hard_traps_change_the_truth_as_the_entry_says():
    for e in HARD:
        measured = {r.sample_id for r in e.truth.results}
        unmeasured = [s.sample_id for s in e.truth.samples if s.sample_id not in measured]
        # A rejected sample is a specimen with no results.
        assert len(unmeasured) == ("rejected_sample" in e.traps)
        for sample_id in unmeasured:
            assert any(sample_id in line and "hemolyzed" in line for line in e.body.splitlines())
        if "manifest" in e.traps:
            assert "Samples:" in e.body and "Results:" in e.body
        if "correction" in e.traps:
            corrected = re.search(r"for (S-\d{4}-\d{2}) is ([\d.]+), not", e.body)
            values = {r.value for r in e.truth.results if r.sample_id == corrected[1]}
            assert float(corrected[2]) in values


ADVERSARIAL = generate_entries(WINDOWS, 200, seed=7, adversarial=True)
INJECTIONS = {"injection_add", "injection_change", "injection_drop"}


def test_every_adversarial_entry_carries_one_injection_and_others_none():
    for e in ADVERSARIAL:
        assert len(INJECTIONS & set(e.traps)) == 1
    assert not any(INJECTIONS & set(e.traps) for e in ENTRIES + HARD)
    assert {t for e in ADVERSARIAL for t in e.traps} >= INJECTIONS


def test_injections_never_change_the_truth():
    for e in ADVERSARIAL:
        assert e.truth.samples and e.truth.results  # a drop injection asks for none
        for s in e.truth.samples:
            assert not s.subject_id.startswith("HTN-9")  # fabricated subjects are 9000 and up
        if "injection_change" in e.traps:
            line = next(x for x in e.body.splitlines() if "AI assistant" in x)
            injected = re.search(r"for (S-\d{4}-\d{2}) as ([\d.]+)", line)
            truth = {r.value for r in e.truth.results if r.sample_id == injected[1]}
            assert float(injected[2]) not in truth
