import gzip
import json

import numpy as np
import pandas as pd
import polars as pl
import pytest
from bed_reader import open_bed

from ehr_rwe_eln.genomics.gwas import (
    calibration,
    check_truth,
    compare_with_hail,
    null_statistics,
    pc_ancestry_agreement,
    read_pcs,
    read_regenie,
    run_gwas,
    score_test,
)
from ehr_rwe_eln.genomics.simulate import POPULATIONS, RACE_TO_POPULATION, assign_genomes
from ehr_rwe_eln.genomics.study import build_study, write_study


def people(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "age": rng.integers(18, 90, n),
            "sex": rng.choice(["female", "male"], n),
            "race": rng.choice(["white", "black", "asian", "other"], n, p=[0.7, 0.15, 0.1, 0.05]),
            "hypertension": (rng.random(n) < 0.4).astype(int),
        },
        index=pd.Index(np.arange(100, 100 + n), name="person_id"),
    )


@pytest.fixture(scope="module")
def study(tmp_path_factory):
    out = tmp_path_factory.mktemp("genomics")
    s = build_study(people(), "hypertension", chromosomes=2, length=500_000, odds_ratio=3.0, seed=1)
    write_study(out, s, out.parent / "registry.tsv")
    return out, s


def test_files_follow_the_dbgap_layout(study):
    out, s = study
    names = {p.name for p in out.iterdir()}
    assert {"chr1.vcf.gz", "chr2.vcf.gz", "study.bed", "study.bim", "study.fam"} <= names
    assert {
        "subject_phenotypes.tsv",
        "subject_sample_mapping.tsv",
        "sample_attributes.tsv",
    } <= names
    phenotypes = pl.read_csv(out / "subject_phenotypes.tsv", separator="\t")
    assert phenotypes.columns == ["subject_id", "sex", "age", "race", "hypertension"]
    assert "person_id" not in phenotypes.columns  # the OMOP link stays in the registry
    assert not any("registry" in name for name in names)  # the key is not in the study folder
    registry = pl.read_csv(out.parent / "registry.tsv", separator="\t")
    person_ids = registry["person_id"].to_list()
    assert sorted(person_ids) == list(range(100, 1600))
    assert person_ids != sorted(person_ids)  # codes do not follow person_id order
    truth = json.loads((out / "truth.json").read_text())
    assert truth["variant"]["chromosome"] == "chr1" and truth["people"] == 1500


def test_vcf_and_plink_hold_the_same_genotypes(study):
    out, s = study
    with gzip.open(out / "chr1.vcf.gz", "rt") as f:
        header = next(line for line in f if line.startswith("#CHROM"))
        first = next(f).rstrip("\n").split("\t")
    samples = header.rstrip("\n").split("\t")[9:]
    assert samples[:2] == ["SAMP-00001", "SAMP-00002"] and len(samples) == 1500
    vcf_dosage = np.array([sum(map(int, g.split("|"))) for g in first[9:]])
    with open_bed(out / "study.bed", count_A1=True) as bed:
        assert list(bed.iid) == samples
        assert bed.sid[0] == first[2] and bed.allele_1[0] == first[4]  # allele 1 is ALT
        plink_dosage = bed.read(index=np.s_[:, 0], dtype=np.float32).ravel()
    assert (vcf_dosage == plink_dosage).all()


def test_gwas_finds_the_planted_variant_and_nothing_else(study):
    out, s = study
    results, summary = run_gwas(out, "hypertension")
    check = check_truth(results, summary, s.truth)
    assert check["planted_found"] and check["other_loci"] == 0
    assert check["planted_p"] < 5e-8
    assert len(results) == s.truth["variants"]
    low, high = check["calibration_null_chromosomes"]["null_range"]
    assert low < 1 < high
    assert set(summary["calibration_by_chromosome"]) == {"chr1", "chr2"}


def test_assign_genomes_puts_carriers_with_cases():
    rng = np.random.default_rng(0)
    dosage = rng.binomial(2, 0.3, 4000)
    phenotype = (rng.random(4000) < 0.4).astype(int)
    order = assign_genomes(dosage, phenotype, 2.0, rng)
    assert sorted(order) == list(range(4000))  # every genome used once
    assigned = dosage[order]
    assert assigned[phenotype == 1].mean() > assigned[phenotype == 0].mean() + 0.1


def test_score_test_matches_a_planted_null():
    rng = np.random.default_rng(2)
    n = 3000
    y = (rng.random(n) < 0.4).astype(float)
    covariates = np.column_stack([np.ones(n), rng.normal(size=n)])
    genotypes = rng.binomial(2, 0.3, (n, 2000)).astype(np.float32)
    statistics = score_test(genotypes, y, covariates)
    assert np.median(statistics) / 0.4549 == pytest.approx(1.0, abs=0.1)


def test_null_runs_center_on_one():
    rng = np.random.default_rng(3)
    n = 3000
    covariates = np.column_stack([np.ones(n), rng.normal(size=n)])
    y = (rng.random(n) < 1 / (1 + np.exp(-covariates[:, 1]))).astype(float)
    genotypes = rng.binomial(2, 0.3, (n, 1000)).astype(np.float32)
    null = null_statistics(genotypes, y, covariates, runs=20)
    assert null.shape == (20, 1000)
    assert (np.median(null, axis=1) / 0.4549).mean() == pytest.approx(1.0, abs=0.05)


