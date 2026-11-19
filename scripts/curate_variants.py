"""Curate variants with the expert-panel rules (src/ehr_rwe_eln/curation/rules.yaml).

Usage:
    uv run python scripts/curate_variants.py --set panel
        the clinical panel's variants (data/genomics/panel.vcf.gz; scripts/generate_panel.py)
    uv run python scripts/curate_variants.py --set eval [--per-class 20]
        ClinVar expert-panel (3-star) variants in the rules' genes, up to per-class from each
        gene and class, scored against the panel's classification, which the rules never see
    uv run python scripts/curate_variants.py --set erepo
        every ClinGen Evidence Repository curation in the rules' genes, scored by class and
        criterion by criterion against the codes the panel applied (downloads the export,
        33 MB, to data/reference/clingen/ if none is there)

Reads positions and alleles only. Evidence comes from gnomAD v4 (frequencies) and Ensembl VEP
(consequences on the MANE Select transcript), both cached under data/reference/, so a rerun
makes no requests. The first eval run asks gnomAD about each sampled variant at about 70
variants a minute. Each run is stored in curation.run and curation.assessment.

This tool includes data from the gnomAD v4 release (https://gnomad.broadinstitute.org).
"""

import argparse
import gzip
import time
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from ehr_rwe_eln.config import DatabaseSettings
from ehr_rwe_eln.curation.curate import ORDER, curate, save_run, score, sources
from ehr_rwe_eln.curation.erepo import SCORED, read_erepo, score_criteria
from ehr_rwe_eln.curation.erepo import URL as EREPO_URL
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


def erepo_path() -> Path:
    found = sorted((REFERENCE / "clingen").glob("erepo_*.tsv"))
    if found:
        return found[-1]
    path = REFERENCE / "clingen" / f"erepo_{date.today():%Y%m%d}.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {EREPO_URL}")
    urllib.request.urlretrieve(EREPO_URL, path)  # noqa: S310  (fixed https URL)
    return path


def erepo_variants(genes: set[str], release_date: str, path: Path) -> list[dict]:
    """ClinVar's records for every Evidence Repository curation in genes, matched by ClinVar
    variation id, with the panel's class and codes."""
    curations = read_erepo(path, genes)
    clinvar = read_clinvar(REFERENCE / "clinvar" / f"clinvar_{release_date}.vcf.gz", genes)
    short = clinvar.filter(
        pl.col("variation_id").is_in(list(curations))
        & (pl.max_horizontal(pl.col("ref").str.len_chars(), pl.col("alt").str.len_chars()) < SHORT)
    ).sort("variation_id")
    rows = []
    for r in short.iter_rows(named=True):
        c = curations[r["variation_id"]]
        rows.append(
            {
                "id": f"{r['chromosome']}:{r['position']}:{r['ref']}:{r['alt']}",
                "gnomad_id": gnomad_id(r["chromosome"], r["position"], r["ref"], r["alt"]),
                "expected": c["assertion"],
                "expert": {"met": c["met"], "not_met": c["not_met"], "pmids": c["pmids"]},
            }
        )
    print(f"{len(curations)} Evidence Repository curations; {len(rows)} short variants in ClinVar")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["panel", "eval", "erepo"], required=True)
    parser.add_argument("--per-class", type=int, default=20)
    args = parser.parse_args()

    rules = load_rules()
    panel = load_panel_spec()
    start = time.time()
    erepo = erepo_path() if args.set == "erepo" else None
    if args.set == "panel":
        variants = panel_variants()
    elif args.set == "eval":
        variants = eval_variants(set(rules.genes), panel.clinvar_release, args.per_class)
    else:
        variants = erepo_variants(set(rules.genes), panel.clinvar_release, erepo)
    ids = [v["gnomad_id"] for v in variants]
    ensembl = release()
    consequences = annotate(ids, set(rules.genes), REFERENCE / "ensembl" / f"vep_{ensembl}.json")
    transcripts = sorted({c["transcript"] for c in consequences.values() if c})
    lengths = exons(transcripts, REFERENCE / "ensembl" / f"exons_{ensembl}.json")
    frequencies = details(
        ids, REFERENCE / "gnomad" / f"{panel.gnomad_dataset}_details.json", panel.gnomad_dataset
    )
    assessments = curate(variants, rules, frequencies, consequences, lengths)
    clinvar = panel.clinvar_release if args.set != "panel" else None
    summary = score(assessments) if args.set != "panel" else {"variants": len(assessments)}
    if erepo:
        summary["criteria_vs_panel"] = score_criteria(assessments)
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
        run_sources = sources(rules, panel.gnomad_dataset, ensembl, clinvar)
        if erepo:
            run_sources["erepo"] = erepo.name
        run_id = save_run(con, args.set, run_sources, assessments, summary)
        con.commit()

    print(
        f"run {run_id}: {len(assessments)} {args.set} variants"
        f" in {time.time() - start:.0f}s (Ensembl {ensembl})"
    )
    print("  classes:", ", ".join(f"{k} {v}" for k, v in summary["classes"].items()))
    if args.set != "panel":
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
    if erepo:
        print("  per criterion against the panel's codes (agreed, extra, missed; strength):")
        for code in SCORED:
            c = summary["criteria_vs_panel"][code]
            extra = c.get("extra_marked_not_met", 0) + c.get("extra_not_listed", 0)
            if not (c.get("agreed") or extra or c.get("missed")):
                continue
            pct = lambda x: "-" if x is None else f"{x:.0%}"  # noqa: E731
            print(
                f"    {code:<5} agreed {c.get('agreed', 0):>3}, extra {extra:>3}"
                f" ({c.get('extra_marked_not_met', 0)} marked not met), missed"
                f" {c.get('missed', 0):>3}; precision {pct(c['precision'])}, recall"
                f" {pct(c['recall'])}; same strength {c.get('same_strength', 0)}"
            )


if __name__ == "__main__":
    main()
