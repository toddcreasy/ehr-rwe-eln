"""Write the clinical panel's carriers to OMOP measurement rows, with OMOP Genomic concepts.

Usage: uv run python scripts/write_panel_omop.py

Run scripts/generate_genomics.py and scripts/generate_panel.py first, and download the OMOP
Genomic vocabulary from Athena into data/vocab_genomic/ (only OMOP Genomic is loaded from it,
once). Writes to the staging Postgres, as every OMOP writer does; then republish the changed
tables (scripts/publish_omop.py --tables ...). Each variant's MANE HGVS comes from Ensembl VEP,
cached in data/reference/ensembl/. Checks the rows against panel_truth.json before committing.
"""

import json
from pathlib import Path

import polars as pl

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.curation import vep
from ehr_rwe_eln.genomics.omop import (
    VOCABULARY,
    check_against_truth,
    load_genomic_vocabulary,
    read_panel_genotypes,
    write_panel_measurements,
)

ROOT = Path(__file__).resolve().parent.parent
GENOMICS = ROOT / "data" / "genomics"
REGISTRY = ROOT / "data" / "registry" / "genomics_subjects.tsv"
BUNDLE = ROOT / "data" / "vocab_genomic"


def main() -> None:
    truth = json.loads((GENOMICS / "panel_truth.json").read_text())["variants"]
    gnomad_id = {
        v["id"]: "-".join([v["id"].removeprefix("chr").split(":")[0], *v["id"].split(":")[1:]])
        for v in truth
    }
    cache = ROOT / "data" / "reference" / "ensembl" / f"vep_{vep.release()}.json"
    annotated = vep.annotate(list(gnomad_id.values()), {v["gene"] for v in truth}, cache)
    variants = [
        {"id": v["id"], "gene": v["gene"]} | (annotated[gnomad_id[v["id"]]] or {}) for v in truth
    ]
    registry = pl.read_csv(REGISTRY, separator="\t")
    mapping = pl.read_csv(GENOMICS / "subject_sample_mapping.tsv", separator="\t")
    person_of_subject = dict(registry.select("subject_id", "person_id").iter_rows())
    people = dict(
        mapping.join(registry, on="subject_id").select("sample_id", "person_id").iter_rows()
    )

    con = DatabaseSettings().connect()
    loaded = con.execute("SELECT 1 FROM cdm.vocabulary WHERE vocabulary_id = %s", [VOCABULARY])
    if not loaded.fetchone():
        print(f"loading {VOCABULARY} from {BUNDLE.relative_to(ROOT)}")
        for name, n in load_genomic_vocabulary(con, BUNDLE).items():
            print(f"  {name.replace('_', ' '):<30}{n:>10,}")
    version = con.execute(
        "SELECT vocabulary_version FROM cdm.vocabulary WHERE vocabulary_id = %s", [VOCABULARY]
    ).fetchone()[0]
    counts = write_panel_measurements(
        con, variants, read_panel_genotypes(GENOMICS / "panel.vcf.gz"), people
    )
    check = check_against_truth(con, truth, person_of_subject)
    print(f"{version}; {cache.name}")
    for name, n in (counts | {f"truth_{k}": v for k, v in check.items()}).items():
        print(f"  {name.replace('_', ' '):<30}{n:>10,}")
    if (
        check["missing"]
        or check["extra"]
        or check["variants_wrong_count"]
        or counts["measurements"] != counts["carrier_genotypes"]
    ):
        con.rollback()
        raise SystemExit("rows do not match the panel's carriers; nothing written")
    con.commit()


if __name__ == "__main__":
    main()