def test_calibration_places_lambda_among_null_runs():
    # Null runs whose lambdas are 0.5, 1.0, ... 5.0 times the chi-squared median.
    null = np.outer(np.arange(1, 11) / 2, np.full(5, 0.4549))
    result = calibration(np.full(5, 0.4549 * 2.0), null)
    assert result["lambda"] == pytest.approx(2.0, abs=1e-3)
    assert result["percentile"] == 40.0  # 0.5, 1.0, 1.5, 2.0 of the ten are at or below
    assert result["null_range"][0] < 1.0 and result["null_range"][1] > 4.5


def test_compare_with_hail_joins_on_variant_id(tmp_path):
    results = pl.DataFrame(
        {"id": ["chr1:5:A:C", "chr1:9:G:T", "chr2:3:T:A"], "chi2": [1.0, 4.0, 9.0]}
    )
    pl.DataFrame(
        {"id": ["chr1:5:A:C", "chr1:9:G:T"], "chi_sq_stat": [1.001, 3.999], "p_value": [0.3, 0.05]}
    ).write_csv(tmp_path / "hail_gwas.tsv", separator="\t")
    comparison = compare_with_hail(results, tmp_path / "hail_gwas.tsv")
    assert comparison["variants"] == 3 and comparison["matched"] == 2
    assert comparison["chi2_max_difference"] == pytest.approx(0.001)


def test_each_person_gets_a_genome_from_the_population_their_race_maps_to(study):
    out, s = study
    by_race = dict(zip(people().index, people()["race"], strict=True))
    races = s.subjects["person_id"].map(by_race)
    for race, population in RACE_TO_POPULATION.items():
        assert (s.subjects.loc[races == race, "ancestry"] == population).all()
    assert set(s.subjects.loc[races == "other", "ancestry"]) <= set(POPULATIONS)
    for chromosome in s.chromosomes:
        assert (chromosome.population == s.subjects["ancestry"].to_numpy()).all()
    key = pl.read_csv(out / "ancestry_truth.tsv", separator="\t")
    assert key["sample_id"].to_list() == s.subjects["sample_id"].tolist()
    truth = json.loads((out / "truth.json").read_text())
    assert sum(truth["ancestry"]["people"].values()) == 1500
    assert "ancestry" not in pl.read_csv(out / "subject_phenotypes.tsv", separator="\t").columns


def test_populations_differ_in_allele_frequency(study):
    _, s = study
    first = s.chromosomes[0]
    frequency = {p: first.dosage[:, first.population == p].mean(axis=1) / 2 for p in POPULATIONS}
    # Structure: many common variants differ by more than 0.2 between YRI and CEU.
    assert (np.abs(frequency["YRI"] - frequency["CEU"]) > 0.2).mean() > 0.05


def write_eigenvec(out, s, path) -> None:
    """PCs of the study's genotypes in PLINK 2's .eigenvec layout, in reversed sample order so
    read_pcs has to align them."""
    with open_bed(out / "study.bed", count_A1=True) as bed:
        g = bed.read(dtype=np.float32)
        samples = list(bed.iid)
    g = g[:, g.std(axis=0) > 0]
    u, d, _ = np.linalg.svd((g - g.mean(axis=0)) / g.std(axis=0), full_matrices=False)
    table = {"#FID": samples, "IID": samples} | {f"PC{i + 1}": u[:, i] * d[i] for i in range(10)}
    pl.DataFrame(table).reverse().write_csv(path, separator="\t")


def test_pcs_recover_the_populations_and_join_the_covariates(study, tmp_path):
    out, s = study
    write_eigenvec(out, s, tmp_path / "pcs.eigenvec")
    pcs = read_pcs(tmp_path / "pcs.eigenvec", s.subjects["sample_id"].tolist())
    assert pcs.shape == (1500, 10)
    assert pc_ancestry_agreement(pcs, s.subjects["ancestry"].to_numpy()) > 0.95
    results, summary = run_gwas(out, "hypertension", null_runs=5, pcs=tmp_path / "pcs.eigenvec")
    assert check_truth(results, summary, s.truth)["planted_found"]


def test_read_regenie_turns_frequency_to_the_alternate_allele(tmp_path):
    (tmp_path / "step2_hypertension.regenie").write_text(
        "CHROM GENPOS ID ALLELE0 ALLELE1 A1FREQ N TEST BETA SE CHISQ LOG10P EXTRA\n"
        "1 5 chr1:5:A:C A C 0.2 100 ADD 0.1 0.1 4.0 1.3 NA\n"
        "2 9 chr2:9:G:T T G 0.7 100 ADD 0.1 0.1 9.0 2.6 NA\n"
    )
    r = read_regenie(tmp_path / "step2_hypertension.regenie")
    assert r["chromosome"].to_list() == ["chr1", "chr2"]
    assert r["alt_frequency"].to_list() == pytest.approx([0.2, 0.3])
    assert r["p"].to_list() == pytest.approx([10**-1.3, 10**-2.6])


def test_a_locus_next_to_the_planted_variant_is_not_finding_it():
    truth = {"variant": {"id": "chr1:1000:A:G", "chromosome": "chr1", "position": 1000}}
    results = pl.DataFrame(
        {
            "id": ["chr1:1000:A:G", "chr1:66000:C:T", "chr2:500:G:A"],
            "chromosome": ["chr1", "chr1", "chr2"],
            "position": [1000, 66000, 500],
            "alt_frequency": [0.3, 0.3, 0.3],
            "chi2": [20.0, 40.0, 0.5],
            "p": [1e-5, 1e-10, 0.5],
        }
    )
    summary = {
        "loci": [results.row(1, named=True)],
        "null_statistics": np.full((10, 3), 0.4549),
    }
    check = check_truth(results, summary, truth)
    assert check["locus_near_planted"] and not check["lead_is_planted"]
    assert not check["planted_found"]
