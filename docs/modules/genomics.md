# Synthetic genomics

Package: `ehr_rwe_eln.genomics`. Back to the [README](../../README.md). Terms are defined in the [glossary](../GLOSSARY.md).

A genotyping study for adults in the [OMOP](https://ohdsi.github.io/CommonDataModel/cdm54.html) build, made with no real genome, to build and test genomic pipelines against. It is laid out the way [dbGaP](https://www.ncbi.nlm.nih.gov/gap/) (NIH's database of Genotypes and Phenotypes) distributes a study, with one known genetic effect planted in it, and a GWAS (genome-wide association study) that has to find that effect and nothing else.

## What it does

1. **Simulate genomes** (`simulate.py`). [msprime](https://tskit.dev/msprime/) runs the coalescent with recombination: it traces simulated chromosomes back through shared ancestors, so allele frequencies and linkage disequilibrium (nearby variants inherited together) look like real data's.
2. **Plant an effect.** One common variant on chromosome 1 is chosen, and whole simulated genomes are assigned to people so that carriers of it are more likely to have the phenotype. Assigning whole genomes, rather than editing one variant, keeps linkage disequilibrium intact.
3. **Lay it out like dbGaP** (`study.py`): a VCF (variant call format) file per chromosome, one [PLINK](https://www.cog-genomics.org/plink/) binary set, subject phenotypes from OMOP, sample attributes, and a subject-to-sample mapping. Study codes go to people in a random order. The registry linking codes to OMOP persons is written to `data/registry/`, outside the study folder.
4. **Run the GWAS** (`gwas.py`). A score test for every variant, adjusted for age and sex, then the full logistic model on each lead variant. The result is checked against the planted effect: found, nothing else found, and genomic inflation on the chromosomes without it. That inflation is read against 100 phenotypes redrawn from the age-and-sex model alone, with no genetic effect, so it comes with a percentile instead of a bare number.
5. **Cross-check in [Hail](https://hail.is).** The same study as a Hail MatrixTable, with the GWAS rerun there and compared variant by variant. Hail pins pandas below 3, PySpark 3.5, and Java 11, so it runs in its own container.

Genomic inflation (lambda) compares the middle of the observed test statistics with what chance alone gives. 1.0 means well calibrated. Above 1 means something other than the planted effect pushes p-values down, such as population structure. Below 1 means the test is too conservative. On a genome this small lambda is noisy: nearby variants are inherited together, so a few thousand of them behave like a few dozen independent tests, and lambda with no effect at all has a standard deviation of about 0.10.

## Run it

```bash
uv run python scripts/generate_genomics.py   # about 2 minutes
uv run python scripts/run_gwas.py
docker compose run --rm --build hail                                 # optional, 2.4 GB image
```

The defaults simulate 5,000 adults on three 3 Mb chromosomes with an odds ratio of 1.4 planted on hypertension. Everything is written to `data/genomics/`. After the Hail run, `run_gwas.py` also reports how closely Hail's score statistics agree with its own.

## Results

On the current 23,421-person build, 2026-11-18:

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
