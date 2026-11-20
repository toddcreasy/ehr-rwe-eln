"""Extract every ELN entry with Claude on Bedrock and store the results in the eln schema.

Usage: uv run python scripts/extract_eln.py [--workers 4]

Loads data/registry/eln_subjects.csv and data/eln/entries.jsonl (scripts/generate_eln.py) into
eln.subject and eln.entry, extracts the entries with no extraction yet (or a failed one), a few
calls at a time, and stores each result in eln.extraction as it arrives, so a rerun after a stop
picks up where it left off. Prints precision and recall against the truth in entries.jsonl.
Bedrock has no Message Batches API, so these are ordinary calls at the full price.

Needs migrations applied (uv run alembic upgrade head) and AWS credentials (aws sso login).
"""

import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import anthropic

from ehr_rwe_eln.agents.config import AgentSettings, claude_client
from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.eln.extract import ExtractionFailed, extract
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
    parser.add_argument("--workers", type=int, default=4, help="calls in flight at once")
    args = parser.parse_args()

    client = claude_client()
    model = AgentSettings().model

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

    def run(entry_id: str, body: str) -> tuple[str, Extraction | None, str | None]:
        try:
            return entry_id, extract(body, client, model), None
        except (ExtractionFailed, anthropic.APIError) as exc:
            return entry_id, None, str(exc)[:500]

    todo = pending(con)
    if not todo:
        print("every entry already has an extraction")
    failed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run, entry_id, body) for entry_id, body in todo.items()]
        for done, future in enumerate(as_completed(futures), 1):
            entry_id, extraction, error = future.result()
            failed += error is not None
            save_extraction(con, entry_id, model, None, extraction, error)
            con.commit()
            if done % 25 == 0 or done == len(futures):
                print(f"  {done} of {len(futures)} extracted, {failed} failed", flush=True)

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
