# CLAUDE.md

Operating file for `ehr-rwe-eln`. The platform is built and deployed on AWS; work now is the domain
modules below. Claude Code loads this file every session. How things got this way is in
`docs/HISTORY.md` (the reasoning) and `docs/SETUP.md` (the steps, numbers, and cost table); runbooks
are `docs/INSTALL.md` and `infra/terraform/README.md`. Open items are in
`notes/TODO_IMPROVEMENTS.md` (`notes/` is gitignored).

## Project scope

Real world evidence from synthetic EHR data, linked to lab notebook records. Seven modules, one OMOP CDM v5.4 database:

| Module | Package | What it does |
|---|---|---|
| 1. EHR to RWE cohort pipeline | `ehr_rwe_eln.cohort` | Synthea patients to OMOP CDM v5.4; cohort definitions as YAML; analysis-ready cohort tables |
| 2. ELN to EHR bridge | `ehr_rwe_eln.eln` | LLM extraction of samples, assays, biomarkers, and results from ELN entries into typed models, then OMOP `specimen` and `measurement` rows plus FHIR `Specimen` and `Observation` resources |
| 3. Target trial emulation toolkit | `ehr_rwe_eln.tte` | Protocol spec in YAML (eligibility, strategies, time zero, outcomes) to cohort SQL, propensity score analysis, survival estimates, and a bias diagnostics report |
| 4. RWE data quality dashboard | `ehr_rwe_eln.dq` | OHDSI DataQualityDashboard 2.9.1 (R): conformance, completeness, and plausibility checks (Kahn framework) over the OMOP tables in the lake, loaded into the `dq` schema and shown in the frontend |
| 5. Synthetic genomics | `ehr_rwe_eln.genomics` | A dbGaP-style genotyping study simulated with stdpopsim (three populations, out of Africa, each person's from their OMOP race) for OMOP persons (VCF, PLINK, phenotype and sample tables), a planted genetic effect, and a GWAS checked against it; a clinical panel of real ClinVar variants at their GRCh38 positions, planted in the same synthetic people |
| 6. Variant curation | `ehr_rwe_eln.curation` | ACMG/AMP criteria that data alone decides, with each gene's ClinGen expert panel thresholds, from gnomAD v4 frequencies and Ensembl VEP consequences; Bayesian points to a class; scored against ClinVar expert-panel classifications it never reads. Claude proposes literature evidence (PS3, BS3, PS4, PP1) from LitVar2 and PubTator3 text, each claim's PMID and quote verified in code; proposals never change a class. A curator accepts proposals and records the class, with who and when, on `/curation/`. Each study subject's conditions as HPO terms, scored against the panel genes and checked against the planted carriers |
| 7. Synthetic data | `ehr_rwe_eln.synth` | Differentially private synthetic releases of the OMOP data (statistical and generative synthesizers), with fidelity, utility, and privacy risk reports and a provenance record per release |

Each module depends on the OMOP tables from module 1.

## Settled decisions

Do not re-ask. Rationale in `docs/HISTORY.md`.

| Decision | Value |
|---|---|
| AWS account and region | The `default` AWS CLI profile (SSO, AdministratorAccess), `us-east-1` |
| AWS budget | $100 a month on resources tagged `project = ehr-rwe-eln`, credits excluded; email at 50% and 80% actual and 100% forecast |
| Public demo | No sign-in. `DAILY_TOKEN_LIMIT` 150,000 a day and 10 calls an hour per address on `/api/agent` (`api/limits.py`); `PUBLIC_DEMO=true` turns off curator decisions; one task; a daily token alarm. See `infra/terraform/README.md`, Public demo limits |
| `MODEL` | `us.anthropic.claude-opus-4-6-v1` on Bedrock, the newest Claude this account can call (Opus 5.5, 4.8, 4.7 returned AccessDenied on 2026-11-19). Revisit when Opus 5.5 access opens |
| Python | 3.14, pinned in `.python-version` |
| Databases | OMOP only in the lake (Iceberg in S3 Tables, read through Redshift Serverless). App state, module schemas, and pgvector in Aurora Serverless v2 PostgreSQL 18.6, which never holds OMOP. Locally (pytest, the ETL's staging OMOP, Compose): PostgreSQL 18 + pgvector 0.8.7, image `pgvector/pgvector:0.8.7-pg18-trixie` |
| Data database | One: `ehr_rwe_eln`, 23,421 Synthea patients, every module. A second population is a second CDM schema, never a second database. `ehr_rwe_eln_test` is for pytest only |
| App name | RWE Workbench, for the web app only; the repo and the Python package stay `ehr-rwe-eln` |

## Where things run

- OMOP: the ETL builds in a staging Postgres, `scripts/publish_omop.py` copies it to Iceberg in S3 Tables, and `scripts/reconcile_lake.py` checks every column through Redshift. Readers go through `connect_omop()` (the lake by default, `OMOP_SOURCE=staging` for the staging Postgres), in SQL that runs on both. Writers (ETL, cohorts, ELN bridge) write to staging and republish.
- Trial emulation: the Python `tte` analysis is the readable version behind `/tte`; CohortMethod (`r/run_cohortmethod.R`) is the OHDSI check, TrialEmulation (`r/run_trialemulation.R`) the per-protocol estimate.
- Heavy jobs (REGENIE, Exomiser, LIRICAL, BIAS-2015, synthetic releases) run as on-demand x86 Fargate tasks, images built by CodeBuild; nothing heavy runs in local Docker.
- OMOP MCP server: local only, over stdio (`agents/mcp_server.py`, `.mcp.json`); `/api/agent` calls the same functions in-process (`agents/omop_tools.py`). Counts are precomputed in Aurora (`omop_stats`), so public calls never reach Redshift; counts under 11 are suppressed and never stored. A Bedrock Guardrail checks every `/api/agent` call.
- Literature curation runs on LangGraph (`curation/literature_graph.py`), pausing for the curator; Claude through `propose()` and `claude_client()`, not `langchain-aws`.

## Data rules

- Synthetic or openly licensed de-identified data only: Synthea output, the MIMIC-IV demo, and synthetic ELN entries generated in this repo. No real patient data, ever.
- OMOP vocabularies come from OHDSI Athena under their own licenses. Never commit vocabulary files or patient-level data; `data/` is gitignored.
- Public reference data is allowed: summary-level knowledge about variants and phenotypes, never individual-level data. Kept in `data/reference/`, never committed, each release named so a run can be repeated:
  - ClinVar (NCBI; no restrictions on use), from the dated GRCh38 VCF, checked against NCBI's md5.
  - gnomAD (CC0). Attribute it ("includes data from the gnomAD v4 release"), never attempt to reidentify participants, never put "gnomAD" in a tool's name, and skip its SpliceAI annotations (non-commercial license). The API allows about 10 requests a minute; cache every answer.
  - Ensembl VEP and lookup (no restrictions on use), cached per Ensembl release.
  - ClinGen curated content (CC0 1.0; attribute ClinGen with the date accessed): expert panel thresholds, transcribed into `curation/rules.yaml` with each panel's CSpec ID and version; ENIGMA's PVS1 table, generated into `curation/enigma_pvs1.yaml` by `scripts/import_enigma_pvs1.py`; ENIGMA's functional table, into `curation/enigma_functional.tsv` by `scripts/import_enigma_functional.py`; the Evidence Repository export, cached as `data/reference/clingen/erepo_YYYYMMDD.tsv`.
  - LIRICAL (The Jackson Laboratory; non-commercial use only, no modification, not for diagnosis; read 2026-11-23). Run unmodified, phenotype only, in our private ECR image (`docker/lirical.Dockerfile`); never redistribute the image or claim a clinical result. Its data files are named in the Dockerfile and recorded in each run's `SHA256SUMS`.
  - NCBI LitVar2 and PubTator3, for variant mentions and paper text (at most 3 requests a second). Paper text is the publishers' and authors': cached per variant under `data/reference/pubtator/`, never committed.
  - HPO, the Human Phenotype Ontology (its own license, read 2026-11-19 at human-phenotype-ontology.github.io/license.html; free to use, no commercial restriction). Three conditions: acknowledge and cite the HPO Consortium (Köhler et al., NAR 2014, doi:10.1093/nar/gkt1026); show the release date or version of every HPO file shown publicly; never alter the content or logical relationships of an HPO file (changes go to HPO's issue tracker). Pages and docs that use it say "This service/product is using the Human Phenotype Ontology (release YYYY-MM-DD). Find out more at http://www.human-phenotype-ontology.org". Keep `hp.obo` and the annotation files unmodified in `data/reference/hpo/<release>/`; derived tables (term sets, mappings, scores) are ours and name the release they came from. Not in the loaded Athena vocabularies.
- Every LLM extraction is validated against a typed Pydantic model and scored against a labeled set in `evals/`.
- Outputs are for research and demonstration. No clinical decision claims in code, docs, or UI.

## Stack

All AWS resources in Terraform. Values that are settled are in the table above; this is what each tool does and why.

| Slot | Tool | Why |
|---|---|---|
| Synthetic EHR source | Synthea (CSV output) | Open standard synthetic patient generator. |
| Common data model | OMOP CDM v5.4 | OHDSI standard; OHDSI's DatabaseConnector supports Redshift. |
| Interoperability format | FHIR R4 via `fhir.resources` | Language-level library; no FHIR server needed at this scale. |
| Causal inference and survival | scikit-learn, statsmodels, lifelines | Language-level libraries. |
| ELN source | Synthetic entries; eLabFTW API optional | Open-source ELN with a REST API. |
| Models | Claude on Amazon Bedrock | Model access, permissions, and the bill stay in the AWS account; IAM auth (SSO locally, the task role on ECS), no API key. `anthropic` stays below 2: the 2.x releases send an API version Bedrock accepts only for Claude 4.7 and later. |
| Agent framework | Anthropic Python SDK, `client.beta.messages.tool_runner`, through `AnthropicBedrock` | Runs the tool loop and returns typed output with no extra framework. LangGraph for literature curation only, for its pause and resume around the curator; no LangChain. |
| Lake | S3 Tables (Apache Iceberg), AWS Glue Data Catalog, Lake Formation | Open table format any engine reads; Lake Formation controls who reads what. |
| Warehouse SQL | Redshift Serverless | The AWS engine DatabaseConnector supports; billed per second of compute, capped at 150 RPU-hours a month. An open Data API session is billed as compute until it ends, so `RedshiftSession` ends its session when its block ends. |
| App database + vector | Aurora Serverless v2 + pgvector | Row-by-row app writes and vector search, which Redshift is not built for. Pauses to 0 when idle. |
| Secrets and settings | `pydantic-settings`; `.env` locally, Secrets Manager on AWS | One code path; database passwords are managed by RDS and Redshift in Secrets Manager. |
| App hosting | ECS Express Mode, one x86 task in the public subnets, image in ECR tagged with its git commit | Express Mode builds the load balancer, HTTPS certificate, and URL; the public IP means no NAT gateway or interface endpoints, which would cost more than the whole budget. FastAPI serves the API under `/api` and the static frontend at `/`. Migrations and data copies go through an on-demand bastion task and an SSM tunnel. |
| Infrastructure as code | Terraform, state in `ehr-rwe-eln-tfstate-<account>` | `bootstrap/` made the state bucket, `foundation/` holds the shared resources, `app/` the rest. |
| Backend framework | FastAPI + Pydantic | Typed request and response models, OpenAPI for free. |
| Python toolchain | uv, ruff, pytest | Fast, one tool per job, lockfile pinned. |
| DB migrations | Alembic | `uv run alembic upgrade head` against the Compose Postgres locally, and against Aurora through the bastion tunnel. |
| Dev-loop evals | pydantic-evals golden set in pytest | Scores the agent against the real model before a deploy. Run by hand, never in CI (billed, needs Bedrock and local data); all of `evals/` takes about 6 minutes. |
| Frontend framework | Next.js + React + Tailwind, static export | Builds to plain files, so no Node server at runtime. |
| Code host + CI runner | GitHub + GitHub Actions | `lint-test` runs ruff and pytest against a Postgres service container. `secrets` runs gitleaks (pinned, checksum verified) over every commit and file for keys, tokens, passwords, usernames, and email addresses, with the rules in `.gitleaks.toml`; the same scan runs in pre-commit. `terraform` checks formatting, validates each stack, and runs tflint and trivy. All three are required to merge. |
| Containers | Docker + Docker Compose | Open standard; the whole stack starts with one command. |
| Heavy jobs | On-demand x86 Fargate tasks (`docker/*.Dockerfile`, `infra/terraform/app/`), images built by CodeBuild, started by `scripts/run_*.py` | Long or memory-hungry runs leave the laptop; billed only while a task runs. x86 because REGENIE ships no ARM build. |
| OHDSI HADES | R 4.6.1 + Java 21 in `docker/hades.Dockerfile`, run with `scripts/hades.py` | OHDSI's reference tools (ETL-Synthea, DataQualityDashboard, CohortMethod) are R; the repo runs them where R is the standard, against the lake. The Python ETL stays: it is verified against ETL-Synthea and fixes two of its bugs. HADES comes from OHDSI's r-universe, which serves only the latest builds, so no renv lockfile: CRAN is pinned by a dated snapshot, installed versions are recorded in `r/installed-versions.txt`, and the image is the artifact. Redshift over JDBC through the bastion tunnel with a temporary IAM password; no stored Redshift password. |

Excluded on purpose (wrong scale for a personal project): Kubernetes, A2A, LiteLLM, dedicated vector databases, WAF-heavy perimeter builds, NAT gateways and interface endpoints (cost).

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
- Write all prose in the maintainer's voice: `~/.claude/rules/writing-voice.md`. Read it; do not
edit it. No em dashes or en dashes. Short and direct; skip "actually matters" style framing.

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

## Conventions

- AWS resources are Terraform only, never created by hand in the console. Show `terraform plan` and get approval before every `apply`. Every resource carries the `project = ehr-rwe-eln` tag (provider default tags), which the budget filters on.
- Local dev runs in `docker-compose.yml`. Bind every published port to 127.0.0.1; there is no auth locally, and `PUBLIC_DEMO` stays off.
- Any route that writes records or spends money is either bounded (like `/api/agent`) or guarded by `not_in_public_demo` before it ships: the deployed app has no sign-in.
- One model: every call uses `MODEL`, through `claude_client()`, with `thinking=THINKING` (adaptive; Opus 4.6 does not think unless asked). Prompt caching on for any repeated prefix. Offline jobs run as direct calls a few at a time: Bedrock has no Message Batches API.

## Repository layout

Standard `src/` layout ([project-template](https://github.com/toddcreasy/project-template/blob/main/aws/LAYOUT.md) explains it). The parts that are not obvious:

- `src/ehr_rwe_eln/` is the only code that ships; one package per module.
- `tests/` use local services only (the Compose Postgres), nothing off the machine. `evals/` hit a real model: slow, billed, never in plain `uv run pytest`.
- `scripts/` are one-shot operational scripts, never imported.
- `r/` holds the HADES scripts, run in the `hades` container; `docker/` the Dockerfiles for hades, hail, and the Fargate tasks.
- `infra/terraform/`: `bootstrap/` (state bucket), `foundation/` (network, lake, Redshift, Aurora, budget), `app/` (ECR, ECS, CodeBuild, Fargate tasks, Guardrail, alarms).
- `data/` (synthetic data, vocabularies, reference data) and `notes/` (personal planning) are gitignored.
