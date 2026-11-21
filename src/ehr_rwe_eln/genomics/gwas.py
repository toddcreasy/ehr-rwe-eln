"""A genome-wide association study (GWAS) on a study written by study.py, read back from its
PLINK set and tables the way an analyst would receive them.

Each variant is tested for association with the phenotype, adjusted for age and sex, under an
additive model (each copy of the alternate allele multiplies the odds by the same amount).
Fitting a logistic regression for every variant is slow, so the test is the score test: fit
the model once without any variant, then ask, for all variants at once with matrix
arithmetic, how much the fit would improve by adding each one. Large GWAS tools work the same
way. The lead variant of each hit is then fit in full for its odds ratio.

- Genome-wide significance: p below 5e-8, the field's threshold for about a million
  independent tests.
- Loci: significant variants within 500 kb of a stronger one belong to its locus (LD makes
  neighbors of a true hit significant too). One locus per real signal is the goal.
- Genomic inflation (lambda): the median test statistic over its expected value under no
  association, on common variants (frequency 5% or more, where the test's chi-squared
  approximation holds best). Near 1.0 means the tests are calibrated; well above means
  something such as population structure is inflating every test. A strong real signal also
  lifts its whole chromosome through weak long-range LD, so the truth check reads lambda on the
  chromosomes without the planted variant.
- Calibration: on a small simulated genome lambda is noisy, because LD leaves a few thousand
  variants behaving like a few dozen independent tests. On 5,000 people and two 3 Mb
  chromosomes, lambda with no effect has a standard deviation of about 0.10. So lambda is read
  against its own null: the phenotype is redrawn NULL_RUNS times from the age-and-sex model
  alone, the score test rerun, and the observed lambda placed among those null lambdas. A
  percentile near 0 or 100 on every rebuild points at the pipeline; one low draw does not.
- Population structure: when allele frequencies and the phenotype both differ by ancestry, every
  variant that differs by ancestry looks associated. Principal components (PCs) of the genotypes
  recover ancestry (the first two separate the study's three populations), and adding them as
  covariates removes that confounding. PLINK 2 computes them in the gwas task
  (docker/gwas_task.py), which also runs REGENIE, the mixed-model test that is the primary GWAS;
  this score test with the same PCs is the readable check on it, and its null runs calibrate both.
"""

from pathlib import Path

import numpy as np
import polars as pl
import statsmodels.api as sm
from bed_reader import open_bed
from scipy.stats import chi2
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.model_selection import cross_val_score

SIGNIFICANCE = 5e-8
LOCUS_WINDOW = 500_000
CHI2_MEDIAN = chi2.ppf(0.5, 1)
CHUNK = 2000
COMMON = 0.05
NULL_RUNS = 100


def load(directory: Path) -> tuple[np.ndarray, pl.DataFrame, pl.DataFrame]:
    """Genotypes (people by variants, alternate allele counts), variants, and covariates with
    the phenotype, in the PLINK file's sample order."""
    with open_bed(directory / "study.bed", count_A1=True) as bed:
        genotypes = bed.read(dtype=np.float32)
        variants = pl.DataFrame(
            {
                "id": bed.sid,
                "chromosome": ["chr" + c for c in bed.chromosome],
                "position": bed.bp_position.astype(np.int64),
            }
        )
        samples = list(bed.iid)
    phenotypes = pl.read_csv(directory / "subject_phenotypes.tsv", separator="\t")
    mapping = pl.read_csv(directory / "subject_sample_mapping.tsv", separator="\t")
    people = (
        pl.DataFrame({"sample_id": samples})
        .join(mapping, on="sample_id", how="left", maintain_order="left")
        .join(phenotypes, on="subject_id", how="left", maintain_order="left")
    )
    return genotypes, variants, people


def read_pcs(path: Path, samples: list[str]) -> np.ndarray:
    """PLINK 2's .eigenvec (people by PCs), in the given sample order."""
    pcs = pl.read_csv(path, separator="\t").rename(lambda c: c.lstrip("#"))
    ordered = pl.DataFrame({"IID": samples}).join(pcs, on="IID", how="left", maintain_order="left")
    return ordered.select(pl.col("^PC\\d+$")).to_numpy()


