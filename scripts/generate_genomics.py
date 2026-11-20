"""Simulate a dbGaP-style genotyping study for adults in the OMOP build, with one genetic
effect planted on a phenotype.

Usage: uv run python scripts/generate_genomics.py
           [--people 5000] [--chromosomes 3] [--length 3000000] [--odds-ratio 1.4]
           [--phenotype hypertension] [--seed 0]

Writes data/genomics/ (gitignored): VCFs per chromosome, a PLINK set, subject and sample
tables, and truth.json; the registry linking study codes to persons goes to
data/registry/genomics_subjects.tsv, outside the study folder. The same arguments always give
the same files. Synthetic only.
"""

import argparse
import time
from pathlib import Path

import numpy as np

from ehr_rwe_eln.cohort.lake import connect_omop
from ehr_rwe_eln.genomics.study import build_study, write_study
from ehr_rwe_eln.synth.source import build_source
from ehr_rwe_eln.synth.spec import SPECS, load_spec

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "genomics"
REGISTRY = DATA / "registry" / "genomics_subjects.tsv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--people", type=int, default=5000)
    parser.add_argument("--chromosomes", type=int, default=3)
    parser.add_argument("--length", type=int, default=3_000_000)
    parser.add_argument("--odds-ratio", type=float, default=1.4)
    parser.add_argument("--phenotype", default="hypertension")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    # The person summary already has age, sex, and the condition flags, one row per person.
    omop, cdm = connect_omop()
    with omop:
        source = build_source(omop, load_spec(SPECS / "person_summary.yaml"), cdm)
    adults = source[source["age"] >= 18]
    rng = np.random.default_rng(args.seed)
    people = adults.loc[np.sort(rng.choice(adults.index, args.people, replace=False))]

    start = time.time()
    study = build_study(
        people, args.phenotype, args.chromosomes, args.length, args.odds_ratio, args.seed
    )
    write_study(OUT, study, REGISTRY)
    truth = study.truth
    print(
        f"{truth['people']:,} people ({truth['cases']:,} with {args.phenotype}),"
        f" {truth['variants']:,} variants on {args.chromosomes} chromosomes"
        f" in {time.time() - start:.0f}s"
    )
    v = truth["variant"]
    print(
        f"planted {v['id']}: alternate allele frequency {v['alt_frequency_cases']:.3f} in"
        f" cases, {v['alt_frequency_controls']:.3f} in controls (odds ratio {args.odds_ratio})"
    )
    print(f"written to {OUT}; registry in {REGISTRY}")


if __name__ == "__main__":
    main()
