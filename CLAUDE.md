# CLAUDE.md

Operating file for `ehr-rwe-eln`. The platform is built and deployed; work now is the domain modules
below. Claude Code loads this file every session.

## How Claude Code must use this file

Follow the operating rules below. The infrastructure history, the build phases that produced it,
and the expected cost table live in `docs/SETUP.md`; runbooks are in `docs/INSTALL.md`.

## Project scope

Real world evidence from synthetic EHR data, linked to lab notebook records. Seven modules, one OMOP CDM v5.4 database:

| Module | Package | What it does |
|---|---|---|
| 1. EHR to RWE cohort pipeline | `ehr_rwe_eln.cohort` | Synthea patients to OMOP CDM v5.4; cohort definitions as YAML; analysis-ready cohort tables |
| 2. ELN to EHR bridge | `ehr_rwe_eln.eln` | LLM extraction of samples, assays, biomarkers, and results from ELN entries into typed models, then OMOP `specimen` and `measurement` rows plus FHIR `Specimen` and `Observation` resources |
| 4. Target trial emulation toolkit | `ehr_rwe_eln.tte` | Protocol spec in YAML (eligibility, strategies, time zero, outcomes) to cohort SQL, propensity score analysis, survival estimates, and a bias diagnostics report |
| 7. RWE data quality dashboard | `ehr_rwe_eln.dq` | Conformance, completeness, and plausibility checks (Kahn framework) over the OMOP tables, scored and shown in the frontend |
| Synthetic genomics | `ehr_rwe_eln.genomics` | A dbGaP-style genotyping study simulated with msprime for OMOP persons (VCF, PLINK, phenotype and sample tables), a planted genetic effect, and a GWAS checked against it; a clinical panel of real ClinVar variants at their GRCh38 positions, planted in the same synthetic people |
| Variant curation | `ehr_rwe_eln.curation` | ACMG/AMP criteria that data alone decides, with each gene's ClinGen expert panel thresholds, from gnomAD v4 frequencies and Ensembl VEP consequences; Bayesian points to a class; scored against ClinVar expert-panel classifications it never reads. Claude proposes literature evidence (PS3, BS3, PS4, PP1) from LitVar2 and PubTator3 text, each claim's PMID and quote verified in code; proposals never change a class. A curator accepts proposals and records the class, with who and when, on `/curation/`. Each study subject's conditions as HPO terms, scored against the panel genes and checked against the planted carriers |
| Synthetic data | `ehr_rwe_eln.synth` | Differentially private synthetic releases of the OMOP data (statistical and generative synthesizers), with fidelity, utility, and privacy risk reports and a provenance record per release |

Build order after the platform: 1, then 7, then 4, then 2. Each module depends on the OMOP tables from module 1.

### In progress since 2026-11-19: move to AWS

