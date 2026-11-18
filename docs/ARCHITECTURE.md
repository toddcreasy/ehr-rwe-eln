# Architecture

How the pieces fit, why each tool fills its slot, and what is still missing. Setup is in [INSTALL.md](INSTALL.md); the build history, including the AWS version this replaced, is in [SETUP.md](SETUP.md). Terms are defined in the [glossary](GLOSSARY.md).

<img src="architecture.svg" alt="ehr-rwe-eln architecture. Top: a browser reaches the app container (FastAPI plus a static Next.js frontend), which reads Postgres 18 with pgvector; scripts on the host write to Postgres; a Hail container runs on request. Middle: Synthea output and Athena vocabularies feed the cohort pipeline, which builds the OMOP CDM v5.4 tables. Data quality, target trial emulation, synthetic data, and synthetic genomics read OMOP and write their own schemas and files. The ELN bridge sends free-text entries to Claude on the Anthropic API and writes specimen and measurement rows into OMOP and a FHIR R4 bundle. Bottom: pre-commit, pull requests, GitHub Actions, pytest, and evals." width="100%">

GitHub shows the diagram as a plain image. Opened in a browser, [`architecture.svg`](architecture.svg) is interactive: hover a box for what it does and why, and click it for its source or docs. `uv run python scripts/make_diagrams.py` redraws it.

## Contents

