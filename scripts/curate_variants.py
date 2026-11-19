"""Curate variants with the expert-panel rules (src/ehr_rwe_eln/curation/rules.yaml).

Usage:
    uv run python scripts/curate_variants.py --set panel
        the clinical panel's variants (data/genomics/panel.vcf.gz; scripts/generate_panel.py)
    uv run python scripts/curate_variants.py --set eval [--per-class 20]
        ClinVar expert-panel (3-star) variants in the rules' genes, up to per-class from each
        gene and class, scored against the panel's classification, which the rules never see

Reads positions and alleles only. Evidence comes from gnomAD v4 (frequencies) and Ensembl VEP
(consequences on the MANE Select transcript), both cached under data/reference/, so a rerun
makes no requests. The first eval run asks gnomAD about each sampled variant at about 70
variants a minute. Each run is stored in curation.run and curation.assessment.

This tool includes data from the gnomAD v4 release (https://gnomad.broadinstitute.org).
"""

import argparse
import gzip
import time
from pathlib import Path

import numpy as np
import polars as pl

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.curation.curate import ORDER, curate, save_run, score, sources
from ehr_rwe_eln.curation.rules import load_rules
from ehr_rwe_eln.curation.vep import annotate, exons, release
from ehr_rwe_eln.genomics.clinvar import read_clinvar
from ehr_rwe_eln.genomics.gnomad import details, gnomad_id
from ehr_rwe_eln.genomics.panel import SHORT, load_panel_spec

DATA = Path(__file__).resolve().parent.parent / "data"
REFERENCE = DATA / "reference"
CLASSES = [
    "Pathogenic",
    "Likely_pathogenic",
    "Uncertain_significance",
    "Likely_benign",
    "Benign",
]


def panel_variants() -> list[dict]:
    rows = []
    with gzip.open(DATA / "genomics" / "panel.vcf.gz", "rt") as f:
        for line in f:
            if not line.startswith("#"):
                chrom, pos, _, ref, alt = line.split("\t", 5)[:5]
                rows.append(
                    {
                        "id": f"{chrom}:{pos}:{ref}:{alt}",
                        "gnomad_id": gnomad_id(chrom, int(pos), ref, alt),
                    }
                )
    return rows


def eval_variants(genes: set[str], release_date: str, per_class: int) -> list[dict]:
    clinvar = read_clinvar(REFERENCE / "clinvar" / f"clinvar_{release_date}.vcf.gz", genes)
    expert = clinvar.filter(
        (pl.col("stars") >= 3)
        & pl.col("classification").is_in(CLASSES)
        & (pl.max_horizontal(pl.col("ref").str.len_chars(), pl.col("alt").str.len_chars()) < SHORT)
    ).sort("variation_id")
    rng = np.random.default_rng(0)
    rows = []
    for (_, classification), group in expert.group_by(
        "gene", "classification", maintain_order=True
    ):
        picked = group[np.sort(rng.permutation(len(group))[:per_class]).tolist()]
        for r in picked.iter_rows(named=True):
            rows.append(
                {
                    "id": f"{r['chromosome']}:{r['position']}:{r['ref']}:{r['alt']}",
                    "gnomad_id": gnomad_id(r["chromosome"], r["position"], r["ref"], r["alt"]),
                    "expected": classification,
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["panel", "eval"], required=True)
    parser.add_argument("--per-class", type=int, default=20)
    args = parser.parse_args()

    rules = load_rules()
    panel = load_panel_spec()
    start = time.time()
    variants = (
        panel_variants()
        if args.set == "panel"
        else eval_variants(set(rules.genes), panel.clinvar_release, args.per_class)
    )
    ids = [v["gnomad_id"] for v in variants]
    ensembl = release()
    consequences = annotate(ids, set(rules.genes), REFERENCE / "ensembl" / f"vep_{ensembl}.json")
    transcripts = sorted({c["transcript"] for c in consequences.values() if c})
    lengths = exons(transcripts, REFERENCE / "ensembl" / f"exons_{ensembl}.json")
    frequencies = details(
        ids, REFERENCE / "gnomad" / f"{panel.gnomad_dataset}_details.json", panel.gnomad_dataset
    )
    assessments = curate(variants, rules, frequencies, consequences, lengths)
    clinvar = panel.clinvar_release if args.set == "eval" else None
    summary = score(assessments) if args.set == "eval" else {"variants": len(assessments)}
    summary["classes"] = {
        c: sum(a["classification"] == c for a in assessments)
        for c in [
            "Pathogenic",
            "Likely pathogenic",
            "Uncertain significance",
            "Likely benign",
            "Benign",
        ]
    }
    with DatabaseSettings().connect() as con:
        run_id = save_run(
            con,
            args.set,
            sources(rules, panel.gnomad_dataset, ensembl, clinvar),
            assessments,
            summary,
        )
        con.commit()

    print(
        f"run {run_id}: {len(assessments)} {args.set} variants"
        f" in {time.time() - start:.0f}s (Ensembl {ensembl})"
    )
    print("  classes:", ", ".join(f"{k} {v}" for k, v in summary["classes"].items()))
    if args.set == "eval":
        print(
            f"  agreement with the expert panels: {summary['agreement']:.1%};"
            f" reversals: {summary['reversals']}"
        )
        print("  expected (rows) by rules (columns):", "  ".join(ORDER))
        for e in ORDER:
            print(f"    {e:<5}", "  ".join(f"{summary['confusion'][e][c]:>4}" for c in ORDER))
        for gene, g in summary["by_gene"].items():
            print(
                f"  {gene:<6} {g['agreement']:.0%} of {g['variants']}, reversals {g['reversals']}"
            )
        print("  criteria met:", summary["criteria"])


if __name__ == "__main__":
    main()
