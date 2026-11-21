# Synthetic genomics

Package: `ehr_rwe_eln.genomics`. Back to the [README](../../README.md). Terms are defined in the [glossary](../GLOSSARY.md).

A genotyping study for adults in the [OMOP](https://ohdsi.github.io/CommonDataModel/cdm54.html) build, made with no real genome, to build and test genomic pipelines against. It is laid out the way [dbGaP](https://www.ncbi.nlm.nih.gov/gap/) (NIH's database of Genotypes and Phenotypes) distributes a study, with one known genetic effect planted in it, and a GWAS (genome-wide association study) that has to find that effect and nothing else.

## What it does

1. **Simulate genomes** (`simulate.py`). [stdpopsim](https://popsim-consortium.github.io/stdpopsim-docs/)'s `OutOfAfrica_3G09` model (Gutenkunst et al. 2009) runs on [msprime](https://tskit.dev/msprime/), the coalescent with recombination: it traces simulated chromosomes back through three populations, YRI (Yoruba, West African), CEU (European), and CHB (Han Chinese, East Asian), so allele frequencies, linkage disequilibrium (nearby variants inherited together), and the differences between populations look like real data's. Each person's population follows the race in their OMOP record: Black to YRI, White to CEU, Asian to CHB, any other race at random. That is a simulation convention, not a claim that race is ancestry. It ties ancestry to hypertension the way Synthea's rates differ by race (61% of Black adults, 43% of White), which gives the GWAS population structure to correct.
2. **Plant an effect.** One common variant on chromosome 1 is chosen, and whole simulated genomes from each person's own population are assigned so that carriers of it are more likely to have the phenotype. Assigning whole genomes, rather than editing one variant, keeps linkage disequilibrium intact.
3. **Lay it out like dbGaP** (`study.py`): a VCF (variant call format) file per chromosome, one [PLINK](https://www.cog-genomics.org/plink/) binary set, subject phenotypes from OMOP, sample attributes, and a subject-to-sample mapping. Study codes go to people in a random order. The registry linking codes to OMOP persons is written to `data/registry/`, outside the study folder. Each sample's population is in `ancestry_truth.tsv`, an answer key like `truth.json`, never in the study tables.
4. **QC, principal components, and REGENIE on AWS** (`scripts/run_regenie.py`, `docker/gwas_task.py`). [PLINK 2](https://www.cog-genomics.org/plink/2.0/) drops people and variants with more than 2% missing calls and variants under 1% frequency, then tests Hardy-Weinberg equilibrium within self-reported White participants only: pooled across populations whose frequencies differ, a sample has too few heterozygotes (the Wahlund effect) and good variants fail. It then computes 10 principal components (PCs) on common variants pruned of LD. [REGENIE](https://rgcgithub.github.io/regenie/) is the primary test: step 1 fits a whole-genome ridge regression of the phenotype on every variant, leaving out one chromosome at a time; step 2 tests each variant with that prediction as an offset and age, sex, and the PCs as covariates, Firth-corrected below p 0.01. REGENIE ships no ARM build, so the image is built by CodeBuild on x86 and runs as an x86 Fargate task (`infra/terraform/app/gwas.tf`); nothing runs on the laptop. Results come back to `data/genomics/regenie/<run>/`.
5. **Run the GWAS** (`gwas.py`). A score test for every variant, adjusted for age, sex, and the same 10 PCs, then the full logistic model on each lead variant: the readable check on REGENIE. Both are checked against the planted effect: the planted variant itself genome-wide significant, nothing else found, and genomic inflation on the chromosomes without it. That inflation is read against 100 phenotypes redrawn from the covariate model alone, with no genetic effect, so it comes with a percentile instead of a bare number; the same null runs, on the variants QC kept, calibrate REGENIE. A cross-validated classifier from the PCs to each person's simulated population (`ancestry_truth.tsv`) checks that the PCs carry ancestry.
6. **Cross-check in [Hail](https://hail.is).** The same study as a Hail MatrixTable, with the GWAS rerun there and compared variant by variant. Hail pins pandas below 3, PySpark 3.5, and Java 11, so it runs in its own container.
7. **Add a clinical panel** (`panel.py`, `clinvar.py`, `gnomad.py`). The simulated chromosomes have made-up coordinates, which suits a GWAS but not curation, where a variant is looked up by its real position. So the same samples also get a panel VCF of real [ClinVar](https://www.ncbi.nlm.nih.gov/clinvar/) variants at their real GRCh38 positions, in six genes from the [ACMG secondary findings list](https://www.ncbi.nlm.nih.gov/clinvar/docs/acmg/) whose condition Synthea records. Pathogenic variants are planted at a higher rate in people whose OMOP record has the gene's condition; common benign variants at their [gnomAD](https://gnomad.broadinstitute.org) v4 frequency in everyone; variants of uncertain significance at a fixed low rate. The VCF holds positions, alleles, and genotypes only. ClinVar's classification and every carrier are in `panel_truth.json`, the answer key for curating the panel.

Genomic inflation (lambda) compares the middle of the observed test statistics with what chance alone gives. 1.0 means well calibrated. Above 1 means something other than the planted effect pushes p-values down, such as population structure. Below 1 means the test is too conservative. On a genome this small lambda is noisy: nearby variants are inherited together, so a few thousand of them behave like a few dozen independent tests, and lambda with no effect at all has a standard deviation of about 0.10.

## Run it

```bash
uv run python scripts/generate_genomics.py   # about 3 minutes
uv run python scripts/run_regenie.py         # on AWS, about 4 minutes (plus 5 to build a new image)
uv run python scripts/run_gwas.py            # --no-pcs for the uncorrected test
docker compose run --rm --build hail                                 # optional, 2.4 GB image
uv run python scripts/generate_panel.py      # the clinical panel, after generate_genomics.py
```

`generate_genomics.py` and `generate_panel.py` read their people and conditions from OMOP: oMOP is read from the lake through Redshift; `OMOP_SOURCE=staging` reads the staging Postgres instead (see [Who reads the lake](cohort.md#who-reads-the-lake)).

The defaults simulate 5,000 adults on three 3 Mb chromosomes with an odds ratio of 1.4 planted on hypertension. Everything is written to `data/genomics/`. The panel's genes, carrier rates, and variant counts are in `src/ehr_rwe_eln/genomics/panel.yaml`. Its first run downloads the ClinVar release the spec names (200 MB, checked against NCBI's md5) to `data/reference/clinvar/`, and asks gnomAD's public API about a few dozen variants, about two minutes at gnomAD's limit of 10 requests a minute. Answers are cached in `data/reference/gnomad/`, so later runs take about 10 seconds and make no requests. After the Hail run, `run_gwas.py` also reports how closely Hail's score statistics agree with its own.

## Results

### Three populations, corrected, 2026-11-21

The same study as below, with 10 PCs as covariates. QC removed nothing: simulated genotypes have no missing calls, and every variant passed Hardy-Weinberg in the 4,122 White participants. The PCs came from 213 variants left after pruning (frequency 5% or more, r-squared under 0.1 within 500 kb).

| | Uncorrected score test | Score test + 10 PCs | REGENIE + 10 PCs |
|---|---|---|---|
| Genomic inflation, all chromosomes | 4.0 | 0.950 | 0.981 |
| Genomic inflation without chr1 (percentile of 100 null runs) | 4.0 (100) | 0.919 (17) | 0.947 (29) |
| Planted variant p | 0.58 | 2.2e-11 | 1.5e-11 |
| Other loci | 12 | 0 | 0 |

The null runs' middle 95% is 0.81 to 1.25. In both corrected tests the locus is led by chr1:1907158:G:A, 3.4 kb from the planted variant and in LD with it (p 2.1e-11 and 1.4e-11); the score test's odds ratio there is 1.46 (1.30 to 1.63) against 1.4 planted. The 10 PCs predict every person's simulated population (100%, 5-fold cross-validated). REGENIE ran in 201 seconds on Fargate, x86, 2 vCPUs.

### Three populations, no ancestry correction, 2026-11-21

| | Value |
|---|---|
| People | 5,000 (2,256 with hypertension): 4,177 CEU, 455 YRI, 368 CHB |
| Variants | 26,361 |
| Planted variant | chr1:1903772:C:A, alternate allele frequency 0.721 in cases and 0.698 in controls; 0.13 in YRI, 0.80 in CEU, 0.36 in CHB |
| Planted variant significant | no, p 0.58 |
| Other loci | 12, p 7.5e-9 to 1.4e-13 |
| Genomic inflation, chromosomes without the effect | 4.0, percentile 100 (null runs' middle 95%: 0.79 to 1.33) |

The age-and-sex score test fails on purpose here. Variants that differ in frequency between populations look associated with hypertension because the populations differ in it, and the planted variant's real effect is hidden by the same confounding: YRI have more hypertension and fewer copies. The truth check then printed "found", because a false locus 65 kb away put the planted variant inside a significant locus; since PR 2, found means the planted variant itself passes 5e-8. Principal components and REGENIE are the fix (above).

### One population, 2026-11-18

The study before stdpopsim: 5,000 people from one population of fixed size, on the 23,421-person build. The calibration below is from this study.

| | Value |
|---|---|
| People | 5,000 (2,256 with hypertension) |
| Variants | 16,080 |
| Planted variant | chr1:2360834:C:G, alternate allele frequency 0.295 in cases and 0.220 in controls |
| Planted variant found | yes, p 1.28e-15 |
| Lead variant at its locus | chr1:2358417:A:G, a neighbor in linkage disequilibrium, p 8.65e-16 |
| Other loci | none |
| Genomic inflation, chromosomes without the effect | 0.80 (chr2 0.76, chr3 0.83) |
| Its percentile among 100 null runs | 0 (their middle 95%: 0.85 to 1.22) |

The GWAS finds the planted effect and nothing else. A neighbor carries the strongest signal, which linkage disequilibrium allows: nearby variants travel with the planted one.

### Calibration

The 0.80 is a low draw, not a broken test. A single study can't show that, so the check was run on 16 studies, rebuilt with seeds 0 to 15 and the same settings:

- The score test matches a full logistic regression's likelihood ratio test to within 0.001 on the variants checked.
- On this study's genotypes, 100 phenotypes with no genetic effect give lambda 1.02 on average per chromosome. The test is unbiased.
- Across the 16 rebuilds, the percentile of lambda among its own null runs averages 46 (50 if calibrated). Two fall below 10 and two above 90, about what chance gives. This build, seed 0, is the lowest at 0; seed 4 is the highest at 99.
- Planting the effect does not move lambda on the other chromosomes: rebuilt with and without it, the same seeds differ by 0.03 on average, in both directions.

So read lambda through its percentile. One study at 0 or 100 is a draw; rebuild after rebuild near 0 or 100 would point at the pipeline. The study is kept at seed 0 rather than reseeded for a better-looking number. The earlier README figures (planted variant at p 1.4e-11, inflation 0.95) came from an earlier build and are another draw from the same spread. The Hail comparison has not been rerun on this build.

### Clinical panel

ClinVar release 2026-11-15, gnomAD v4, on the same 5,000 subjects, 2026-11-19:

| Gene | Condition in OMOP | People with it | Pathogenic carriers with it | Without it |
|---|---|---|---|---|
| BRCA1, BRCA2 | Malignant neoplasm of breast | 99 | 7 (7%) | 14 (0.3%) |
| MLH1, MSH2, APC | Malignant neoplasm of colon | 107 | 14 (13%) | 15 (0.3%) |
| LDLR | Hyperlipidemia | 1,006 | 50 (5%) | 24 (0.6%) |

48 variants: 3 pathogenic, 3 benign, and 2 of uncertain significance per gene, each with at least two ClinVar stars (several submitters agree, or an expert panel). The pathogenic ones are 10 frameshifts, 7 nonsense variants, and 1 splice acceptor; 17 of 18 are absent from gnomAD and the last is at 2.5 in a million. In the study, each benign variant's frequency is within 0.008 of gnomAD's. Variants of 50 bp or more are left out: those count as structural variants, which panels call and curate separately.

The carrier rates are set in the spec at about twice what studies report among people with each condition, so a study this size has carriers to test with; without the condition they are near population rates. These are real variants in synthetic people: no carrier is a real person, and the rates are not estimates of anything.
