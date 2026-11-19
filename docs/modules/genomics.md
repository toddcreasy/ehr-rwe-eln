# Synthetic genomics

Package: `ehr_rwe_eln.genomics`. Back to the [README](../../README.md). Terms are defined in the [glossary](../GLOSSARY.md).

A genotyping study for adults in the [OMOP](https://ohdsi.github.io/CommonDataModel/cdm54.html) build, made with no real genome, to build and test genomic pipelines against. It is laid out the way [dbGaP](https://www.ncbi.nlm.nih.gov/gap/) (NIH's database of Genotypes and Phenotypes) distributes a study, with one known genetic effect planted in it, and a GWAS (genome-wide association study) that has to find that effect and nothing else.

## What it does

1. **Simulate genomes** (`simulate.py`). [msprime](https://tskit.dev/msprime/) runs the coalescent with recombination: it traces simulated chromosomes back through shared ancestors, so allele frequencies and linkage disequilibrium (nearby variants inherited together) look like real data's.
2. **Plant an effect.** One common variant on chromosome 1 is chosen, and whole simulated genomes are assigned to people so that carriers of it are more likely to have the phenotype. Assigning whole genomes, rather than editing one variant, keeps linkage disequilibrium intact.
3. **Lay it out like dbGaP** (`study.py`): a VCF (variant call format) file per chromosome, one [PLINK](https://www.cog-genomics.org/plink/) binary set, subject phenotypes from OMOP, sample attributes, and a subject-to-sample mapping. Study codes go to people in a random order. The registry linking codes to OMOP persons is written to `data/registry/`, outside the study folder.
4. **Run the GWAS** (`gwas.py`). A score test for every variant, adjusted for age and sex, then the full logistic model on each lead variant. The result is checked against the planted effect: found, nothing else found, and genomic inflation on the chromosomes without it.
5. **Cross-check in [Hail](https://hail.is).** The same study as a Hail MatrixTable, with the GWAS rerun there and compared variant by variant. Hail pins pandas below 3, PySpark 3.5, and Java 11, so it runs in its own container.

Genomic inflation (lambda) compares the middle of the observed test statistics with what chance alone gives. 1.0 means well calibrated. Above 1 means something other than the planted effect pushes p-values down, such as population structure. Below 1 means the test is too conservative.

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

The GWAS finds the planted effect and nothing else. A neighbor carries the strongest signal, which linkage disequilibrium allows: nearby variants travel with the planted one.

The inflation is the open question. With no effect present, inflation per chromosome on a genome this small varies by about 0.06, so 0.76 is well below what chance explains, and the test may be too conservative. The README's earlier figures (planted variant at p 1.4e-11, inflation 0.95) do not reproduce from the same code on this build, so they are not quoted here. Until that is explained, treat the p-values as uncalibrated. The Hail comparison has not been rerun on this build.
