"""Exomiser on the clinical panel: inputs for each study subject, and its gene ranks read back.

Exomiser (https://github.com/exomiser/Exomiser) scores each gene a person carries a variant in
twice: a variant score (how damaging and how rare the variant is, and what ClinVar says of it) and
a phenotype score (hiPhive: how well the person's HPO terms match what is known of the gene in
human disease and in mouse and zebrafish models), then combines them. It runs on AWS
(scripts/run_exomiser.py); this module only writes its inputs and reads its results.

Sources: REVEL, MVP, and AlphaMissense for missense pathogenicity; not SpliceAI (non-commercial
licence), CADD, or REMM. Every person runs with one analysis, in FULL mode so every gene is
scored, not only those that pass the filters.
"""

import csv
import io
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import yaml
from sklearn.metrics import roc_auc_score

PATHOGENICITY_SOURCES = ["REVEL", "MVP", "ALPHA_MISSENSE"]
FREQUENCY_SOURCES = ["UK10K"] + [
    f"GNOMAD_{kind}_{group}" for kind in ("E", "G") for group in ("AFR", "AMR", "EAS", "NFE", "SAS")
]
ANALYSIS = {
    "analysisMode": "FULL",
    "inheritanceModes": {
        "AUTOSOMAL_DOMINANT": 0.1,
        "AUTOSOMAL_RECESSIVE_HOM_ALT": 0.1,
        "AUTOSOMAL_RECESSIVE_COMP_HET": 2.0,
    },
    "frequencySources": FREQUENCY_SOURCES,
    "pathogenicitySources": PATHOGENICITY_SOURCES,
    "steps": [
        {"failedVariantFilter": {}},
        {"frequencyFilter": {"maxFrequency": 2.0}},
        {"pathogenicityFilter": {"keepNonPathogenic": True}},
        {"inheritanceFilter": {}},
        {"omimPrioritiser": {}},
        {"hiPhivePrioritiser": {}},
    ],
}
SEX = {"female": "FEMALE", "male": "MALE"}
SCORES = {
    "combined": "EXOMISER_GENE_COMBINED_SCORE",
    "phenotype": "EXOMISER_GENE_PHENO_SCORE",
    "variant": "EXOMISER_GENE_VARIANT_SCORE",
}


def vcf(sample: str, calls: list[tuple[str, str]]) -> str:
    """A single-sample VCF of one person's non-reference calls, in position order."""
    lines = [
        "##fileformat=VCFv4.2",
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">',
        "\t".join(
            ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT", sample]
        ),
    ]
    order = sorted(calls, key=lambda c: (c[0].split(":")[0], int(c[0].split(":")[1])))
    for variant_id, genotype in order:
        chromosome, position, ref, alt = variant_id.split(":")
        lines.append(
            "\t".join(
                [chromosome, position, variant_id, ref, alt, ".", "PASS", ".", "GT", genotype]
            )
        )
    return "\n".join(lines) + "\n"


def write_inputs(
    people: list[dict], genotypes: list[tuple[str, str, str]], release: str
) -> tuple[bytes, dict[str, int]]:
    """inputs.zip for the task: analysis.yml, then per person samples/<id>.yml (a v1 phenopacket
    with sex and HPO terms) and vcf/<id>.vcf, and batch.txt with one line per person. People
    with no non-reference call have nothing to rank and are left out.

    people: dicts with sample_id, sex, hpo_ids. genotypes: (variant id, sample id, genotype)."""
    calls: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for variant_id, sample, genotype in genotypes:
        calls[sample].append((variant_id, genotype))
    buffer, batch = io.BytesIO(), []
    counts = {"people": 0, "no_calls": 0, "no_hpo_terms": 0}
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("analysis.yml", yaml.safe_dump(ANALYSIS, sort_keys=False))
        for person in people:
            sample = person["sample_id"]
            if not calls[sample]:
                counts["no_calls"] += 1
                continue
            counts["people"] += 1
            counts["no_hpo_terms"] += not person["hpo_ids"]
            # A v1 phenopacket, its fields at the top level as in Exomiser's examples.
            phenopacket = {
                "id": sample,
                "subject": {"id": sample, "sex": SEX.get(person["sex"], "UNKNOWN_SEX")},
                "phenotypicFeatures": [{"type": {"id": t}} for t in person["hpo_ids"]],
                "metaData": {
                    "createdBy": "ehr-rwe-eln",
                    "resources": [
                        {
                            "id": "hp",
                            "name": "human phenotype ontology",
                            "namespacePrefix": "HP",
                            "version": person["hpo_release"],
                        }
                    ],
                    "phenopacketSchemaVersion": "1.0",
                },
            }
            z.writestr(f"samples/{sample}.yml", yaml.safe_dump(phenopacket, sort_keys=False))
            z.writestr(f"vcf/{sample}.vcf", vcf(sample, calls[sample]))
            batch.append(
                f"--analysis analysis.yml --sample samples/{sample}.yml --vcf vcf/{sample}.vcf"
                f" --assembly hg38 --output-format TSV_GENE,TSV_VARIANT"
                f" --output-filename {sample} --output-directory results"
            )
        z.writestr("batch.txt", "\n".join(batch) + "\n")
        z.writestr("release.txt", release + "\n")
    return buffer.getvalue(), counts


