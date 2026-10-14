"""Synthetic genotypes for OMOP persons, with a genetic effect planted on a phenotype.

msprime simulates the ancestry of a sample of people (the coalescent: tracing their DNA back
through a population of fixed size, with recombination breaking it into segments), then drops
mutations onto that history. The result has what real genotype data has and random numbers do
not: allele frequencies with many rare variants, and linkage disequilibrium (LD), the
correlation between nearby variants that makes a real association show up as a peak of
neighboring variants rather than one spike. Each chromosome is simulated on its own, so
chromosomes are independent, as unlinked chromosomes are.

The phenotype comes from OMOP and is not changed. The effect is planted by choosing which
simulated genome each person gets: genomes carrying more copies of one chosen variant are
more likely to go to people with the phenotype (each copy multiplies the odds by roughly the
chosen odds ratio). Whole genomes move together, so LD around the planted variant is intact.

Synthetic only: no real genome is used, and no simulated genome resembles a real person's.
"""

from dataclasses import dataclass

import msprime
import numpy as np

# Human-like defaults: effective population size and per-base rates per generation.
POPULATION_SIZE = 10_000
RECOMBINATION_RATE = 1e-8
MUTATION_RATE = 1e-8


@dataclass
class Chromosome:
    name: str
    positions: np.ndarray  # 1-based base pair positions
    ref: list[str]
    alt: list[str]
    # Alternate allele count per person, 0 to 2: variants by people, in simulated-genome order.
    dosage: np.ndarray
    # Phased haplotypes as (variants, people, 2), for the VCF.
    haplotypes: np.ndarray


def simulate_chromosome(
    name: str, people: int, length: int, seed: int, min_maf: float
) -> Chromosome:
    ancestry = msprime.sim_ancestry(
        samples=people,
        population_size=POPULATION_SIZE,
        sequence_length=length,
        recombination_rate=RECOMBINATION_RATE,
        random_seed=seed,
    )
    ts = msprime.sim_mutations(ancestry, rate=MUTATION_RATE, random_seed=seed)
    positions, ref, alt, rows = [], [], [], []
    for variant in ts.variants():
        # Two alleles only, as on a genotyping array; the rare multi-allelic site is dropped.
        if len(variant.alleles) != 2 or variant.alleles[1] is None:
            continue
        haplotypes = variant.genotypes.reshape(people, 2)
        frequency = haplotypes.mean()
        if min(frequency, 1 - frequency) < min_maf:
            continue
        positions.append(int(variant.site.position) + 1)
        ref.append(variant.alleles[0])
        alt.append(variant.alleles[1])
        rows.append(haplotypes.astype(np.int8))
    haplotypes = np.stack(rows)
    return Chromosome(
        name, np.array(positions), ref, alt, haplotypes.sum(axis=2, dtype=np.int8), haplotypes
    )


def assign_genomes(
    dosage: np.ndarray, phenotype: np.ndarray, odds_ratio: float, rng: np.random.Generator
) -> np.ndarray:
    """An order of the simulated genomes, one per person, that plants the effect: people with
    the phenotype draw genomes with weight odds_ratio ** dosage (dosage at the planted
    variant), without replacement; everyone else gets the rest at random."""
    cases = np.flatnonzero(phenotype == 1)
    weights = np.power(odds_ratio, dosage.astype(float))
    to_cases = rng.choice(len(dosage), size=len(cases), replace=False, p=weights / weights.sum())
    rest = np.setdiff1d(np.arange(len(dosage)), to_cases)
    order = np.empty(len(dosage), dtype=np.int64)
    order[cases] = to_cases
    order[np.flatnonzero(phenotype != 1)] = rng.permutation(rest)
    return order
