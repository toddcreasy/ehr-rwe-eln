"""Generate synthetic ELN entries for module 2, with their known extractions.

Usage: uv run python scripts/generate_eln.py [--subjects 200] [--entries 300] [--seed 0]

Subjects are adults with essential hypertension in the CDM, as study codes HTN-0001 and on,
assigned in a random order.
Each specimen is collected inside its subject's observation period, on or after their 18th
birthday. Writes data/eln/entries.jsonl (one entry per line, with its truth) and the registry
linking codes to persons, data/registry/eln_subjects.csv (code, person_id). The registry is the
re-identification key, so it is kept out of data/eln/, the folder a study would share. The same
arguments always give the same files. Synthetic only.
"""

import argparse
import csv
import json
import random
from pathlib import Path

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.eln.synthetic import generate_entries, subject_registry

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "eln"
REGISTRY = DATA / "registry" / "eln_subjects.csv"

# Adults with essential hypertension, and the part of their observation period from age 18 that
# overlaps the years entries are dated in.
SUBJECTS_SQL = """
SELECT op.person_id,
       greatest(op.observation_period_start_date,
                make_date(p.year_of_birth + 18, 1, 1), DATE '2015-01-01') AS start,
       least(op.observation_period_end_date, DATE '2024-12-31') AS stop
FROM cdm.observation_period op
JOIN cdm.person p USING (person_id)
WHERE op.person_id IN (
    SELECT person_id FROM cdm.condition_occurrence
    WHERE condition_concept_id IN (
        SELECT descendant_concept_id FROM cdm.concept_ancestor WHERE ancestor_concept_id = 320128
    )
)
ORDER BY op.person_id
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subjects", type=int, default=200)
    parser.add_argument("--entries", type=int, default=300)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    with DatabaseSettings().connect() as con:
        windows = [r for r in con.execute(SUBJECTS_SQL).fetchall() if r[1] <= r[2]]
    if not windows:
        raise SystemExit("no eligible subjects; build the CDM first (scripts/build_omop.py)")
    rng = random.Random(args.seed)  # noqa: S311  (seeded subject choice, not cryptography)
    chosen = sorted(rng.sample(windows, min(args.subjects, len(windows))))
    registry = subject_registry([person_id for person_id, _, _ in chosen], rng)
    subjects = {
        code: (start, stop) for code, (_, start, stop) in zip(registry, chosen, strict=True)
    }
    entries = generate_entries(subjects, args.entries, args.seed)

    OUT.mkdir(parents=True, exist_ok=True)
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["subject_id", "person_id"])
        writer.writerows(registry.items())
    with (OUT / "entries.jsonl").open("w") as f:
        for e in entries:
            row = {
                "entry_id": e.entry_id,
                "title": e.title,
                "author": e.author,
                "created": e.created.isoformat(),
                "body": e.body,
                "truth": e.truth.model_dump(mode="json"),
            }
            f.write(json.dumps(row) + "\n")
    samples = sum(len(e.truth.samples) for e in entries)
    results = sum(len(e.truth.results) for e in entries)
    print(f"{len(registry)} subjects, {len(entries)} entries, {samples} samples, {results} results")
    print(f"written to {OUT}; registry in {REGISTRY}")


if __name__ == "__main__":
    main()
