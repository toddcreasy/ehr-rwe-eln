import re
from datetime import date

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


def test_registry_codes_follow_the_given_order():
    assert list(subject_registry([5, 3]).items()) == [("HTN-0001", 5), ("HTN-0002", 3)]


def test_same_seed_same_entries():
    again = generate_entries(WINDOWS, 200, seed=7)
    assert [e.body for e in again] == [e.body for e in ENTRIES]
    assert [e.truth for e in again] == [e.truth for e in ENTRIES]


def test_the_truth_is_what_the_entry_says():
    for e in ENTRIES:
        numbers = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", e.body)}
        for s in e.truth.samples:
            assert s.sample_id in e.body and s.subject_id in e.body
        sample_ids = {s.sample_id for s in e.truth.samples}
        for r in e.truth.results:
            assert r.sample_id in sample_ids
            assert r.value in numbers


def test_qc_lines_name_no_sample():
    qc = [line for e in ENTRIES for line in e.body.splitlines() if line.startswith("QC level")]
    assert qc
    assert not any(re.search(r"S-\d{4}-\d{2}", line) for line in qc)


def test_specimens_are_collected_inside_their_subjects_windows():
    for e in ENTRIES:
        for s in e.truth.samples:
            if s.collection_date is not None:
                start, end = WINDOWS[s.subject_id]
                assert start <= s.collection_date <= end


def test_sample_ids_never_repeat():
    ids = [s.sample_id for e in ENTRIES for s in e.truth.samples]
    assert len(ids) == len(set(ids))


def test_every_trap_and_style_occurs():
    bodies = "\n".join(e.body for e in ENTRIES)
    for marker in ("failed QC", "QC level", "Reagent lot", "| Subject |", "- S-", "Subject HTN-"):
        assert marker in bodies