def read_gene_results(results: zipfile.ZipFile) -> dict[str, dict[str, dict[str, float]]]:
    """{sample: {gene: {combined, phenotype, variant}}} from each <sample>.genes.tsv. A gene
    appears once per mode of inheritance; its best combined score is kept."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for name in results.namelist():
        if not name.endswith(".genes.tsv"):
            continue
        sample = name.removesuffix(".genes.tsv")
        genes: dict[str, dict[str, float]] = {}
        with results.open(name) as f:
            for row in csv.DictReader(io.TextIOWrapper(f), delimiter="\t"):
                scores = {k: float(row[c]) for k, c in SCORES.items()}
                gene = row["GENE_SYMBOL"]
                if gene not in genes or scores["combined"] > genes[gene]["combined"]:
                    genes[gene] = scores
        out[sample] = genes
    return out


def rank(genes: dict[str, dict[str, float]], gene: str, score: str) -> int | None:
    """The gene's rank among the person's genes by one score (1 is first; ties share the better
    rank), or None if Exomiser did not score it."""
    if gene not in genes:
        return None
    return 1 + sum(s[score] > genes[gene][score] for s in genes.values())


def check_planted(
    results: dict[str, dict[str, dict[str, float]]],
    planted: dict[str, set[str]],
) -> dict[str, dict[str, int]]:
    """For each pathogenic carrier (sample -> the planted genes; one person can carry two), how
    often each score ranks a planted gene first among the genes the person carries a variant in."""
    out = {}
    for score in SCORES:
        ranks = []
        for s, genes in planted.items():
            found = [r for g in genes if (r := rank(results.get(s, {}), g, score)) is not None]
            ranks.append(min(found) if found else None)
        out[score] = {
            "carriers": len(ranks),
            "first": sum(r == 1 for r in ranks),
            "not_scored": sum(r is None for r in ranks),
        }
    return out


def phenotype_auc(
    results: dict[str, dict[str, dict[str, float]]],
    planted: dict[str, set[str]],
    resnik: dict[str, dict[str, float]],
    rng: np.random.Generator,
    n: int = 1000,
) -> dict[str, dict]:
    """Per gene, among the people Exomiser scored for it (everyone with a panel variant there),
    how well each phenotype score ranks the pathogenic carriers above the rest: AUC for
    Exomiser's hiPhive score and for our Resnik score (curation/phenotype.py) on the same
    people, each with a 95% bootstrap interval (resample people, keep resamples with both
    groups). resnik: {sample: {gene: score}}."""
    out = {}
    for gene in sorted({g for genes in results.values() for g in genes}):
        people = sorted(s for s, genes in results.items() if gene in genes)
        y = np.array([gene in planted.get(s, set()) for s in people])
        if not 0 < y.sum() < len(y):
            continue
        scores = {
            "exomiser": np.array([results[s][gene]["phenotype"] for s in people]),
            "resnik": np.array([resnik[s][gene] for s in people]),
        }
        draws = {k: [] for k in scores}
        for _ in range(n):
            i = rng.integers(0, len(y), len(y))
            if 0 < y[i].sum() < len(i):
                for k, score in scores.items():
                    draws[k].append(roc_auc_score(y[i], score[i]))
        row = {"people": len(people), "carriers": int(y.sum())}
        for k, score in scores.items():
            low, high = np.percentile(draws[k], [2.5, 97.5])
            row[k] = {
                "auc": round(float(roc_auc_score(y, score)), 3),
                "ci95": [round(float(low), 3), round(float(high), 3)],
            }
        out[gene] = row
    return out


def variant_context(
    results: dict[str, dict[str, dict[str, float]]],
    carriers: dict[str, list[str]],
    gene_of: dict[str, str],
    auc: dict[str, float],
) -> list[dict]:
    """For the curator, per panel variant: each carrier's phenotype rank for the variant's gene
    and how many genes that carrier has, best rank first, with the gene's study-wide AUC.
    Carriers come from the genotypes (variant -> samples), not the answer key; only people
    Exomiser scored count. No sample IDs leave this function."""
    out = []
    for variant_id, samples in sorted(carriers.items()):
        gene = gene_of[variant_id]
        found = sorted(
            (r, len(results[s]))
            for s in samples
            if s in results and (r := rank(results[s], gene, "phenotype")) is not None
        )
        out.append(
            {
                "variant_id": variant_id,
                "gene": gene,
                "subjects": len(found),
                "ranks": [r for r, _ in found],
                "genes": [n for _, n in found],
                "auc": auc.get(gene),
            }
        )
    return out


def read_results_zip(path: Path) -> dict[str, dict[str, dict[str, float]]]:
    with zipfile.ZipFile(path) as z:
        return read_gene_results(z)
