"""A clinical sequencing panel for the genomics study: real ClinVar variants at their real
GRCh38 positions, planted in the study's synthetic people.

The array genotypes from simulate.py sit on simulated chromosomes with made-up coordinates,
which suits a GWAS but not curation: a curator looks a variant up by its real position. So the
panel is a second VCF for the same samples, the way a biobank pairs array genotypes with
clinical sequencing of selected genes. Three kinds of variant are planted per gene:

- pathogenic: carriers drawn at a higher rate among people whose OMOP record has the gene's
  condition (panel.yaml sets both rates); each carrier gets one variant, heterozygous.
- benign: common in gnomAD, so drawn at their gnomAD frequency in everyone (Hardy-Weinberg:
  each of a person's two copies carries it independently).
- uncertain: ClinVar's "uncertain significance", rare, carried at a fixed rate by anyone.

The VCF carries positions, alleles, and genotypes only. ClinVar's classification, the role
each variant was planted in, and every carrier are in panel_truth.json, the answer key, so
anything that curates the panel has to work the classification out for itself.
"""

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import yaml
from pydantic import Field

from ehr_rwe_eln.cohort.spec import Strict
from ehr_rwe_eln.genomics.gnomad import gnomad_id

SPEC = Path(__file__).parent / "panel.yaml"
# GRCh38 lengths of the chromosomes the panel's genes are on, for the VCF header.
CONTIG_LENGTHS = {
    "chr2": 242_193_529,
    "chr3": 198_295_559,
    "chr5": 181_538_259,
    "chr13": 114_364_328,
    "chr17": 83_257_441,
    "chr19": 58_617_616,
}
GENOTYPES = np.array(["0/0", "0/1", "1/1"])
# Short variants only: at 50 bp or more a variant counts as structural, which panels call
# and curate separately.
SHORT = 50


