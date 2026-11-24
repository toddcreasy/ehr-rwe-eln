# Architecture

How the pieces fit, why each tool fills its slot, and what is still missing. Setup is in [INSTALL.md](INSTALL.md); the build history, from the first AWS build through the local-first months to the move back to AWS, is in [SETUP.md](SETUP.md). Terms are defined in the [glossary](GLOSSARY.md).

<a href="https://toddcreasy.github.io/ehr-rwe-eln/architecture.svg"><img src="architecture.svg" alt="ehr-rwe-eln architecture. Top, AWS: a browser reaches RWE Workbench on ECS Express Mode, which reads and writes Aurora Serverless v2 and calls Claude on Amazon Bedrock behind a Guardrail. The OMOP tables are Iceberg in S3 Tables, read through Redshift Serverless; on-demand Fargate tasks (gwas, exomiser, lirical, bias, synth, monitor, bastion) read it. CodeBuild builds every image into ECR; a budget, alarms, and CloudTrail watch the account. Below, the laptop: the Compose Postgres where the ETL builds OMOP before it is published to the lake, the hades container with OHDSI's R tools reaching Redshift through the bastion, scripts that start every job, a Hail container, and the MCP server for Claude Code. Middle: Synthea output and Athena vocabularies feed the cohort pipeline, which builds the OMOP tables. Data quality, target trial emulation, synthetic data, and synthetic genomics read OMOP and write their results to Aurora or files. The ELN bridge sends free-text entries to Claude and writes specimen and measurement rows into OMOP and a FHIR R4 bundle. Variant curation classifies the genomics panel's variants, with literature evidence proposed by Claude, and a curator decides. Bottom: pre-commit, pull requests, GitHub Actions, pytest, and evals." width="100%"></a>

