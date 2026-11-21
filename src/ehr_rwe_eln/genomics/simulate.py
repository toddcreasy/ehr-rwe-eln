"""Synthetic genotypes for OMOP persons, with population structure and a genetic effect planted
on a phenotype.

stdpopsim is a catalog of published population histories; it runs msprime, which simulates the
ancestry of a sample of people (the coalescent: tracing their DNA back through the populations
it came from, with recombination breaking it into segments), then drops mutations onto that
history. The result has what real genotype data has and random numbers do not: allele
frequencies with many rare variants, and linkage disequilibrium (LD), the correlation between
nearby variants that makes a real association show up as a peak of neighboring variants rather
than one spike. Each chromosome is simulated on its own, so chromosomes are independent, as
unlinked chromosomes are.

The history is stdpopsim's HomSap OutOfAfrica_3G09 (Gutenkunst et al. 2009): three populations,
YRI (Yoruba, West African), CEU (European), and CHB (Han Chinese, East Asian), split from one
African population, with migration between them. Their allele frequencies differ, which is
population structure: if ancestry is also linked to the phenotype, every variant whose
frequency differs between populations looks associated with it. That is what principal
components and mixed models in a GWAS correct. Each chromosome keeps its name's average
recombination rate, uniform along the simulated stretch; no genetic map is downloaded.

Each person's population follows the race recorded in OMOP (RACE_TO_POPULATION). That is a
simulation convention only: race is a social category, not genetic ancestry. It links ancestry
to the phenotype the way Synthea's rates differ by race, so the GWAS has confounding to correct.

The phenotype comes from OMOP and is not changed. The effect is planted by choosing which
simulated genome each person gets, among genomes of their own population: genomes carrying more
copies of one chosen variant are more likely to go to people with the phenotype (each copy
multiplies the odds by roughly the chosen odds ratio). Whole genomes move together, so LD around
the planted variant is intact.

Synthetic only: no real genome is used, and no simulated genome resembles a real person's.
"""

from dataclasses import dataclass

import numpy as np
import stdpopsim

SPECIES = "HomSap"
MODEL = "OutOfAfrica_3G09"
POPULATIONS = ("YRI", "CEU", "CHB")
# Races with no population in the model get one of the three at random.
RACE_TO_POPULATION = {"black": "YRI", "white": "CEU", "asian": "CHB"}


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
    population: np.ndarray  # each simulated genome's population name


def ancestry(race: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """A population for each person, from their recorded race (RACE_TO_POPULATION)."""
    drawn = rng.choice(POPULATIONS, len(race))
    return np.array([RACE_TO_POPULATION.get(r, d) for r, d in zip(race, drawn, strict=True)])


def simulate_chromosome(
    name: str, counts: dict[str, int], length: int, seed: int, min_maf: float
) -> Chromosome:
    """counts: people to simulate from each population. Only the first length bases of the
    named chromosome are simulated."""
    species = stdpopsim.get_species(SPECIES)
    model = species.get_demographic_model(MODEL)
    contig = species.get_contig(name, left=0, right=length, mutation_rate=model.mutation_rate)
    samples = {p: n for p, n in counts.items() if n}
    ts = stdpopsim.get_engine("msprime").simulate(model, contig, samples=samples, seed=seed)
    names = [ts.population(p).metadata["name"] for p in range(ts.num_populations)]
    population = np.array([names[p] for p in ts.individuals_population])
    people = ts.num_individuals
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
        name,
        np.array(positions),
        ref,
        alt,
        haplotypes.sum(axis=2, dtype=np.int8),
        haplotypes,
        population,
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
