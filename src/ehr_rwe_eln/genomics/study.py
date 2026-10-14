"""A synthetic genotyping study laid out the way dbGaP distributes one.

dbGaP (NIH's database of Genotypes and Phenotypes) releases a study as genotype files plus
tables keyed by de-identified IDs: subjects with their phenotypes, samples with their
attributes, and a subject-to-sample mapping. A subject is a participant; a sample is the
specimen genotyped from them. Here:

- chr<N>.vcf.gz: phased genotypes per chromosome, one column per sample (VCF 4.2, gzip).
- study.bed, study.bim, study.fam: the same genotypes as one PLINK binary set.
- subject_phenotypes.tsv, sample_attributes.tsv, subject_sample_mapping.tsv.
- subject_registry.tsv: subject code to OMOP person_id. A real study keeps this link with the
  data holder and never distributes it; it is written here so the genotypes can be joined back
  to the OMOP records for testing. Codes are assigned in a random order, never by person_id.
- truth.json: the simulation settings and the planted variant, the answer key for the GWAS.
"""

import gzip
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from bed_reader import to_bed

from ehr_rwe_eln.genomics.simulate import Chromosome, assign_genomes, simulate_chromosome

GENOTYPE_CODES = np.array(["0|0", "0|1", "1|0", "1|1"])


@dataclass
class Study:
    subjects: pd.DataFrame  # indexed by subject id: person_id, sample_id, sex, age, phenotype
    chromosomes: list[Chromosome]  # people in subject order
    truth: dict


def build_study(
    people: pd.DataFrame,
    phenotype: str,
    chromosomes: int,
    length: int,
    odds_ratio: float,
    seed: int,
    min_maf: float = 0.01,
) -> Study:
    """people: one row per person (indexed by person_id) with sex, age, and the 0/1 phenotype
    column. The planted variant is drawn from chromosome 1 among variants with minor allele
    frequency 0.2 to 0.3, common enough to find."""
    rng = np.random.default_rng(seed)
    n = len(people)
    # Study codes go to people in a random order, so a code says nothing about the person (the
    # GDS policy's "random, unique codes"; HIPAA 164.514(c): not derived from their data).
    people = people.iloc[rng.permutation(n)]
    simulated = [
        simulate_chromosome(f"chr{c}", n, length, seed + c, min_maf)
        for c in range(1, chromosomes + 1)
    ]
    first = simulated[0]
    frequency = first.dosage.mean(axis=1) / 2
    minor = np.minimum(frequency, 1 - frequency)
    candidates = np.flatnonzero((minor >= 0.2) & (minor <= 0.3))
    causal = int(rng.choice(candidates))
    order = assign_genomes(first.dosage[causal], people[phenotype].to_numpy(), odds_ratio, rng)
    for chromosome in simulated:
        chromosome.dosage = chromosome.dosage[:, order]
        chromosome.haplotypes = chromosome.haplotypes[:, order, :]

    subjects = pd.DataFrame(
        {
            "person_id": people.index.to_numpy(),
            "sample_id": [f"SAMP-{i:05d}" for i in range(1, n + 1)],
            "sex": people["sex"].to_numpy(),
            "age": people["age"].to_numpy(),
            phenotype: people[phenotype].to_numpy(),
        },
        index=pd.Index([f"SUBJ-{i:05d}" for i in range(1, n + 1)], name="subject_id"),
    )
    dosage = first.dosage[causal]
    cases = subjects[phenotype].to_numpy() == 1
    truth = {
        "phenotype": phenotype,
        "people": n,
        "cases": int(cases.sum()),
        "chromosomes": chromosomes,
        "length": length,
        "min_maf": min_maf,
        "seed": seed,
        "odds_ratio_planted": odds_ratio,
        "variant": {
            "chromosome": first.name,
            "position": int(first.positions[causal]),
            "id": variant_ids(first)[causal],
            "alt_frequency": float(dosage.mean() / 2),
            "alt_frequency_cases": float(dosage[cases].mean() / 2),
            "alt_frequency_controls": float(dosage[~cases].mean() / 2),
        },
        "variants": int(sum(len(c.positions) for c in simulated)),
    }
    return Study(subjects, simulated, truth)


