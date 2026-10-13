# CLAUDE.md

Operating file for `ehr-rwe-eln`. The platform is built and deployed; work now is the domain modules
below. Claude Code loads this file every session.

## How Claude Code must use this file

Follow the operating rules below. The infrastructure history, the build phases that produced it,
and the expected cost table live in `docs/SETUP.md`; runbooks are in the README.

## Project scope

Real world evidence from synthetic EHR data, linked to lab notebook records. Four modules, one OMOP CDM v5.4 database:

| Module | Package | What it does |
|---|---|---|
| 1. EHR to RWE cohort pipeline | `ehr_rwe_eln.cohort` | Synthea patients to OMOP CDM v5.4; cohort definitions as YAML; analysis-ready cohort tables |
| 2. ELN to EHR bridge | `ehr_rwe_eln.eln` | LLM extraction of samples, assays, biomarkers, and results from ELN entries into typed models, then OMOP `specimen` and `measurement` rows plus FHIR `Specimen` and `Observation` resources |
| 4. Target trial emulation toolkit | `ehr_rwe_eln.tte` | Protocol spec in YAML (eligibility, strategies, time zero, outcomes) to cohort SQL, propensity score analysis, survival estimates, and a bias diagnostics report |
| 7. RWE data quality dashboard | `ehr_rwe_eln.dq` | Conformance, completeness, and plausibility checks (Kahn framework) over the OMOP tables, scored and shown in the frontend |

Build order after the platform: 1, then 7, then 4, then 2. Each module depends on the OMOP tables from module 1.

### TODO before module 7: run locally, no AWS

Goal: anyone can clone the repo, install it, and run every module on their own machine without an AWS account. This comes before module 7 and changes the platform the remaining modules build on.

Decided 2026-10-12: PostgreSQL 17 with pgvector replaces both DuckDB and Aurora. The app will have concurrent writers and large vector search (RAG), which DuckDB's single-writer file does not fit. It runs locally from `docker-compose.yml`, and tests run against that database.

- [x] `docker-compose.yml` with the database service
- [x] Port module 1 from DuckDB to Postgres. The 1,325,353-row reconciliation, the counts in `docs/etl_synthea_comparison.md`, and both cohorts reproduce exactly
- [x] CI runs the tests against a Postgres service container
- [x] Plan the move (agreed 2026-10-12): Anthropic API replaces Bedrock (each user brings `ANTHROPIC_API_KEY`); no auth, the app binds to 127.0.0.1; everything runs in Docker Compose (`db` plus one `app` container serving the API, agent, and static frontend). Dropped: Guardrail, AgentCore (Runtime, Gateway, Observability, Evaluations), S3, Secrets Manager, Cognito, Budgets, CDK. Work in four PRs:
  - [x] 1. Agent on the Anthropic API, served at `POST /agent`; evals run against it
  - [x] 2. Remove auth; FastAPI serves the frontend; `app` service in Compose
  - [ ] 3. Delete `infra/`, the AWS scripts and dependencies; migrations run with plain Alembic
- [ ] Rewrite "Stack decisions", "Conventions", and the README install steps for the local stack
- [x] Tear down the deployed AWS stacks (2026-10-12, README runbook). `deploy.yml` and the `cdk-diff` CI job are gone; `lint-test` is the only required check

Data rules:
- Synthetic or openly licensed de-identified data only: Synthea output, the MIMIC-IV demo, and synthetic ELN entries generated in this repo. No real patient data, ever.
- OMOP vocabularies come from OHDSI Athena under their own licenses. Never commit vocabulary files or patient-level data; `data/` is gitignored.
- Every LLM extraction is validated against a typed Pydantic model and scored against a labeled set in `evals/`.
- Outputs are for research and demonstration. No clinical decision claims in code, docs, or UI.

Domain stack (additions to the platform stack below):

