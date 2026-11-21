"""Run the GWAS on data/genomics/ and check it against the planted effect.

Usage: uv run python scripts/run_gwas.py [--no-pcs]

Run scripts/generate_genomics.py first, then scripts/run_regenie.py (PLINK 2 PCs and REGENIE, on
AWS). Fits the score test with age, sex, and the newest REGENIE run's 10 PCs as covariates
(--no-pcs: age and sex only, the uncorrected test), writes data/genomics/gwas.parquet (one row
per variant), and prints the loci, the genomic inflation with its percentile among phenotypes
simulated with no genetic effect, and whether the planted variant was found. Then the same for
REGENIE's results, calibrated by the score test's null runs on the same variants, and how well
the PCs recover the simulated populations. If the Hail container has run (docker compose run
--rm --build hail), also compares the score test with Hail's.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import polars as pl

from ehr_rwe_eln.genomics.gwas import (
    NULL_RUNS,
    SIGNIFICANCE,
    check_truth,
    compare_with_hail,
    inflation,
    loci,
    pc_ancestry_agreement,
    read_pcs,
    read_regenie,
    run_gwas,
)

DIRECTORY = Path(__file__).resolve().parent.parent / "data" / "genomics"


def newest_regenie_run() -> Path | None:
    runs = sorted(p.parent for p in (DIRECTORY / "regenie").glob("*/run.json"))
    return runs[-1] if runs else None


def print_check(check: dict, truth: dict) -> None:
    null = check["calibration_null_chromosomes"]
    print(
        f"  planted {truth['variant']['id']} (odds ratio {truth['odds_ratio_planted']}):"
        f" found {check['planted_found']} at p {check['planted_p']:.2e}; a locus within 500 kb"
        f" {check['locus_near_planted']}, led by the planted variant {check['lead_is_planted']};"
        f" other loci {check['other_loci']}; genomic inflation without its chromosome"
        f" {null['lambda']:.3f}, percentile {null['percentile']:.0f} of {NULL_RUNS} null runs"
        f" (their middle 95%: {null['null_range'][0]:.2f} to {null['null_range'][1]:.2f})"
    )


def report_regenie(run: Path, results: pl.DataFrame, summary: dict, truth: dict) -> None:
    """REGENIE on the variants QC kept, with the score test's null runs for those variants."""
    regenie = read_regenie(next(run.glob("step2_*.regenie")))
    index = {v: i for i, v in enumerate(results["id"])}
    columns = np.array([index[v] for v in regenie["id"]])
    found = loci(regenie)
    frequency = regenie["alt_frequency"]
    common = regenie.filter(pl.min_horizontal(frequency, 1 - frequency) >= 0.05)
    print(
        f"REGENIE ({run.name}): {len(regenie):,} variants after QC; genomic inflation"
        f" {inflation(common):.3f}; {int((regenie['p'] < SIGNIFICANCE).sum())} variants below"
        f" p {SIGNIFICANCE:g}"
    )
    for locus in found:
        print(f"  locus {locus['id']}: p {locus['p']:.2e}")
    if truth["variant"]["id"] not in index or truth["variant"]["id"] not in set(regenie["id"]):
        print("  the planted variant did not pass QC")
        return
    check = check_truth(
        regenie, {"loci": found, "null_statistics": summary["null_statistics"][:, columns]}, truth
    )
    print_check(check, truth)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-pcs", action="store_true", help="age and sex only")
    args = parser.parse_args()
    truth = json.loads((DIRECTORY / "truth.json").read_text())
    run = newest_regenie_run()
    if run is None and not args.no_pcs:
        raise SystemExit("no REGENIE run in data/genomics/regenie/: run scripts/run_regenie.py,"
                         " or pass --no-pcs")  # fmt: skip
    pcs = None if args.no_pcs else run / "pcs.eigenvec"
    start = time.time()
    results, summary = run_gwas(DIRECTORY, truth["phenotype"], pcs=pcs)
    results.write_parquet(DIRECTORY / "gwas.parquet")
    by_chromosome = ", ".join(
        f"{c} {v['lambda']:.2f} p{v['percentile']:.0f}"
        for c, v in summary["calibration_by_chromosome"].items()
    )
    print(
        f"score test, {'age and sex' if pcs is None else 'age, sex, and 10 PCs'}:"
        f" {summary['variants']:,} variants, {summary['people']:,} people,"
        f" {time.time() - start:.0f}s; genomic inflation {summary['genomic_inflation']:.3f}"
        f" (by chromosome, with its percentile among {NULL_RUNS} null runs: {by_chromosome});"
        f" {summary['significant_variants']} variants below p {SIGNIFICANCE:g}"
    )
    for locus in summary["loci"]:
        low, high = locus["ci"]
        print(
            f"  locus {locus['id']}: p {locus['p']:.2e}, odds ratio {locus['odds_ratio']:.2f}"
            f" ({low:.2f} to {high:.2f}), alternate allele frequency {locus['alt_frequency']:.3f}"
        )
    print_check(check_truth(results, summary, truth), truth)
    if run is not None:
        report_regenie(run, results, summary, truth)
        ancestry = pl.read_csv(DIRECTORY / "ancestry_truth.tsv", separator="\t")
        agreement = pc_ancestry_agreement(
            read_pcs(run / "pcs.eigenvec", ancestry["sample_id"].to_list()),
            ancestry["ancestry"].to_numpy(),
        )
        print(f"the 10 PCs predict {agreement:.1%} of simulated populations (cross-validated)")
    hail_path = DIRECTORY / "hail_gwas.tsv"
    if hail_path.exists() and hail_path.stat().st_mtime < (DIRECTORY / "study.bed").stat().st_mtime:
        print("Hail: its results predate this study; rerun docker compose run --rm hail")
    elif hail_path.exists():
        hail = compare_with_hail(results, hail_path)
        print(
            f"Hail: {hail['matched']:,} of {hail['variants']:,} variants matched; score"
            f" statistics agree to {hail['chi2_max_difference']:.1e} at most (correlation"
            f" {hail['chi2_correlation']:.6f})"
        )


if __name__ == "__main__":
    main()