def variant_ids(chromosome: Chromosome) -> list[str]:
    return [
        f"{chromosome.name}:{p}:{r}:{a}"
        for p, r, a in zip(chromosome.positions, chromosome.ref, chromosome.alt, strict=True)
    ]


def write_vcf(path: Path, chromosome: Chromosome, length: int, samples: list[str]) -> None:
    codes = chromosome.haplotypes[:, :, 0] * 2 + chromosome.haplotypes[:, :, 1]
    with gzip.open(path, "wt") as f:
        f.write("##fileformat=VCFv4.2\n")
        f.write("##source=ehr-rwe-eln synthetic genotypes (msprime); not real people\n")
        f.write(f"##contig=<ID={chromosome.name},length={length}>\n")
        f.write('##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n')
        f.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t" + "\t".join(samples))
        f.write("\n")
        ids = variant_ids(chromosome)
        for v, position in enumerate(chromosome.positions):
            fixed = [chromosome.name, str(position), ids[v], chromosome.ref[v]]
            fixed += [chromosome.alt[v], ".", "PASS", ".", "GT"]
            f.write("\t".join(fixed) + "\t" + "\t".join(GENOTYPE_CODES[codes[v]]) + "\n")


def write_plink(path: Path, study: Study, phenotype: str) -> None:
    """One PLINK binary set for all chromosomes. Values count the alternate allele, which is
    allele 1 in the .bim; sex is 1 male, 2 female; the phenotype is 2 case, 1 control."""
    subjects = study.subjects
    to_bed(
        path,
        np.vstack([c.dosage for c in study.chromosomes]).T.astype(np.float32),
        properties={
            "fid": subjects["sample_id"].tolist(),
            "iid": subjects["sample_id"].tolist(),
            "sex": [1 if s == "male" else 2 for s in subjects["sex"]],
            "pheno": [2 if p == 1 else 1 for p in subjects[phenotype]],
            "chromosome": [c.name.removeprefix("chr") for c in study.chromosomes for _ in c.ref],
            "sid": [i for c in study.chromosomes for i in variant_ids(c)],
            "bp_position": np.concatenate([c.positions for c in study.chromosomes]),
            "allele_1": [a for c in study.chromosomes for a in c.alt],
            "allele_2": [r for c in study.chromosomes for r in c.ref],
        },
        count_A1=True,
    )


def write_study(out: Path, study: Study) -> None:
    out.mkdir(parents=True, exist_ok=True)
    subjects, phenotype = study.subjects, study.truth["phenotype"]
    samples = subjects["sample_id"].tolist()
    for chromosome in study.chromosomes:
        write_vcf(out / f"{chromosome.name}.vcf.gz", chromosome, study.truth["length"], samples)
    write_plink(out / "study.bed", study, phenotype)
    # From plain lists: pandas 3 strings convert to Polars only through pyarrow.
    table = pl.DataFrame(
        {"subject_id": subjects.index.tolist()}
        | {column: subjects[column].tolist() for column in subjects.columns}
    )
    table.select("subject_id", "sex", "age", phenotype).write_csv(
        out / "subject_phenotypes.tsv", separator="\t"
    )
    table.select("subject_id", "sample_id").write_csv(
        out / "subject_sample_mapping.tsv", separator="\t"
    )
    table.select(
        "sample_id", pl.lit("Whole blood").alias("body_site"), pl.lit("DNA").alias("analyte_type")
    ).write_csv(out / "sample_attributes.tsv", separator="\t")
    table.select("subject_id", "person_id").write_csv(out / "subject_registry.tsv", separator="\t")
    (out / "truth.json").write_text(json.dumps(study.truth, indent=2) + "\n")