| Slot | Tool | AWS? | If not AWS, why |
|---|---|---|---|
| Synthetic EHR source | Synthea (CSV output) | No | Open standard synthetic patient generator. AWS has no equivalent. |
| Common data model | OMOP CDM v5.4 on PostgreSQL 17 + pgvector | No | The model is an OHDSI standard; Postgres hosts it, locally in Docker Compose. |
| Interoperability format | FHIR R4 via `fhir.resources` | No | Language-level library. AWS HealthLake costs too much at personal scale. |
| Causal inference and survival | scikit-learn, statsmodels, lifelines | No | Language-level libraries. |
| ELN source | Synthetic entries; eLabFTW API optional | No | Open-source ELN with a REST API. AWS makes no ELN. |

OHDSI reference implementations (ETL-Synthea, DataQualityDashboard, CohortMethod) are R. This repo reimplements the needed subset in Python and uses the R tools as the correctness reference, not as dependencies.

## Explain before you act

The maintainer is learning ML development on this project and does not have a solid ML background.
Before doing anything, explain what you are about to do and why.

1. Before any change that edits files, adds a dependency, or runs training, say in plain language what the step is and why it comes next.
2. Define ML terms the first time they come up (backbone, embedding, linear probe, epoch, loss, optimizer). One or two sentences each, no stacked jargon.
3. Point to the code: file and function, e.g. `infra/stacks/data_stack.py:24`, so the maintainer can read along.
4. For every tool or library, say what job it does and why it was picked over the obvious alternative.
5. After a training or evaluation run, explain what the numbers mean and whether they are good.
6. This section overrides "skip preamble" and "no trailing summaries" below for ML concepts and decisions. Routine steps (installs, lint fixes, commits) stay terse.
7. Define acronyms always

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
- Settings load through `pydantic-settings`. Secrets are `SecretStr`. Locally they come from `.env`; deployed they come from AWS Secrets Manager or SSM. `.env` is gitignored.

### Coding principles
- Don't add features, refactors, or improvements beyond what was asked.
- Don't add comments, docstrings, or type annotations to code you didn't change.
- No helpers or abstractions for one-time operations. Three similar lines beat a premature abstraction.
- Validate only at system boundaries (user input, external APIs). Trust internal code.
- When editing: match existing style, don't touch adjacent code, remove only what YOUR change made unused. Mention unrelated dead code; don't delete it.
- No OWASP top 10 vulnerabilities. Fix insecure code you wrote immediately.

## Stack decisions

AWS-first. Anything not AWS is listed with the reason AWS cannot fill the slot.

| Slot | Tool | AWS? | If not AWS, why |
|---|---|---|---|
| Infrastructure as code | AWS CDK (Python) | Yes | |
| Models | Amazon Bedrock (Claude family) | Yes | |
| Agent framework | Strands Agents SDK | Yes (AWS open source) | |
| Agent runtime | Bedrock AgentCore Runtime | Yes | |
| Tool access (MCP) | AgentCore Gateway | Yes | |
| Agent observability | AgentCore Observability + CloudWatch | Yes | |
| Production evals | AgentCore Evaluations | Yes | |
| Relational + vector DB | PostgreSQL 17 + pgvector, in Docker Compose | No | Runs anywhere Docker does, so people can install the project without AWS. Concurrent writes and pgvector for RAG. Replaces Aurora Serverless v2 (see the TODO under Project scope). |
| Object storage | S3 | Yes | |
| Secrets | AWS Secrets Manager | Yes | |
| Auth | Amazon Cognito | Yes | |
| Backend hosting | Amazon ECS Express Mode on Fargate (alt: Lambda + API Gateway) | Yes | |
| Frontend hosting | AWS Amplify Hosting | Yes | |
| Cost control | AWS Budgets + cost allocation tags | Yes | |
| Backend framework | FastAPI + Pydantic | No | Language-level tooling. AWS makes no Python web framework. |
| Python toolchain | uv, ruff, pytest | No | Language ecosystem tools. No AWS equivalent exists. |
| DB migrations | Alembic | No | AWS has no schema migration tool for application tables. |
| Dev-loop evals | pydantic-evals golden set in pytest | No | AgentCore Evaluations scores deployed traces. Pre-deploy evals must run locally in seconds. Both are used. |
| Frontend framework | Next.js + React + Tailwind | No | AWS hosts frontends (Amplify) but does not make a frontend framework. |
| Code host + CI runner | GitHub + GitHub Actions | No | The repo lives on GitHub. Actions integrates natively, has a free tier, and assumes an AWS role via OIDC with no stored keys. AWS CodePipeline would add setup and cost for no benefit at this scale. |
| Containers | Docker | No | Open standard. AWS consumes it; it does not replace it. |

