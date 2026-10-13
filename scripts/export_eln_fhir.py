"""Export the stored ELN extractions as a FHIR R4 Bundle of Specimen and Observation resources.

Usage: uv run python scripts/export_eln_fhir.py

Run scripts/extract_eln.py first. Writes data/eln/fhir_bundle.json, the same file for the same
extractions, and prints what it holds.
"""

from pathlib import Path

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.eln.fhir import build_bundle

OUT = Path(__file__).resolve().parent.parent / "data" / "eln" / "fhir_bundle.json"


def main() -> None:
    with DatabaseSettings().connect() as con:
        bundle = build_bundle(con)
    resources = [e.resource for e in bundle.entry or []]
    specimens = [r for r in resources if r.get_resource_type() == "Specimen"]
    observations = [r for r in resources if r.get_resource_type() == "Observation"]
    counts = {
        "specimens": len(specimens),
        "observations": len(observations),
        "specimens_without_collection_date": sum(s.collection is None for s in specimens),
        "uncoded_observations": sum(not o.code.coding for o in observations),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(bundle.model_dump_json(indent=2, exclude_none=True))
    for name, n in counts.items():
        print(f"  {name.replace('_', ' '):<36}{n:>8,}")
    print(f"written to {OUT}")


if __name__ == "__main__":
    main()
