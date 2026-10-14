import gzip
import json

import numpy as np
import pandas as pd
import polars as pl
import pytest
from bed_reader import open_bed

from ehr_rwe_eln.genomics.gwas import check_truth, run_gwas, score_test
from ehr_rwe_eln.genomics.simulate import assign_genomes
from ehr_rwe_eln.genomics.study import build_study, write_study


def people(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "age": rng.integers(18, 90, n),
            "sex": rng.choice(["female", "male"], n),
            "hypertension": (rng.random(n) < 0.4).astype(int),
        },
        index=pd.Index(np.arange(100, 100 + n), name="person_id"),
    )


@pytest.fixture(scope="module")
def study(tmp_path_factory):
    out = tmp_path_factory.mktemp("genomics")
    s = build_study(people(), "hypertension", chromosomes=2, length=500_000, odds_ratio=3.0, seed=1)
    write_study(out, s)
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
    assert phenotypes.columns == ["subject_id", "sex", "age", "hypertension"]
    assert "person_id" not in phenotypes.columns  # the OMOP link stays in the registry
    registry = pl.read_csv(out / "subject_registry.tsv", separator="\t")
    assert registry["person_id"].to_list() == list(range(100, 1600))
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