def pc_ancestry_agreement(pcs: np.ndarray, ancestry: np.ndarray) -> float:
    """How much of each person's simulated population the PCs carry: the cross-validated
    accuracy (5 folds, each person predicted by a fit on the others) of linear discriminant
    analysis from the PCs to the population. PLINK computed the PCs without the labels; which
    PCs hold ancestry varies (LD can take PC2 on a small genome), so all of them are used."""
    return float(cross_val_score(LinearDiscriminantAnalysis(), pcs, ancestry, cv=5).mean())


def score_test(genotypes: np.ndarray, y: np.ndarray, covariates: np.ndarray) -> np.ndarray:
    """The score statistic (chi-squared, 1 degree of freedom) for each variant, from one
    logistic fit of y on the covariates."""
    null = sm.Logit(y, covariates).fit(disp=0)
    mu = null.predict(covariates)
    w = mu * (1 - mu)
    residual = y - mu
    information = np.linalg.inv(covariates.T @ (covariates * w[:, None]))
    statistics = np.empty(genotypes.shape[1])
    for start in range(0, genotypes.shape[1], CHUNK):
        g = genotypes[:, start : start + CHUNK].astype(np.float64)
        u = g.T @ residual
        cross = covariates.T @ (g * w[:, None])
        variance = (g * g * w[:, None]).sum(axis=0) - (cross * (information @ cross)).sum(axis=0)
        statistics[start : start + CHUNK] = u**2 / variance
    return statistics


def null_statistics(
    genotypes: np.ndarray, y: np.ndarray, covariates: np.ndarray, runs: int, seed: int = 0
) -> np.ndarray:
    """Score statistics (runs by variants) for phenotypes with no genetic effect: each run
    draws every person's phenotype from the fitted covariate-only model, so only chance links
    it to any variant."""
    mu = sm.Logit(y, covariates).fit(disp=0).predict(covariates)
    rng = np.random.default_rng(seed)
    return np.stack(
        [
            score_test(genotypes, (rng.random(len(y)) < mu).astype(float), covariates)
            for _ in range(runs)
        ]
    )


def calibration(observed: np.ndarray, null: np.ndarray) -> dict:
    """Lambda on these variants, and where it falls among the null runs' lambdas on the same
    variants: the share of null lambdas at or below it, and their middle 95%."""
    value = float(np.median(observed) / CHI2_MEDIAN)
    nulls = np.median(null, axis=1) / CHI2_MEDIAN
    return {
        "lambda": value,
        "percentile": float(100 * np.mean(nulls <= value)),
        "null_range": [float(np.percentile(nulls, 2.5)), float(np.percentile(nulls, 97.5))],
    }


def loci(results: pl.DataFrame) -> list[dict]:
    """Group significant variants into loci around their strongest one."""
    significant = results.filter(pl.col("p") < SIGNIFICANCE).sort("p").to_dicts()
    out = []
    for variant in significant:
        if any(
            variant["chromosome"] == lead["chromosome"]
            and abs(variant["position"] - lead["position"]) <= LOCUS_WINDOW
            for lead in out
        ):
            continue
        out.append(variant)
    return out


def lead_fit(genotype: np.ndarray, y: np.ndarray, covariates: np.ndarray) -> dict:
    fit = sm.Logit(y, np.column_stack([covariates, genotype])).fit(disp=0)
    low, high = np.exp(fit.conf_int()[-1])
    return {"odds_ratio": float(np.exp(fit.params[-1])), "ci": [float(low), float(high)]}


def inflation(results: pl.DataFrame) -> float:
    return float(results["chi2"].median() / CHI2_MEDIAN)


