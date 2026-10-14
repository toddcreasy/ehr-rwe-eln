"""Load the synthetic genotyping study into Hail, keep it as a MatrixTable, and rerun the GWAS.

Usage: docker compose run --rm --build hail

Runs inside the hail container (docker/hail.Dockerfile), so it imports Hail and nothing from
this project. Run scripts/generate_genomics.py first. Reads the VCFs and tables in
data/genomics/; writes data/genomics/study.mt (a Hail MatrixTable: variants as rows, samples as
columns, genotypes as entries) and data/genomics/hail_gwas.tsv, which scripts/run_gwas.py
compares with its own results.
"""

import json
from pathlib import Path

import hail as hl

DATA = Path("/work/data/genomics")
# Spark's scratch space, in the container user's home.
SCRATCH = Path.home() / "hail-tmp"
CHI2_MEDIAN = 0.454936


def main() -> None:
    truth = json.loads((DATA / "truth.json").read_text())
    hl.init(
        quiet=True,
        tmp_dir=str(SCRATCH),
        local_tmpdir=str(SCRATCH),
        log=str(SCRATCH / "hail.log"),
        spark_conf={"spark.driver.memory": "4g"},
    )
    contigs = [f"chr{c}" for c in range(1, truth["chromosomes"] + 1)]
    # A reference genome for the simulated contigs, so loci are checked against real bounds.
    reference = hl.ReferenceGenome("synthetic", contigs, {c: truth["length"] for c in contigs})
    # force: the VCFs are plain gzip, read whole; bgzip would let Hail split them across cores.
    mt = hl.import_vcf(
        [str(DATA / f"{c}.vcf.gz") for c in contigs], reference_genome=reference, force=True
    )
    phenotypes = hl.import_table(
        str(DATA / "subject_phenotypes.tsv"), key="subject_id", impute=True
    )
    mapping = hl.import_table(str(DATA / "subject_sample_mapping.tsv"), key="sample_id")
    mt = mt.annotate_cols(subject_id=mapping[mt.s].subject_id)
    mt = mt.annotate_cols(pheno=phenotypes[mt.subject_id])
    mt = hl.variant_qc(mt)
    mt.write(str(DATA / "study.mt"), overwrite=True)

    mt = hl.read_matrix_table(str(DATA / "study.mt"))
    variants, samples = mt.count()
    age = mt.aggregate_cols(hl.agg.stats(mt.pheno.age))
    mt = mt.annotate_cols(
        age_std=(mt.pheno.age - age.mean) / age.stdev,
        male=hl.float(mt.pheno.sex == "male"),
    )
    gwas = hl.logistic_regression_rows(
        test="score",
        y=hl.float(mt.pheno[truth["phenotype"]]),
        x=mt.GT.n_alt_alleles(),
        covariates=[1.0, mt.age_std, mt.male],
    )
    gwas = gwas.annotate(
        id=hl.format(
            "%s:%d:%s:%s", gwas.locus.contig, gwas.locus.position, gwas.alleles[0], gwas.alleles[1]
        )
    )
    gwas = gwas.key_by().select("id", "chi_sq_stat", "p_value")
    gwas.export(str(DATA / "hail_gwas.tsv"))

    planted = gwas.filter(gwas.id == truth["variant"]["id"]).collect()[0]
    top = gwas.order_by(gwas.p_value).take(1)[0]
    median = gwas.aggregate(hl.agg.approx_median(gwas.chi_sq_stat))
    print(f"MatrixTable: {variants:,} variants x {samples:,} samples, written to study.mt")
    print(f"planted {planted.id}: p {planted.p_value:.2e}; top {top.id}: p {top.p_value:.2e}")
    print(f"genomic inflation (approximate median) {median / CHI2_MEDIAN:.3f}")


if __name__ == "__main__":
    main()