Click the diagram for [the interactive version](https://toddcreasy.github.io/ehr-rwe-eln/architecture.svg): hover a box for what it does and why, and click it for its source or docs. `uv run python scripts/make_diagrams.py` redraws it.

## Contents

1. [Where the data lives](#where-the-data-lives)
2. [How data moves](#how-data-moves)
3. [Where things run](#where-things-run)
4. [The app](#the-app)
5. [Where Claude is used](#where-claude-is-used)
6. [Stack](#stack)
7. [Design decisions](#design-decisions)
8. [Known gaps](#known-gaps)

## Where the data lives

Every module reads or writes one [OMOP CDM v5.4](https://ohdsi.github.io/CommonDataModel/cdm54.html) database (the Observational Medical Outcomes Partnership Common Data Model, the standard schema [OHDSI](https://www.ohdsi.org) tools expect). OMOP gives every diagnosis, drug, and lab test a standard concept, so a cohort definition, a data quality check, or a trial protocol written against it runs on any OMOP database.

The data comes from a 23,421-person [Synthea](https://github.com/synthetichealth/synthea) run. That size gives trial emulation enough outcome events for an estimate. It lives in two places:

- **OMOP, in the lake.** The OMOP tables are [Apache Iceberg](https://iceberg.apache.org) tables in an [S3 table bucket](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-tables.html), namespace `cdm`, cataloged in AWS Glue, with Lake Formation granting each reader its tables. Everything reads them through Redshift Serverless, in SQL that also runs on Postgres (`connect_omop()` in `src/ehr_rwe_eln/omop.py`). A second patient population would be a second CDM namespace, not a second database.
- **Module results, in Aurora.** Aurora Serverless v2 PostgreSQL 18.6 holds each module's results in its own schema (`dq`, `tte`, `eln`, `synth`, `curation`) and the app's state (`omop_stats`, `agent`). [Alembic](https://alembic.sqlalchemy.org) migrations create them. Aurora never holds OMOP.

<a href="https://toddcreasy.github.io/ehr-rwe-eln/schema.svg"><img src="schema.svg" alt="The project's data. Left, the lake's cdm namespace: clinical tables keyed to person (person, observation_period, death, visit_occurrence, condition_occurrence, drug_exposure, procedure_occurrence, measurement, observation, device_exposure, specimen, fact_relationship), derived tables (condition_era, drug_era, cohort, cdm_source), and Athena vocabulary tables keyed to concept. Right, the Aurora schemas with their foreign keys: dq.result to dq.run, tte.report to tte.run, eln.extraction to eln.entry, eln.subject, synth.row and synth.report to synth.release, curation.assessment and curation.proposal to curation.run, curation.decision to curation.assessment, curation.phenotype and curation.exomiser on their own, synth.monitor_run, synth.distribution, omop_stats, and agent.daily_usage. Below, on the laptop: the Compose Postgres for ETL staging and pytest, and the files under data/ for genomics, registries, ELN entries and FHIR, and synthetic data cards." width="100%"></a>

Click the diagram for [the interactive version](https://toddcreasy.github.io/ehr-rwe-eln/schema.svg): hover a table for what it holds, and click it for its OMOP definition or the migration that creates it.

On the laptop, a Postgres in Docker Compose holds two databases: `ehr_rwe_eln`, the ETL's staging copy of OMOP, and `ehr_rwe_eln_test`, where pytest writes and rolls back. Setting `OMOP_SOURCE=staging` points the readers at the staging copy instead of the lake. The ETL-Synthea and DataQualityDashboard comparisons were run on a separate 1,172-person Synthea run from the same fixed seed.

## How data moves

The cohort pipeline turns Synthea CSV files into OMOP tables in the staging Postgres, mapping each source code to its standard concept with the [Athena](https://athena.ohdsi.org) vocabularies. The ETL was checked table by table against OHDSI's own [ETL-Synthea](https://github.com/OHDSI/ETL-Synthea) on the same input; every difference is explained, and two of them are bugs in ETL-Synthea ([comparison](etl_synthea_comparison.md)). `scripts/publish_omop.py` copies the tables to the lake, and `scripts/reconcile_lake.py` checks every column of every table through Redshift.

Three modules only read OMOP. Data quality runs 2,384 checks and loads the results into Aurora. Trial emulation builds an analysis table per protocol and stores a bias report. The synthetic data module builds a source table from OMOP and stores differentially private copies of it.

Two write back. The ELN bridge reads free-text lab notebook entries, has Claude extract samples and results, and writes them as `specimen` and `measurement` rows, linked to the right person through a study subject registry. The genomics module draws people from OMOP for a simulated genotype study, writes the study as files, and writes the clinical panel's carriers back as `measurement` rows. Writers write to staging, and the tables are published again, so the lake is always a copy of a checked build.

## Where things run

- **The app** runs on ECS Express Mode: one x86 task, built by CodeBuild and tagged with its git commit.
- **Heavy jobs** run as on-demand x86 Fargate tasks, each from its own image built by CodeBuild: `gwas` (PLINK 2 and REGENIE), `exomiser`, `lirical`, `bias` (BIAS-2015), and `synth` (synthetic releases and their reports). A `scripts/run_*.py` script on the laptop builds the image if needed, starts the tasks, waits, and downloads the results. Nothing heavy runs in local Docker.
- **The privacy monitor** runs as a Fargate task every day at 11:00 UTC, started by EventBridge Scheduler.
- **OHDSI's R tools** (DataQualityDashboard, CohortMethod, TrialEmulation) run in the `hades` container on the laptop. `scripts/hades.py` starts the `bastion` task, opens a Systems Manager tunnel to Redshift, and connects over JDBC with a one-hour IAM password, so no Redshift password is stored anywhere.
- **Scripts** run on the laptop with `uv run python scripts/<name>.py`. A Redshift Data API session is billed until it ends, so `RedshiftSession` ends it when its `with` block ends, and long computations run after the block.

Every AWS resource is in Terraform (`infra/terraform/`): `bootstrap/` for the state bucket, `foundation/` for the network, lake, Redshift, Aurora, budget, and audit trail, and `app/` for the rest. Details and costs are in the [infrastructure README](../infra/terraform/README.md).

## The app

The app is called RWE Workbench. One container runs [FastAPI](https://fastapi.tiangolo.com): the API under `/api` and the frontend at `/`. The frontend is a [Next.js](https://nextjs.org) static export: `npm run build` turns it into HTML and JavaScript files, so no Node server runs. The home page shows the sections as tabs, each with a live figure from its own API, and every page shares a header and a strip linking the sections.

| Page | Shows | API |
|---|---|---|
| `/dq/` | Data quality runs, by check and table | `/api/dq/runs` |
| `/tte/` | Bias reports per trial protocol | `/api/tte/runs` |
| `/eln/` | Each ELN entry beside what was extracted | `/api/eln/entries` |
| `/synth/` | Synthetic releases compared, with their data cards | `/api/synth/releases` |
| `/curation/` | Each variant's evidence, criteria, literature proposals, and phenotype context; the curator's decision, with who and when | `/api/curation/runs` |

It is a public demo with no sign-in, bounded instead: `/api/agent` has a daily token limit and 10 calls an hour per address, `PUBLIC_DEMO=true` turns off curator decisions, there is one task, and CloudWatch alarms email on token use, errors, and Guardrail interventions. See [Public demo limits](../infra/terraform/README.md#public-demo-limits).

## Where Claude is used

Three places, all on Claude Opus 4.6 through [Amazon Bedrock](https://docs.claude.com/en/docs/build-with-claude/claude-on-amazon-bedrock) (the Anthropic SDK's `AnthropicBedrock` client, IAM credentials, no API key), set by one `MODEL` setting:

- **ELN extraction** (`src/ehr_rwe_eln/eln/`). Structured outputs constrain each reply to the extraction schema, and [Pydantic](https://docs.pydantic.dev) validates it before anything is stored. Bedrock has no Message Batches API, so offline runs make direct calls a few at a time.
- **Literature evidence for variant curation** (`src/ehr_rwe_eln/curation/literature.py`). Claude proposes ACMG criteria from passages that name the variant, each with a PMID and a quote that code checks against what was sent. The run is a [LangGraph](https://langchain-ai.github.io/langgraph/) graph (`curation/literature_graph.py`) that pauses for the curator. Its checkpoints hold passages of publishers' text, so they stay in the laptop's database (the `langgraph` schema) and are never copied to Aurora. Proposals change nothing until a curator accepts them on `/curation/`.
- **The agent** at `POST /api/agent` (`src/ehr_rwe_eln/agents/workbench.py`), on the Anthropic SDK's tool runner, with four read-only tools (`agents/omop_tools.py`): concept search and per-concept person counts from `omop_stats` (precomputed by `scripts/build_omop_stats.py`, counts under 11 suppressed, so public calls never reach Redshift), and the newest trial emulation and data quality results. A Bedrock Guardrail checks every call. Claude Code gets the same tools from a local MCP server over stdio (`agents/mcp_server.py`, configured in `.mcp.json`); nothing serves MCP on the public demo.

All three are scored by evals in `evals/` against the real model. They are slow and billed, so they run by hand, never in CI.

## Stack

| Slot | Tool | Why |
|---|---|---|
| OMOP | Apache Iceberg in S3 Tables, AWS Glue Data Catalog, Lake Formation | An open table format any engine reads; Lake Formation controls who reads what |
| Warehouse SQL | Redshift Serverless | The AWS engine OHDSI's DatabaseConnector supports; billed per second, capped at 150 RPU-hours a month |
| App database | Aurora Serverless v2 PostgreSQL 18.6 + [pgvector](https://github.com/pgvector/pgvector) | Row-by-row app writes and vector search, which Redshift is not built for; pauses to zero when idle |
| Local database | PostgreSQL 18 + pgvector in [Docker Compose](https://docs.docker.com/compose/) | ETL staging and tests, on the same engine as Aurora |
| App hosting | ECS Express Mode, one x86 task | Builds the load balancer, certificate, and URL; a public IP, so no NAT gateway |
| Heavy jobs | Fargate tasks, images built by CodeBuild into ECR | Billed only while a task runs; x86 because REGENIE ships no ARM build |
| Infrastructure | Terraform | Every resource in code, with a plan to review before each change |
| Migrations | Alembic | Versioned schema changes for the Aurora schemas |
| Python | 3.14, uv, ruff, pytest | One fast tool per job, versions pinned in `uv.lock` |
| Model | Claude Opus 4.6 on Amazon Bedrock | IAM auth and the AWS bill, no API key; one model for every call. Opus 5.5 is not enabled for this account |
| Agent framework | Anthropic Python SDK tool runner; LangGraph for literature curation only | The tool loop with typed output and no extra framework; LangGraph for pausing and resuming around the curator |
| OHDSI tools | DataQualityDashboard, CohortMethod, TrialEmulation (R, HADES) | OHDSI's standard implementations, run against the lake |
| Causal inference and survival | [scikit-learn](https://scikit-learn.org), [statsmodels](https://www.statsmodels.org), [lifelines](https://lifelines.readthedocs.io) | Propensity scores, Cox models, Kaplan-Meier |
| Differential privacy | [diffprivlib](https://github.com/IBM/differential-privacy-library), [Opacus](https://opacus.ai), [mbi](https://github.com/ryan112358/private-pgm) | Noisy histograms with a budget accountant; DP-SGD for the autoencoder; MST and AIM |
| Genomics | [stdpopsim](https://popsim-consortium.github.io/stdpopsim-docs/) on [msprime](https://tskit.dev/msprime/), [PLINK 2](https://www.cog-genomics.org/plink/2.0/), [REGENIE](https://rgcgithub.github.io/regenie/), [Hail](https://hail.is), [ClinVar](https://www.ncbi.nlm.nih.gov/clinvar/), [gnomAD](https://gnomad.broadinstitute.org) | Coalescent simulation of three human populations; PLINK 2 QC and principal components and REGENIE, the GWAS, on Fargate; Hail as the cross-check; real variants and their population frequencies for the clinical panel |
| Variant curation | [Ensembl VEP](https://rest.ensembl.org), [gnomAD](https://gnomad.broadinstitute.org), [ClinGen CSpec](https://cspec.genome.network); [BIAS-2015](https://github.com/bitscopic/BIAS-2015), [Exomiser](https://github.com/exomiser/Exomiser), [LIRICAL](https://github.com/TheJacksonLaboratory/LIRICAL) as comparisons | Consequences on the MANE Select transcript; population frequencies; each gene's expert panel thresholds; open tools to compare the rules and phenotype scores with |
| Interoperability | `fhir.resources` | [FHIR R4](https://hl7.org/fhir/R4/) models in Python, no FHIR server needed at this scale |
| API | FastAPI + Pydantic | Typed requests and responses |
| Frontend | Next.js, React, Tailwind, static export | Builds to plain files FastAPI can serve |
| CI | GitHub Actions | `lint-test`: ruff and pytest against the same Postgres image. `secrets`: [gitleaks](https://github.com/gitleaks/gitleaks) over every commit and file for keys, tokens, passwords, usernames, and email addresses (`.gitleaks.toml`). `terraform`: formatting, validation, tflint, and trivy for each stack. All three required to merge |

The Python ETL stays rather than OHDSI's R ETL-Synthea: it is checked against ETL-Synthea and fixes two of its bugs. Where the R tool is the standard, the repo runs it: DataQualityDashboard is the data quality module, CohortMethod checks the trial emulation, and TrialEmulation gives the per-protocol estimate.

## Design decisions

**Synthetic data only.** Synthea patients, generated ELN entries, and simulated genotypes. No real patient data, ever, and no clinical claims in code, docs, or the app.

**Reproducible builds.** Synthea runs with a fixed seed and reference date, and every synthetic release and genotype study is seeded. Rebuilding from a fresh clone reproduces the OMOP row counts, the data quality pass rate, and the trial table exactly. Each Fargate task's image tag is a hash of its Dockerfile and task script, and tags are immutable, so the image is the record of what ran.

**Checked against the reference.** The ETL against ETL-Synthea ([comparison](etl_synthea_comparison.md)), the lake against the staging build column by column, data quality as DataQualityDashboard itself (which matched the earlier Python port check for check, [comparison](dqd_comparison.md)), the trial emulation against CohortMethod, the GWAS against Hail, and every LLM extraction against a labeled set.

**On AWS, within a budget.** The platform began on AWS, moved to Docker Compose on 2026-10-12, and moved back to AWS from 2026-11-19 to 2026-11-23, with OMOP in a lakehouse ([SETUP.md](SETUP.md) has both moves). Spending is capped by a $100 monthly budget, Redshift's usage limit, on-demand tasks, and no NAT gateway or interface endpoints, which would cost more than the whole budget.

## Known gaps

- **Real data readiness.** The code refuses the risky steps on a controlled-access source until the approvals exist (privacy attacks, sharing beyond approved users, seeded noise). What remains is an institutionally attested environment under NIST SP 800-171, which a public demo account without sign-in cannot provide. See [NIH and HHS requirements](nih_hhs_requirements.md#gaps-and-fixes).
