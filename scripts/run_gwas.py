"""Run the GWAS on data/genomics/ and check it against the planted effect.

Usage: uv run python scripts/run_gwas.py

Run scripts/generate_genomics.py first. Writes data/genomics/gwas.parquet (one row per
variant) and prints the loci, the genomic inflation, and whether the planted variant was found.
"""

import json
import time
from pathlib import Path

from ehr_rwe_eln.genomics.gwas import SIGNIFICANCE, check_truth, run_gwas

DIRECTORY = Path(__file__).resolve().parent.parent / "data" / "genomics"


def main() -> None:
    truth = json.loads((DIRECTORY / "truth.json").read_text())
    start = time.time()
    results, summary = run_gwas(DIRECTORY, truth["phenotype"])
    results.write_parquet(DIRECTORY / "gwas.parquet")
    by_chromosome = summary["genomic_inflation_by_chromosome"]
    print(
        f"{summary['variants']:,} variants, {summary['people']:,} people,"
        f" {time.time() - start:.0f}s; genomic inflation {summary['genomic_inflation']:.3f}"
        f" (by chromosome: {', '.join(f'{c} {v:.2f}' for c, v in by_chromosome.items())});"
        f" {summary['significant_variants']} variants below p {SIGNIFICANCE:g}"
    )
    for locus in summary["loci"]:
        low, high = locus["ci"]
        print(
            f"  locus {locus['id']}: p {locus['p']:.2e}, odds ratio {locus['odds_ratio']:.2f}"
            f" ({low:.2f} to {high:.2f}), alternate allele frequency {locus['alt_frequency']:.3f}"
        )
    check = check_truth(results, summary, truth)
    print(
        f"planted {truth['variant']['id']} (odds ratio {truth['odds_ratio_planted']}):"
        f" found {check['planted_found']} at p {check['planted_p']:.2e}; lead variant is the"
        f" planted one {check['lead_is_planted']}; other loci {check['other_loci']};"
        f" genomic inflation without its chromosome"
        f" {check['genomic_inflation_null_chromosomes']:.3f}"
    )


if __name__ == "__main__":
    main()
