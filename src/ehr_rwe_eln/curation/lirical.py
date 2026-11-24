"""LIRICAL on the clinical panel: its disease rankings read back as gene scores.

LIRICAL (https://github.com/TheJacksonLaboratory/LIRICAL) ranks diseases by how well a person's
HPO terms fit each one, as a likelihood ratio. It runs phenotype only (scripts/run_lirical.py), so
it ranks diseases, not genes. Each OMIM disease's genes come from HPO's genes_to_phenotype.txt at
the release subject_hpo.tsv uses; HPO takes them from NCBI's mim2gene_medgen, the file LIRICAL
reads, which NCBI does not archive.

A gene's score for a person is the rank of its best disease in the person's list (1 is first, of
8,525). Not the compositeLR (log10 of the likelihood ratio) itself: it adds one term per HPO term,
and each term a disease does not explain lowers it, so a person with more terms scores lower for
every disease, and carriers have more terms (median 12 against 10). The rank compares across
people; within one person it orders genes as compositeLR does.
"""

import csv
import io
import zipfile
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score


def read_disease_genes(path: Path, genes: set[str]) -> dict[str, set[str]]:
    """{OMIM disease: its genes among `genes`} from HPO's genes_to_phenotype.txt."""
    out: dict[str, set[str]] = {}
    with path.open() as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row["gene_symbol"] in genes and row["disease_id"].startswith("OMIM:"):
                out.setdefault(row["disease_id"], set()).add(row["gene_symbol"])
    return out


def read_ranks(text: str, disease_genes: dict[str, set[str]]) -> dict[str, int]:
    """{gene: rank of its best disease} from one person's LIRICAL TSV (ranks print as "4,677")."""
    rows = csv.DictReader(
        (line for line in text.splitlines() if not line.startswith("!")), delimiter="\t"
    )
    out: dict[str, int] = {}
    for row in rows:
        r = int(row["rank"].replace(",", ""))
        for gene in disease_genes.get(row["diseaseCurie"], ()):
            out[gene] = min(out.get(gene, r), r)
    return out


def read_results(
    results: zipfile.ZipFile, disease_genes: dict[str, set[str]]
) -> dict[str, dict[str, int]]:
    """{sample: {gene: rank of its best disease}} from each <sample>.tsv."""
    return {
        name.removesuffix(".tsv"): read_ranks(
            io.TextIOWrapper(results.open(name)).read(), disease_genes
        )
        for name in results.namelist()
        if name.endswith(".tsv")
    }


def read_results_zip(path: Path, disease_genes: dict[str, set[str]]) -> dict[str, dict[str, int]]:
    with zipfile.ZipFile(path) as z:
        return read_results(z, disease_genes)


def rank(ranks: dict[str, int], gene: str, among: set[str]) -> int | None:
    """The gene's rank among `among` (the genes the person has a panel variant in; 1 is first,
    ties share the better rank), or None if LIRICAL ranked none of its diseases."""
    if gene not in ranks:
        return None
    return 1 + sum(g in ranks and ranks[g] < ranks[gene] for g in among)


def check_planted(
    results: dict[str, dict[str, int]],
    planted: dict[str, set[str]],
    genes_of: dict[str, set[str]],
) -> dict[str, float | int]:
    """For each pathogenic carrier (sample -> planted genes), whether a planted gene ranks first
    among the genes the person has a panel variant in; `random` is how many picking one of those
    genes at random would put first, on average."""
    ranks, chance = [], 0.0
    for s, genes in planted.items():
        among = genes_of.get(s, set()) | genes
        found = [r for g in genes if (r := rank(results.get(s, {}), g, among)) is not None]
        ranks.append(min(found) if found else None)
        chance += len(genes) / len(among)
    return {
        "carriers": len(ranks),
        "first": sum(r == 1 for r in ranks),
        "not_scored": sum(r is None for r in ranks),
        "random": round(chance, 1),
    }


def gene_auc(
    results: dict[str, dict[str, int]],
    planted: dict[str, set[str]],
    genes_of: dict[str, set[str]],
    rng: np.random.Generator,
    n: int = 1000,
) -> dict[str, dict]:
    """Per gene, among the people with a panel variant in it, how well the rank of the gene's best
    disease picks out the pathogenic carriers: AUC with a 95% bootstrap interval (resample people,
    keep resamples with both groups). A gene none of whose diseases LIRICAL ranked ranks last."""
    out = {}
    for gene in sorted({g for genes in genes_of.values() for g in genes}):
        people = sorted(s for s, genes in genes_of.items() if gene in genes and s in results)
        y = np.array([gene in planted.get(s, set()) for s in people])
        if not 0 < y.sum() < len(y):
            continue
        score = -np.array([results[s].get(gene, 10**9) for s in people])
        draws = []
        for _ in range(n):
            i = rng.integers(0, len(y), len(y))
            if 0 < y[i].sum() < len(i):
                draws.append(roc_auc_score(y[i], score[i]))
        low, high = np.percentile(draws, [2.5, 97.5])
        out[gene] = {
            "people": len(people),
            "carriers": int(y.sum()),
            "auc": round(float(roc_auc_score(y, score)), 3),
            "ci95": [round(float(low), 3), round(float(high), 3)],
        }
    return out
