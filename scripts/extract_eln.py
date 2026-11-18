"""Extract every ELN entry with the Message Batches API and store the results in the eln schema.

Usage: uv run python scripts/extract_eln.py [--batch-id msgbatch_...]

Loads data/registry/eln_subjects.csv and data/eln/entries.jsonl (scripts/generate_eln.py) into
eln.subject and eln.entry, sends one batch for the entries with no extraction yet (or a failed
one), waits for it, and stores each result in eln.extraction. Prints precision and recall against
the truth in entries.jsonl. Batches cost half of single calls and usually finish within minutes;
if this script stops while waiting, rerun it with the printed --batch-id instead of paying again.

Needs migrations applied (uv run alembic upgrade head) and ANTHROPIC_API_KEY in .env.
"""

import argparse
import csv
import json
import time
from datetime import date
from pathlib import Path

import anthropic

from ehr_rwe_eln.agents.config import AgentSettings
from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.eln.batch import batch_requests, read_result
from ehr_rwe_eln.eln.models import Extraction
from ehr_rwe_eln.eln.score import Score, add
from ehr_rwe_eln.eln.store import (
    extractions,
    load_entries,
    load_subjects,
    pending,
    save_extraction,
)

DATA = Path(__file__).resolve().parent.parent / "data" / "eln"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-id", help="resume waiting on a batch already sent")
    args = parser.parse_args()

    settings = AgentSettings()
    key = settings.anthropic_api_key
    client = anthropic.Anthropic(api_key=key.get_secret_value() if key else None)
    model = settings.model

    with (DATA.parent / "registry" / "eln_subjects.csv").open() as f:
        registry = {row["subject_id"]: int(row["person_id"]) for row in csv.DictReader(f)}
    rows = [json.loads(line) for line in (DATA / "entries.jsonl").open()]
    truth = {r["entry_id"]: Extraction.model_validate(r["truth"]) for r in rows}

    con = DatabaseSettings().connect()
    load_subjects(con, registry)
    load_entries(
        con,
        [
            (r["entry_id"], r["title"], r["author"], date.fromisoformat(r["created"]), r["body"])
            for r in rows
        ],
    )
    con.commit()

    batch_id = args.batch_id
    if batch_id is None:
        todo = pending(con)
        if todo:
            batch_id = client.messages.batches.create(requests=batch_requests(todo, model)).id
            print(f"sent {len(todo)} entries as batch {batch_id}", flush=True)
        else:
            print("every entry already has an extraction")
    if batch_id:
        while (batch := client.messages.batches.retrieve(batch_id)).processing_status != "ended":
            counts = batch.request_counts
            print(f"  {batch.processing_status}: {counts.processing} processing", flush=True)
            time.sleep(30)
        failed = 0
        for result in client.messages.batches.results(batch_id):
            extraction, error = read_result(result)
            failed += error is not None
            save_extraction(con, result.custom_id, model, batch_id, extraction, error)
        con.commit()
        print(f"stored batch {batch_id}: {failed} failed")

    score = Score()
    for entry_id, extraction in extractions(con).items():
        add(score, entry_id, extraction, truth[entry_id])
    for name, counts in (("samples", score.samples), ("results", score.results)):
        print(
            f"{name}: precision {counts.precision:.3f}, recall {counts.recall:.3f}"
            f" ({counts.true_positive} of {counts.expected} expected, {counts.extracted} extracted)"
        )
    for entry_id, error in score.errors:
        print(f"  {entry_id}: {error}")


if __name__ == "__main__":
    main()
