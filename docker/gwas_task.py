"""The GWAS task: PLINK 2 quality control and principal components, then REGENIE.

Usage: gwas_task.py --prefix studies/<id> (the Fargate task's command, from scripts/run_regenie.py)

Runs inside the gwas container (docker/gwas.Dockerfile), so it uses only the standard library and
boto3. Reads s3://$GWAS_BUCKET/<prefix>/input/ (study.bed/.bim/.fam, pheno.tsv, covariates.tsv,
hwe_keep.tsv) and writes every result and log to <prefix>/output/, also when a step fails.

1. QC: drop people and variants with more than 2% missing calls, variants under 1% minor allele
   frequency, then variants out of Hardy-Weinberg equilibrium (p < 1e-6). HWE is tested only in
   hwe_keep.tsv's people (one self-reported group): across populations whose allele frequencies
   differ, a pooled sample has too few heterozygotes (the Wahlund effect) and good variants fail.
2. Principal components: 10, on common variants (5% or more) pruned so no two within 500 kb have
   r-squared above 0.1; correlated variants would let LD blocks, not ancestry, drive the PCs.
3. REGENIE step 1: a whole-genome ridge regression predicting the phenotype from every QC'd
   variant, one prediction per chromosome left out (LOCO), so a variant is never adjusted for
   itself. Step 2: each variant tested with that prediction as an offset, age, sex, and the PCs as
   covariates, Firth-corrected where p < 0.01 (a binary trait's test is unreliable otherwise).
"""

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path

import boto3

WORK = Path.home() / "work"
THREADS = str(os.cpu_count() or 2)


def run(command: str) -> None:
    print("+", command, flush=True)
    subprocess.run(command.split(), check=True, cwd=WORK)  # noqa: S603  (fixed commands, no user input)


def merge_covariates(covariates: Path, eigenvec: Path, out: Path) -> None:
    """covariates.tsv (FID IID age male) joined with PLINK 2's PCs on IID."""
    with eigenvec.open() as f:
        rows = list(csv.reader(f, delimiter="\t"))
    header = [h.lstrip("#") for h in rows[0]]
    iid, first_pc = header.index("IID"), header.index("PC1")
    pcs = {r[iid]: r[first_pc:] for r in rows[1:]}
    with covariates.open() as f, out.open("w", newline="") as g:
        reader, writer = csv.reader(f, delimiter="\t"), csv.writer(g, delimiter="\t")
        top = next(reader)
        writer.writerow(top + header[first_pc:])
        for r in reader:
            writer.writerow(r + pcs[r[top.index("IID")]])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", required=True)
    prefix = parser.parse_args().prefix.rstrip("/")
    bucket, s3 = os.environ["GWAS_BUCKET"], boto3.client("s3")
    WORK.mkdir(parents=True, exist_ok=True)
    inputs = ["study.bed", "study.bim", "study.fam", "pheno.tsv", "covariates.tsv", "hwe_keep.tsv"]
    for name in inputs:
        s3.download_file(bucket, f"{prefix}/input/{name}", str(WORK / name))
    failed = False
    regenie = f"--bed qc --phenoFile pheno.tsv --covarFile covar.tsv --bt --threads {THREADS}"
    try:
        run("plink2 --bfile study --mind 0.02 --geno 0.02 --maf 0.01 --make-bed --out qc1")
        run("plink2 --bfile qc1 --keep hwe_keep.tsv --hwe 1e-6 --write-snplist --out hwe")
        run("plink2 --bfile qc1 --extract hwe.snplist --make-bed --write-snplist --out qc")
        run("plink2 --bfile qc --maf 0.05 --indep-pairwise 500kb 0.1 --out prune")
        run("plink2 --bfile qc --extract prune.prune.in --pca 10 --out pcs")
        merge_covariates(WORK / "covariates.tsv", WORK / "pcs.eigenvec", WORK / "covar.tsv")
        run(f"regenie --step 1 {regenie} --bsize 1000 --out step1")
        run(
            f"regenie --step 2 {regenie} --firth --approx --pThresh 0.01"
            " --pred step1_pred.list --bsize 400 --out step2"
        )
    except subprocess.CalledProcessError as error:
        print(f"failed: {error}", file=sys.stderr, flush=True)
        failed = True
    keep = [".log", ".regenie", ".eigenvec", ".eigenval", ".snplist", ".prune.in", "covar.tsv"]
    for path in sorted(WORK.iterdir()):
        if any(path.name.endswith(k) for k in keep):
            s3.upload_file(str(path), bucket, f"{prefix}/output/{path.name}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