Decided 2026-11-19, reversing the local-first move below: the app runs on AWS (the `default` profile's account, `us-east-1`), with OMOP in a lakehouse. The plan, open items, and reasons are in `notes/TODO_IMPROVEMENTS.md` (`notes/` is gitignored: personal planning, `TODO.md`, the industry comparison). Six steps, one PR each; until a step lands, the local Docker Compose stack keeps running that part:

- [x] 1. `CLAUDE.md` and the Terraform foundation (`infra/terraform/`): VPC, S3 Tables lake, Lake Formation and Glue catalog, Redshift Serverless, Aurora Serverless v2, budget
- [x] 2. OMOP in the lake: the ETL still builds in a staging Postgres (decided 2026-11-19, stage then publish); `scripts/publish_omop.py` copies all 39 tables (60,890,645 rows) to Iceberg in S3 Tables, and `scripts/reconcile_lake.py` checks every column of every table through Redshift (1,038 checks, cohorts 550 and 885)
- [x] 3. OMOP readers on Redshift: trial emulation, synthetic data sources, and the genomics, curation, and ELN scripts read the lake through `connect_omop()` (Redshift Data API, `OMOP_SOURCE=staging` for the staging Postgres), in SQL that runs unchanged on both. `scripts/compare_omop_sources.py`: identical tables for 4 protocols, 14 negative controls, 2 synthetic specs. Decided 2026-11-19: OMOP writers (ETL, cohorts, ELN bridge) stay on staging and republish; data quality stays on staging until DQD in R (step 6)
- [ ] 4. App on ECS behind a load balancer, with Cognito auth
- [ ] 5. Bedrock (Claude Opus 4.6) replaces the Anthropic API; every eval re-runs
- [ ] 6. R and HADES, LangGraph for literature curation, then the genomics, curation, and synthetic data items in `notes/TODO_IMPROVEMENTS.md`

### Done 2026-10-12: run locally, no AWS (superseded 2026-11-19)

Goal: anyone can clone the repo, install it, and run every module on their own machine without an AWS account. It came before module 7 and changed the platform the remaining modules build on.

Decided 2026-10-12: PostgreSQL with pgvector replaces both DuckDB and Aurora (17 at first, to match Aurora; 18 since 2026-10-13). The app will have concurrent writers and large vector search (RAG), which DuckDB's single-writer file does not fit. It runs locally from `docker-compose.yml`, and tests run against that database.

- [x] `docker-compose.yml` with the database service
- [x] Port module 1 from DuckDB to Postgres. The 1,325,353-row reconciliation, the counts in `docs/etl_synthea_comparison.md`, and both cohorts reproduce exactly
- [x] CI runs the tests against a Postgres service container
- [x] Plan the move (agreed 2026-10-12): Anthropic API replaces Bedrock (each user brings `ANTHROPIC_API_KEY`); no auth, the app binds to 127.0.0.1; everything runs in Docker Compose (`db` plus one `app` container serving the API, agent, and static frontend). Dropped: Guardrail, AgentCore (Runtime, Gateway, Observability, Evaluations), S3, Secrets Manager, Cognito, Budgets, CDK. Work in four PRs:
  - [x] 1. Agent on the Anthropic API, served at `POST /agent`; evals run against it
  - [x] 2. Remove auth; FastAPI serves the frontend; `app` service in Compose
  - [x] 3. Delete `infra/`, the AWS scripts and dependencies; migrations run with plain Alembic
- [x] Rewrite "Stack decisions", "Conventions", and the README install steps for the local stack
- [x] Tear down the deployed AWS stacks (2026-10-12). `deploy.yml` and the `cdk-diff` CI job are gone; `lint-test` is the only required check

Data rules:
- Synthetic or openly licensed de-identified data only: Synthea output, the MIMIC-IV demo, and synthetic ELN entries generated in this repo. No real patient data, ever.
- OMOP vocabularies come from OHDSI Athena under their own licenses. Never commit vocabulary files or patient-level data; `data/` is gitignored.
- Public reference data is allowed: summary-level knowledge about variants and phenotypes, never individual-level data. Kept in `data/reference/`, never committed, each release named so a run can be repeated:
  - ClinVar (NCBI; no restrictions on use), from the dated GRCh38 VCF, checked against NCBI's md5.
  - gnomAD (CC0). Attribute it ("includes data from the gnomAD v4 release"), never attempt to reidentify participants, never put "gnomAD" in a tool's name, and skip its SpliceAI annotations (non-commercial license). The API allows about 10 requests a minute; cache every answer.
  - Ensembl VEP and lookup (no restrictions on use), cached per Ensembl release.
  - ClinGen curated content (CC0 1.0; attribute ClinGen with the date accessed): expert panel thresholds, transcribed into `curation/rules.yaml` with each panel's CSpec ID and version; ENIGMA's PVS1 table, generated into `curation/enigma_pvs1.yaml` by `scripts/import_enigma_pvs1.py`; ENIGMA's functional table, into `curation/enigma_functional.tsv` by `scripts/import_enigma_functional.py`; the Evidence Repository export, cached as `data/reference/clingen/erepo_YYYYMMDD.tsv`.
  - NCBI LitVar2 and PubTator3, for variant mentions and paper text (at most 3 requests a second). Paper text is the publishers' and authors': cached per variant under `data/reference/pubtator/`, never committed.
  - HPO, the Human Phenotype Ontology (its own license, read 2026-11-19 at human-phenotype-ontology.github.io/license.html; free to use, no commercial restriction). Three conditions: acknowledge and cite the HPO Consortium (Köhler et al., NAR 2014, doi:10.1093/nar/gkt1026); show the release date or version of every HPO file shown publicly; never alter the content or logical relationships of an HPO file (changes go to HPO's issue tracker). Pages and docs that use it say "This service/product is using the Human Phenotype Ontology (release YYYY-MM-DD). Find out more at http://www.human-phenotype-ontology.org". Keep `hp.obo` and the annotation files unmodified in `data/reference/hpo/<release>/`; derived tables (term sets, mappings, scores) are ours and name the release they came from. Not in the loaded Athena vocabularies.
- Every LLM extraction is validated against a typed Pydantic model and scored against a labeled set in `evals/`.
- Outputs are for research and demonstration. No clinical decision claims in code, docs, or UI.

Domain stack (additions to the platform stack below):

| Slot | Tool | Why |
|---|---|---|
| Synthetic EHR source | Synthea (CSV output) | Open standard synthetic patient generator. |
| Common data model | OMOP CDM v5.4 as Apache Iceberg tables in S3 Tables, queried through Redshift Serverless | The model is an OHDSI standard; OHDSI's DatabaseConnector supports Redshift. Postgres in Docker Compose until steps 2 and 3 land. |
| Interoperability format | FHIR R4 via `fhir.resources` | Language-level library; no FHIR server needed at this scale. |
| Causal inference and survival | scikit-learn, statsmodels, lifelines | Language-level libraries. |
| ELN source | Synthetic entries; eLabFTW API optional | Open-source ELN with a REST API. |

OHDSI reference implementations (ETL-Synthea, DataQualityDashboard, CohortMethod) are R. This repo reimplements the needed subset in Python and uses the R tools as the correctness reference, not as dependencies.

## Explain before you act

The maintainer is learning ML development on this project and does not have a solid ML background.
Before doing anything, explain what you are about to do and why.

1. Before any change that edits files, adds a dependency, or runs training, say in plain language what the step is and why it comes next.
2. Define ML terms the first time they come up (backbone, embedding, linear probe, epoch, loss, optimizer). One or two sentences each, no stacked jargon.
3. Point to the code: file and function, e.g. `src/ehr_rwe_eln/api/main.py:24`, so the maintainer can read along.
4. For every tool or library, say what job it does and why it was picked over the obvious alternative.
5. After a training or evaluation run, explain what the numbers mean and whether they are good.
6. This section overrides "skip preamble" and "no trailing summaries" below for ML concepts and decisions. Routine steps (installs, lint fixes, commits) stay terse.
7. Define acronyms always
8. The same applies to AWS and Terraform work (asked 2026-11-19): before each step, say what it creates and why it comes next, and define each AWS service the first time it comes up.

## Operating rules

Direct. Evidence-first. Skip preamble.

### Writing style
- Never use em dashes or en dashes in any written output. Use commas, periods,
semicolons, or restructure.
- Write in the maintainer's voice for all prose output. The voice profile is
`~/.claude/rules/writing-voice.md`. Read it; do not edit it. No generic LLM
prose.
- Keep all prose short and direct. State the point; skip "actually matters" style
framing.

### Core protocol
- Evidence: read files before stating facts about them. Verify data claims
against source.
- Action: default to implementation. Explain architecture decisions; act on
details.
- Output: no trailing summaries after actions. The maintainer reads diffs
directly.
- Safety: no force push. No `rm -rf`; use `trash`. Ask before bulk operations.
Never commit secrets, API keys, or credentials.
- Comms: never send email, messages, or any external communication without
showing a draft and getting explicit approval.
- Parallel: launch independent subagents in a single message when tasks are
independent. Delegate mechanical exploration; preserve main context for
decisions.


### Python
- Use `uv` for everything: `uv sync`, `uv run <cmd>`, `uv add <pkg>`. Never activate a venv manually; `uv run` handles it. Never use pip with `--break-system-packages`.
- Always `pyproject.toml`. Always a `.env.example` with every variable the app reads.
- Settings load through `pydantic-settings`. Secrets are `SecretStr`. Locally every setting and secret comes from `.env` (gitignored), never from the shell or a keychain. On AWS, ECS passes values from Secrets Manager into the container as environment variables; the code reads them the same way.
- Terraform values that differ per person (emails, ARNs) go in `terraform.tfvars` (gitignored); `terraform.tfvars.example` lists them. The state bucket name holds the account ID, so it is passed with `terraform init -backend-config="bucket=..."`, never written in the repo.

### Coding principles
- Don't add features, refactors, or improvements beyond what was asked.
- Don't add comments, docstrings, or type annotations to code you didn't change.
- No helpers or abstractions for one-time operations. Three similar lines beat a premature abstraction.
- Validate only at system boundaries (user input, external APIs). Trust internal code.
- When editing: match existing style, don't touch adjacent code, remove only what YOUR change made unused. Mention unrelated dead code; don't delete it.
- No OWASP top 10 vulnerabilities. Fix insecure code you wrote immediately.

## Stack decisions

AWS, from 2026-11-19: OMOP in a lakehouse (S3 Tables, Lake Formation, Redshift Serverless), app data in Aurora, the app on ECS, models on Bedrock, all defined in Terraform. Rows marked "until step N" describe what still runs locally until that step lands.

| Slot | Tool | Why |
|---|---|---|
| Models | Claude on Amazon Bedrock | Model access, permissions, and the bill stay in the AWS account; IAM auth, no API key. Anthropic API with `ANTHROPIC_API_KEY` until step 5. |
| Agent framework | Anthropic Python SDK, `client.beta.messages.tool_runner` | Runs the tool loop and returns typed output with no extra framework. `AnthropicBedrock` client from step 5. LangGraph for literature curation only (step 6). |
| Lake | S3 Tables (Apache Iceberg), AWS Glue Data Catalog, Lake Formation | Open table format any engine reads; Lake Formation controls who reads what. |
| Warehouse SQL | Redshift Serverless | The AWS engine OHDSI's DatabaseConnector supports; billed per second of query time, capped at 60 RPU-hours a month. |
| App database + vector | Aurora Serverless v2 PostgreSQL 18.6 + pgvector | Row-by-row app writes and vector search, which Redshift is not built for. Pauses to 0 when idle. Never holds OMOP. Compose Postgres until steps 2 to 4. |
| Secrets and settings | `pydantic-settings`; `.env` locally, Secrets Manager on AWS | One code path; database passwords are managed by RDS and Redshift in Secrets Manager. |
| Auth | Cognito | The app is public once hosted. None (127.0.0.1 only) until step 4. |
| App hosting | ECS behind a load balancer, in public subnets | No NAT gateway or interface endpoints, which would cost more than the whole budget. FastAPI serves the API under `/api` and the static frontend at `/`. Compose `app` container until step 4. |
| Infrastructure as code | Terraform, state in `ehr-rwe-eln-tfstate-<account>` | Same tool as methyl-flow's newest infra; `bootstrap/` made the state bucket, `foundation/` holds the shared resources. |
| Backend framework | FastAPI + Pydantic | Typed request and response models, OpenAPI for free. |
| Python toolchain | uv, ruff, pytest | Fast, one tool per job, lockfile pinned. |
| DB migrations | Alembic | Versioned schema changes; `uv run alembic upgrade head` against the Compose Postgres. |
| Dev-loop evals | pydantic-evals golden set in pytest | Scores the agent against the real model in seconds. |
| Frontend framework | Next.js + React + Tailwind, static export | Builds to plain files, so no Node server at runtime. |
| Code host + CI runner | GitHub + GitHub Actions | `lint-test` runs ruff and pytest against a Postgres service container. `secrets` runs gitleaks (pinned, checksum verified) over every commit and file for keys, tokens, passwords, usernames, and email addresses, with the rules in `.gitleaks.toml`. Both are required to merge; the same scan runs in pre-commit. |
| Containers | Docker + Docker Compose | Open standard; the whole stack starts with one command. |

Excluded on purpose (wrong scale for a personal project): Kubernetes, A2A, LiteLLM, dedicated vector databases, WAF-heavy perimeter builds, NAT gateways and interface endpoints (cost).

How each piece was built, verified, and what it costs: see `docs/SETUP.md`.

## Repository layout

```
.
├── CLAUDE.md              # this file
├── pyproject.toml         # project definition; uv.lock pins exact versions
├── .env.example           # every env var the app reads, no values
├── src/ehr_rwe_eln/       # application code, the only thing that ships
│   ├── cohort/            # module 1: Synthea to OMOP, cohort building
│   ├── eln/               # module 2: ELN extraction to OMOP and FHIR
│   ├── tte/               # module 4: target trial emulation
│   ├── dq/                # module 7: data quality checks
│   ├── genomics/          # synthetic genotypes and GWAS
│   └── synth/             # privacy-preserving synthetic data releases
├── tests/                 # fast tests; local services only (the Compose Postgres), nothing off the machine
├── migrations/            # Alembic versioned schema changes
├── infra/terraform/       # bootstrap/ (state bucket), foundation/ (network, lake, Redshift, Aurora, budget)
├── frontend/              # Next.js app, static export served by FastAPI
├── evals/                 # golden set; hits a real model, so slow and costs money
├── scripts/               # one-shot operational scripts, never imported
├── data/                  # local synthetic data and vocabularies, gitignored
├── docs/                  # long-form docs the README links to
├── notes/                 # personal planning (TODO.md, TODO_IMPROVEMENTS.md, INDUSTRY_COMPARISON.md), gitignored
└── .github/workflows/     # CI; GitHub reads this exact path only
```

What each directory is for, which of these are real conventions and which are choices, and why
`src/` exists at all: see `aws/LAYOUT.md` in [project-template](https://github.com/toddcreasy/project-template/blob/main/aws/LAYOUT.md).

## Conventions

- AWS resources are Terraform only, never created by hand in the console. Show `terraform plan` and get approval before every `apply`. Every resource carries the `project = ehr-rwe-eln` tag (provider default tags), which the budget filters on.
- Local dev still runs in `docker-compose.yml` until its parts move. Bind every published port to 127.0.0.1; there is no auth locally.
- One model: every call uses `MODEL`. Prompt caching on for any repeated prefix. Batch API (Bedrock batch inference from step 5) for offline jobs.

## Settled decisions

Do not re-ask. Rationale and history in `docs/SETUP.md`.

| Decision | Value |
|---|---|
| AWS account and region | The `default` AWS CLI profile (SSO, AdministratorAccess), `us-east-1`. Decided 2026-11-19 |
| AWS budget | $100 a month on resources tagged `project = ehr-rwe-eln`; email at 80% actual and 100% forecast. Decided 2026-11-19 |
| API key and spend limit (until step 5) | Personal key scoped to the `ehr-rwe-eln` workspace in the Claude Console, which carries the monthly spend limit. The key lives only in `.env` as `ANTHROPIC_API_KEY`. No macOS Keychain, no shell export: an exported variable would override `.env` |
| Python | 3.14, pinned in `.python-version` |
| Database | On AWS: OMOP only in the lake (Iceberg in S3 Tables, read through Redshift Serverless; "lake only", decided 2026-11-19); app state, module schemas, and pgvector in Aurora Serverless v2 PostgreSQL 18.6. Locally until steps 2 to 4: PostgreSQL 18 + pgvector 0.8.7, image `pgvector/pgvector:0.8.7-pg18-trixie`, defined in `docker-compose.yml` |
| App name | RWE Workbench, for the web app only; the repo and the Python package stay `ehr-rwe-eln`. Chosen 2026-11-19 over Counterpart, which collides with Counterpart Health (Clover Health's clinical AI company) |
| `MODEL` | From step 5: `us.anthropic.claude-opus-4-6-v1` on Bedrock, the newest Claude this account can call (tested 2026-11-19: Opus 5.5, 4.8, 4.7 return AccessDenied). Revisit when Opus 5.5 access opens. Until step 5: `claude-opus-5-5` on the Anthropic API, for every call |
| Data database | One: `ehr_rwe_eln`, 23,421 Synthea patients, every module. A second population would be a second CDM schema, never a second database. `ehr_rwe_eln_test` is for pytest only. Merged from two databases on 2026-11-18 |