class Condition(Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    concept_id: int  # an OMOP condition concept; its descendants count too
    genes: list[str] = Field(min_length=1)
    carriers_with: float = Field(ge=0, le=1)
    carriers_without: float = Field(ge=0, le=1)


class PanelSpec(Strict):
    clinvar_release: str = Field(pattern=r"^\d{8}$")
    gnomad_dataset: str
    seed: int
    pathogenic_per_gene: int = Field(ge=1)
    benign_per_gene: int = Field(ge=0)
    uncertain_per_gene: int = Field(ge=0)
    min_stars: int = Field(ge=0, le=4)
    benign_min_frequency: float = Field(gt=0, lt=1)
    uncertain_carriers: float = Field(ge=0, le=1)
    conditions: list[Condition] = Field(min_length=1)

    @property
    def genes(self) -> set[str]:
        return {g for c in self.conditions for g in c.genes}


def load_panel_spec(path: Path = SPEC) -> PanelSpec:
    return PanelSpec.model_validate(yaml.safe_load(path.read_text()))


def _pick(rows: pl.DataFrame, n: int, rng: np.random.Generator) -> pl.DataFrame:
    rows = rows.sort("variation_id")
    return rows[np.sort(rng.permutation(len(rows))[:n]).tolist()] if len(rows) > n else rows


def candidates(clinvar: pl.DataFrame, spec: PanelSpec, rng: np.random.Generator) -> pl.DataFrame:
    """Variants to look up in gnomAD, with the role each would be planted in. Benign ones are
    pre-selected on ClinVar's older frequencies (ExAC, 1000 Genomes), four per slot, so gnomAD
    is asked about a few dozen variants rather than thousands."""
    trusted = clinvar.filter(
        (pl.col("stars") >= spec.min_stars)
        & pl.col("chromosome").is_in(list(CONTIG_LENGTHS))
        & (pl.max_horizontal(pl.col("ref").str.len_chars(), pl.col("alt").str.len_chars()) < SHORT)
    )
    common = pl.max_horizontal(pl.col("af_exac").fill_nan(0), pl.col("af_tgp").fill_nan(0))
    picked = []
    for gene in sorted(spec.genes):
        rows = trusted.filter(pl.col("gene") == gene)
        for role, rule, n in [
            ("pathogenic", pl.col("classification") == "Pathogenic", spec.pathogenic_per_gene),
            (
                "uncertain",
                pl.col("classification") == "Uncertain_significance",
                spec.uncertain_per_gene,
            ),
            (
                "benign",
                (pl.col("classification") == "Benign") & (common >= spec.benign_min_frequency),
                4 * spec.benign_per_gene,
            ),
        ]:
            chosen = _pick(rows.filter(rule), n, rng)
            if role == "pathogenic" and len(chosen) < n:
                raise ValueError(f"{gene}: only {len(chosen)} pathogenic variants qualify")
            picked.append(chosen.with_columns(pl.lit(role).alias("role")))
    out = pl.concat(picked)
    return out.with_columns(
        pl.struct("chromosome", "position", "ref", "alt")
        .map_elements(lambda r: gnomad_id(**r), return_dtype=pl.String)
        .alias("gnomad_id")
    )


def finalize(
    candidates: pl.DataFrame, frequencies: dict[str, dict | None], spec: PanelSpec
) -> pl.DataFrame:
    """Attach gnomAD frequencies; keep the first benign_per_gene benign candidates per gene
    that gnomAD confirms as common. Sorted by chromosome and position, as a VCF is."""
    af = [(frequencies.get(i) or {}).get("af") for i in candidates["gnomad_id"]]
    out = candidates.with_columns(pl.Series("gnomad_af", af, dtype=pl.Float64))
    benign = (
        out.filter(
            (pl.col("role") == "benign") & (pl.col("gnomad_af") >= spec.benign_min_frequency)
        )
        .group_by("gene", maintain_order=True)
        .head(spec.benign_per_gene)
        .select(out.columns)
    )
    out = pl.concat([out.filter(pl.col("role") != "benign"), benign])
    order = {c: i for i, c in enumerate(CONTIG_LENGTHS)}
    return out.sort(pl.col("chromosome").replace_strict(order), "position")


def genotype_panel(
    flags: pd.DataFrame, variants: pl.DataFrame, spec: PanelSpec, rng: np.random.Generator
) -> np.ndarray:
    """Alternate allele counts, variants by people. flags: one row per person in study order,
    a 0/1 column per condition in the spec."""
    n = len(flags)
    dosage = np.zeros((len(variants), n), dtype=np.int8)
    roles, genes = variants["role"].to_list(), variants["gene"].to_list()
    for v, role in enumerate(roles):
        if role == "benign":
            dosage[v] = rng.binomial(2, variants["gnomad_af"][v], n)
        elif role == "uncertain":
            dosage[v] = rng.random(n) < spec.uncertain_carriers
    for condition in spec.conditions:
        has = flags[condition.name].to_numpy() == 1
        rate = np.where(has, condition.carriers_with, condition.carriers_without)
        carriers = np.flatnonzero(rng.random(n) < rate)
        pool = [
            v
            for v, (r, g) in enumerate(zip(roles, genes, strict=True))
            if r == "pathogenic" and g in condition.genes
        ]
        dosage[rng.choice(pool, len(carriers)), carriers] = 1
    return dosage


def panel_truth(
    variants: pl.DataFrame,
    dosage: np.ndarray,
    subjects: list[str],
    flags: pd.DataFrame,
    spec: PanelSpec,
) -> dict:
    """The answer key: each variant's ClinVar record and gnomAD frequency, how many carry it,
    and who carries each pathogenic and uncertain variant."""
    out = []
    condition_of = {g: c for c in spec.conditions for g in c.genes}
    for v, row in enumerate(variants.iter_rows(named=True)):
        carrying = np.flatnonzero(dosage[v] > 0)
        condition = condition_of[row["gene"]]
        record = {
            "id": f"{row['chromosome']}:{row['position']}:{row['ref']}:{row['alt']}",
            "gene": row["gene"],
            "role": row["role"],
            "condition": condition.name,
            "clinvar": {
                "variation_id": row["variation_id"],
                "classification": row["classification"],
                "review_status": row["review_status"],
                "stars": row["stars"],
                "consequence": row["consequence"],
            },
            "gnomad_af": row["gnomad_af"],
            "carriers": int(len(carrying)),
            "carriers_with_condition": int(flags[condition.name].to_numpy()[carrying].sum()),
            "alt_frequency": float(dosage[v].mean() / 2),
        }
        if row["role"] != "benign":
            record["carrier_subjects"] = [subjects[i] for i in carrying]
        out.append(record)
    by_condition = {}
    for condition in spec.conditions:
        has = flags[condition.name].to_numpy() == 1
        pathogenic = [
            v
            for v, r in enumerate(out)
            if r["role"] == "pathogenic" and r["condition"] == condition.name
        ]
        carrier = dosage[pathogenic].sum(axis=0) > 0
        by_condition[condition.name] = {
            "people_with": int(has.sum()),
            "carriers_with": int((carrier & has).sum()),
            "carriers_without": int((carrier & ~has).sum()),
        }
    return {
        "clinvar_release": spec.clinvar_release,
        "gnomad_dataset": spec.gnomad_dataset,
        "seed": spec.seed,
        "people": len(subjects),
        "conditions": by_condition,
        "variants": out,
    }


def write_panel_vcf(
    path: Path, variants: pl.DataFrame, dosage: np.ndarray, samples: list[str]
) -> None:
    contigs = list(dict.fromkeys(variants["chromosome"]))
    with gzip.open(path, "wt") as f:
        f.write("##fileformat=VCFv4.2\n")
        f.write(
            "##source=ehr-rwe-eln synthetic clinical panel;"
            " real ClinVar variants, not real people\n"
        )
        f.write("##reference=GRCh38\n")
        for contig in contigs:
            f.write(f"##contig=<ID={contig},length={CONTIG_LENGTHS[contig]},assembly=GRCh38>\n")
        f.write('##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n')
        f.write(
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t" + "\t".join(samples) + "\n"
        )
        for v, row in enumerate(variants.iter_rows(named=True)):
            variant_id = f"{row['chromosome']}:{row['position']}:{row['ref']}:{row['alt']}"
            fixed = [row["chromosome"], str(row["position"]), variant_id, row["ref"], row["alt"]]
            fixed += [".", "PASS", ".", "GT"]
            f.write("\t".join(fixed) + "\t" + "\t".join(GENOTYPES[dosage[v]]) + "\n")


def read_panel_carriers(path: Path) -> dict[str, list[str]]:
    """The samples carrying each variant in a panel VCF (any genotype other than 0/0), by the
    variant's ID column."""
    out = {}
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.startswith("##"):
                continue
            cols = line.rstrip("\n").split("\t")
            if line.startswith("#"):
                samples = cols[9:]
                continue
            out[cols[2]] = [s for s, gt in zip(samples, cols[9:], strict=True) if gt != "0/0"]
    return out


def write_panel(
    out: Path, variants: pl.DataFrame, dosage: np.ndarray, samples: list[str], truth: dict
) -> None:
    write_panel_vcf(out / "panel.vcf.gz", variants, dosage, samples)
    (out / "panel_truth.json").write_text(json.dumps(truth, indent=2) + "\n")