Excluded on purpose (wrong scale for a personal project): Kubernetes, Terraform, Snowflake, Databricks, A2A, LiteLLM, dedicated vector databases, WAF-heavy perimeter builds.

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
│   └── dq/                # module 7: data quality checks
├── tests/                 # fast tests; local services only (the Compose Postgres), nothing off the machine
├── infra/                 # CDK app: app.py + stacks/
├── migrations/            # Alembic versioned schema changes
├── frontend/              # Next.js app (Phase 7)
├── evals/                 # golden set; hits a real model, so slow and costs money
├── scripts/               # one-shot operational scripts, never imported
├── data/                  # local synthetic data and vocabularies, gitignored
├── docs/                  # long-form docs the README links to
└── .github/workflows/     # CI; GitHub reads this exact path only
```

What each directory is for, which of these are real conventions and which are choices, and why
`src/` exists at all: see `aws/LAYOUT.md` in [project-template](https://github.com/toddcreasy/project-template/blob/main/aws/LAYOUT.md).

## Conventions

- One CDK app in `infra/`, one stack per phase concern: `NetworkStack`, `DataStack`, `BackendStack`, `AgentStack`, `FrontendStack`, `OpsStack`.
- Tag every resource: `project=ehr-rwe-eln`, `env=dev`, `managed-by=cdk`.
- One AWS region: `us-east-1`. Do not spread resources across regions.
- Model tiering: default to the small Bedrock model tier (Haiku class) for extraction, filtering, and routing. Use the large tier only for final synthesis. Prompt caching on for any repeated prefix. Batch API for offline jobs.
- Log retention: 30 days on every log group. Set it explicitly; the default is forever.

## AWS environment

- Account `123456789012`, region `us-east-1`. Credentials come from IAM Identity Center (`https://example.awsapps.com/start`, permission set `AdministratorAccess`) and expire. On `ExpiredToken` or `Unable to locate credentials`, ask the maintainer to run `aws sso login`. Do not try to re-authenticate non-interactively.
- Other projects (glia-nav, nf-multiomics) share this account. This project's stacks are `ehr-rwe-eln-<Stack>`; the bare stack names belong to glia-nav. Never touch resources not tagged `project=ehr-rwe-eln`.
- The `ehr-rwe-eln-*` stacks were destroyed on 2026-10-12. Nothing deploys on merge; branch protection requires `lint-test` only.

## Settled decisions

Do not re-ask. Rationale and history in `docs/SETUP.md`.

| Decision | Value |
|---|---|
| API key and spend limit | Personal key scoped to the `ehr-rwe-eln` workspace in the Claude Console, which carries the monthly spend limit. The key lives in macOS Keychain (`anthropic-api-key`) and `~/.zshrc` exports it as `ANTHROPIC_API_KEY` |
| Python | 3.14, pinned in `.python-version` |
| Database | PostgreSQL 17 + pgvector 0.8.7, image `pgvector/pgvector:0.8.7-pg17-trixie`, defined in `docker-compose.yml` |
| `MODEL_SMALL` | `claude-haiku-5-5` on the Anthropic API. Probed 2026-10-12: works (all 12 evals pass) |
| `MODEL_LARGE` | `claude-sonnet-5-5` on the Anthropic API. Probed 2026-10-12: works. Final synthesis only |