def run_gwas(
    directory: Path, phenotype: str, null_runs: int = NULL_RUNS, pcs: Path | None = None
) -> tuple[pl.DataFrame, dict]:
    """pcs: a PLINK 2 .eigenvec whose PCs join age and sex as covariates."""
    genotypes, variants, people = load(directory)
    y = people[phenotype].to_numpy().astype(float)
    age = people["age"].to_numpy().astype(float)
    male = (people["sex"] == "male").to_numpy().astype(float)
    covariates = np.column_stack([np.ones(len(people)), (age - age.mean()) / age.std(), male])
    if pcs is not None:
        covariates = np.column_stack([covariates, read_pcs(pcs, people["sample_id"].to_list())])
    statistics = score_test(genotypes, y, covariates)
    null = null_statistics(genotypes, y, covariates, null_runs)
    frequency = genotypes.mean(axis=0) / 2
    is_common = np.minimum(frequency, 1 - frequency) >= COMMON
    chromosome = variants["chromosome"].to_numpy()
    results = variants.with_columns(
        pl.Series("alt_frequency", frequency),
        pl.Series("chi2", statistics),
        pl.Series("p", chi2.sf(statistics, 1)),
    )
    common = results.filter(
        pl.min_horizontal(pl.col("alt_frequency"), 1 - pl.col("alt_frequency")) >= COMMON
    )
    found = loci(results)
    index = {v: i for i, v in enumerate(variants["id"])}
    for locus in found:
        locus.update(lead_fit(genotypes[:, index[locus["id"]]], y, covariates))
    summary = {
        "variants": len(results),
        "people": len(people),
        "genomic_inflation": inflation(common),
        "genomic_inflation_by_chromosome": {
            name: inflation(group)
            for (name,), group in common.group_by("chromosome", maintain_order=True)
        },
        "calibration_by_chromosome": {
            name: calibration(statistics[mask], null[:, mask])
            for name in dict.fromkeys(chromosome)
            if (mask := is_common & (chromosome == name)).any()
        },
        "significant_variants": int((results["p"] < SIGNIFICANCE).sum()),
        "loci": found,
        # Runs by variants, aligned with results; check_truth reads it for its own variants.
        "null_statistics": null,
    }
    return results, summary


def read_regenie(path: Path) -> pl.DataFrame:
    """REGENIE step 2's results in run_gwas's shape: id, chromosome, position, alt_frequency,
    chi2, p. ALLELE1 is REGENIE's tested allele; alt_frequency is turned to the alternate allele
    (the last field of the ID) either way."""
    raw = pl.read_csv(path, separator=" ")
    alt = pl.col("ID").str.split(":").list.last()
    return raw.select(
        pl.col("ID").alias("id"),
        ("chr" + pl.col("CHROM").cast(pl.String)).alias("chromosome"),
        pl.col("GENPOS").cast(pl.Int64).alias("position"),
        pl.when(pl.col("ALLELE1") == alt)
        .then(pl.col("A1FREQ"))
        .otherwise(1 - pl.col("A1FREQ"))
        .alias("alt_frequency"),
        pl.col("CHISQ").alias("chi2"),
        (10 ** -pl.col("LOG10P")).alias("p"),
    )


def check_truth(results: pl.DataFrame, summary: dict, truth: dict) -> dict:
    """Did the GWAS find the planted variant, and nothing else? Found means the planted variant
    itself is genome-wide significant: a locus nearby can be a false one (population structure
    gave one 65 kb away on 2026-11-21). Also lambda on the chromosomes it is not on (where
    nothing should be found), placed among the null runs' lambdas on the same variants;
    summary["null_statistics"] must cover the same variants as results."""
    planted = truth["variant"]
    hits = [
        locus
        for locus in summary["loci"]
        if locus["chromosome"] == planted["chromosome"]
        and abs(locus["position"] - planted["position"]) <= LOCUS_WINDOW
    ]
    frequency = results["alt_frequency"].to_numpy()
    mask = (results["chromosome"].to_numpy() != planted["chromosome"]) & (
        np.minimum(frequency, 1 - frequency) >= COMMON
    )
    null = calibration(results["chi2"].to_numpy()[mask], summary["null_statistics"][:, mask])
    planted_p = float(results.filter(pl.col("id") == planted["id"])["p"][0])
    return {
        "planted_found": planted_p < SIGNIFICANCE,
        "locus_near_planted": bool(hits),
        "lead_is_planted": bool(hits) and hits[0]["id"] == planted["id"],
        "planted_p": planted_p,
        "other_loci": len(summary["loci"]) - len(hits),
        "genomic_inflation_null_chromosomes": null["lambda"] if mask.any() else None,
        "calibration_null_chromosomes": null if mask.any() else None,
    }


def compare_with_hail(results: pl.DataFrame, path: Path) -> dict:
    """Agreement with Hail's score test on the same study (scripts/hail_gwas.py's output)."""
    hail = pl.read_csv(path, separator="\t")
    joined = results.join(hail, on="id", how="inner")
    difference = (joined["chi2"] - joined["chi_sq_stat"]).abs()
    return {
        "variants": len(results),
        "matched": len(joined),
        "chi2_max_difference": float(difference.max()),
        "chi2_correlation": float(np.corrcoef(joined["chi2"], joined["chi_sq_stat"])[0, 1]),
    }
