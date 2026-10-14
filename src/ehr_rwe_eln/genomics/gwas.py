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
  something such as population structure is inflating every test. On a small simulated genome
  it is noisy: over 20 random phenotypes with no effect, 5,000 people and three 3 Mb
  chromosomes gave a mean of 0.99 and a standard deviation of 0.06. A strong real signal also
  lifts its whole chromosome through weak long-range LD, so the truth check reads lambda on the
  chromosomes without the planted variant.
"""

from pathlib import Path

import numpy as np
import polars as pl
import statsmodels.api as sm
from bed_reader import open_bed
from scipy.stats import chi2

SIGNIFICANCE = 5e-8
LOCUS_WINDOW = 500_000
CHI2_MEDIAN = chi2.ppf(0.5, 1)
CHUNK = 2000
COMMON = 0.05


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


def run_gwas(directory: Path, phenotype: str) -> tuple[pl.DataFrame, dict]:
    genotypes, variants, people = load(directory)
    y = people[phenotype].to_numpy().astype(float)
    age = people["age"].to_numpy().astype(float)
    male = (people["sex"] == "male").to_numpy().astype(float)
    covariates = np.column_stack([np.ones(len(people)), (age - age.mean()) / age.std(), male])
    statistics = score_test(genotypes, y, covariates)
    frequency = genotypes.mean(axis=0) / 2
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
        "significant_variants": int((results["p"] < SIGNIFICANCE).sum()),
        "loci": found,
    }
    return results, summary


def check_truth(results: pl.DataFrame, summary: dict, truth: dict) -> dict:
    """Did the GWAS find the planted variant, and nothing else? Also the planted variant's own
    p, and lambda on the chromosomes it is not on (where nothing should be found)."""
    planted = truth["variant"]
    hits = [
        locus
        for locus in summary["loci"]
        if locus["chromosome"] == planted["chromosome"]
        and abs(locus["position"] - planted["position"]) <= LOCUS_WINDOW
    ]
    null = results.filter(
        (pl.col("chromosome") != planted["chromosome"])
        & (pl.min_horizontal(pl.col("alt_frequency"), 1 - pl.col("alt_frequency")) >= COMMON)
    )
    return {
        "planted_found": bool(hits),
        "lead_is_planted": bool(hits) and hits[0]["id"] == planted["id"],
        "planted_p": float(results.filter(pl.col("id") == planted["id"])["p"][0]),
        "other_loci": len(summary["loci"]) - len(hits),
        "genomic_inflation_null_chromosomes": inflation(null) if len(null) else None,
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