1. [One database](#one-database)
2. [How data moves](#how-data-moves)
3. [The app](#the-app)
4. [Where Claude is used](#where-claude-is-used)
5. [Stack](#stack)
6. [Design decisions](#design-decisions)
7. [Known gaps](#known-gaps)

## One database

Every module reads or writes one [OMOP CDM v5.4](https://ohdsi.github.io/CommonDataModel/cdm54.html) database (the Observational Medical Outcomes Partnership Common Data Model, the standard schema [OHDSI](https://www.ohdsi.org) tools expect). OMOP gives every diagnosis, drug, and lab test a standard concept, so a cohort definition, a data quality check, or a trial protocol written against it runs on any OMOP database.

Postgres holds two databases built the same way from different [Synthea](https://github.com/synthetichealth/synthea) runs:

| Database | People | Used by |
|---|---|---|
| `ehr_rwe_eln` | 1,172 | Cohorts, data quality, the ELN bridge |
| `ehr_rwe_eln_tte` | 23,421 | Target trial emulation, synthetic data, synthetic genomics |

The second exists because the small one has too few outcome events for a trial estimate. Each database has the OMOP tables in `cdm` and one schema per module for its own results: `dq`, `tte`, `eln`, and `synth`. [Alembic](https://alembic.sqlalchemy.org) migrations create the module schemas; `scripts/build_omop.py` builds `cdm`.

## How data moves

The cohort pipeline turns Synthea CSV files into OMOP tables, mapping each source code to its standard concept with the [Athena](https://athena.ohdsi.org) vocabularies. The ETL was checked table by table against OHDSI's own [ETL-Synthea](https://github.com/OHDSI/ETL-Synthea) on the same input; every difference is explained, and two of them are bugs in ETL-Synthea ([comparison](etl_synthea_comparison.md)).

Four modules only read OMOP. Data quality runs 2,384 checks and stores the results. Trial emulation builds an analysis table per protocol and stores a bias report. The synthetic data module builds a source table from OMOP and stores differentially private copies of it. The genomics module draws people from OMOP for a simulated genotype study and writes files, not tables.

The ELN bridge goes the other way. It reads free-text lab notebook entries, has Claude extract samples and results, and writes them into OMOP as `specimen` and `measurement` rows, linked to the right person through a study subject registry. Once there, bench results sit next to the clinical record, where the other modules can use them.

## The app

One container runs [FastAPI](https://fastapi.tiangolo.com). It serves the API under `/api` and the frontend at `/`. The frontend is a [Next.js](https://nextjs.org) static export: `npm run build` turns it into HTML and JavaScript files, so no Node server runs in production. Pages:

| Page | Shows | API |
|---|---|---|
| `/dq/` | Data quality runs, by check and table | `/api/dq/runs` |
| `/tte/` | Bias reports per trial protocol | `/api/tte/runs` |
| `/eln/` | Each ELN entry beside what was extracted | `/api/eln/entries` |
| `/synth/` | Synthetic releases compared, with their data cards | `/api/synth/releases` |

There is no sign-in. Every port binds to 127.0.0.1, so nothing is reachable from another machine.

## Where Claude is used

Two places, both on Claude Opus 5.5 through the [Anthropic API](https://docs.claude.com), set by one `MODEL` setting:

- **ELN extraction** (`src/ehr_rwe_eln/eln/`). Structured outputs constrain each reply to the extraction schema, and [Pydantic](https://docs.pydantic.dev) validates it before anything is stored. Offline runs go through the [Message Batches API](https://docs.claude.com/en/docs/build-with-claude/batch-processing) at half price.
- **The agent** at `POST /api/agent` (`src/ehr_rwe_eln/agents/`), a small tool-using agent on the Anthropic SDK's tool runner. It checks the time and the database.

Both are scored by evals in `evals/` against the real model. They are slow and billed, so they run by hand, never in CI.

## Stack

| Slot | Tool | Why |
|---|---|---|
| Database | PostgreSQL 18 + [pgvector](https://github.com/pgvector/pgvector), in [Docker Compose](https://docs.docker.com/compose/) | Concurrent writers and vector search, which DuckDB's single-writer file did not fit. Runs anywhere Docker does |
| Migrations | Alembic | Versioned schema changes for the module schemas |
| Python | 3.14, uv, ruff, pytest | One fast tool per job, versions pinned in `uv.lock` |
| Model | Claude Opus 5.5 on the Anthropic API | Each user brings their own key; one model for every call |
| Agent framework | Anthropic Python SDK tool runner | Runs the tool loop and returns typed output with no extra framework |
| Causal inference and survival | [scikit-learn](https://scikit-learn.org), [statsmodels](https://www.statsmodels.org), [lifelines](https://lifelines.readthedocs.io) | Propensity scores, Cox models, Kaplan-Meier |
| Differential privacy | [diffprivlib](https://github.com/IBM/differential-privacy-library), [Opacus](https://opacus.ai) | Noisy histograms with a budget accountant; DP-SGD for the autoencoder |
| Genomics | [msprime](https://tskit.dev/msprime/), [Hail](https://hail.is) | Coalescent simulation; Hail as the cross-check for the GWAS |
| Interoperability | `fhir.resources` | [FHIR R4](https://hl7.org/fhir/R4/) models in Python, no FHIR server needed at this scale |
| API | FastAPI + Pydantic | Typed requests and responses |
| Frontend | Next.js, React, Tailwind, static export | Builds to plain files FastAPI can serve |
| CI | GitHub Actions | `lint-test`: ruff and pytest against the same Postgres image |

OHDSI's reference tools (ETL-Synthea, [DataQualityDashboard](https://github.com/OHDSI/DataQualityDashboard), CohortMethod) are written in R. This repo reimplements the needed parts in Python and uses the R tools as the correctness reference, not as dependencies.

## Design decisions

**Synthetic data only.** Synthea patients, generated ELN entries, and simulated genotypes. No real patient data, ever, and no clinical claims in code, docs, or the app.

**Reproducible builds.** Synthea runs with a fixed seed and reference date, and every synthetic release and genotype study is seeded. Rebuilding from a fresh clone reproduces the OMOP row counts, the data quality pass rate, and the trial table exactly.

**Checked against the reference.** The ETL against ETL-Synthea ([comparison](etl_synthea_comparison.md)), data quality against DataQualityDashboard ([comparison](dqd_comparison.md)), the GWAS against Hail, and every LLM extraction against a labeled set.

**Local first.** The platform began on AWS (Aurora, Bedrock, AgentCore, Cognito) and moved to Docker Compose on 2026-10-12, so anyone can run it without an AWS account. [SETUP.md](SETUP.md) records the AWS build.

## Known gaps

- **One database at a time.** The app reads the database `DB_NAME` names, so the ELN and data quality pages need the default database and the trial and synthetic data pages need the large one.
- **GWAS calibration.** On the current build the GWAS finds the planted effect, but genomic inflation on the chromosomes without it is 0.80, below what chance allows. See [genomics](modules/genomics.md#results).
- **Synthetic data fairness.** Fidelity is not measured by subgroup, and small groups are distorted most. See the [NIST AI RMF mapping](nist_ai_rmf.md#gaps-in-order-of-importance).
- **Release withdrawal.** There is no process to withdraw a synthetic release or notify its users.
- **Real data readiness.** What a controlled-access source would add is listed in [NIH and HHS requirements](nih_hhs_requirements.md#gaps-and-fixes).
