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

### Done 2026-10-12: run locally, no AWS

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
- Every LLM extraction is validated against a typed Pydantic model and scored against a labeled set in `evals/`.
- Outputs are for research and demonstration. No clinical decision claims in code, docs, or UI.

Domain stack (additions to the platform stack below):

| Slot | Tool | Why |
|---|---|---|
| Synthetic EHR source | Synthea (CSV output) | Open standard synthetic patient generator. |
| Common data model | OMOP CDM v5.4 on PostgreSQL 18 + pgvector | The model is an OHDSI standard; Postgres hosts it in Docker Compose. |
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
- Settings load through `pydantic-settings`. Secrets are `SecretStr`. Every setting and secret comes from `.env` (gitignored), never from the shell, a keychain, or a cloud secret store.

### Coding principles
- Don't add features, refactors, or improvements beyond what was asked.
- Don't add comments, docstrings, or type annotations to code you didn't change.
- No helpers or abstractions for one-time operations. Three similar lines beat a premature abstraction.
- Validate only at system boundaries (user input, external APIs). Trust internal code.
- When editing: match existing style, don't touch adjacent code, remove only what YOUR change made unused. Mention unrelated dead code; don't delete it.
- No OWASP top 10 vulnerabilities. Fix insecure code you wrote immediately.

## Stack decisions

Local-first: everything runs on one machine in Docker Compose, with no cloud account and nothing tied to the host OS. The only external service is the Anthropic API, on each user's own key.

| Slot | Tool | Why |
|---|---|---|
| Models | Claude on the Anthropic API | Each user brings `ANTHROPIC_API_KEY`. Replaced Bedrock 2026-10-12. |
| Agent framework | Anthropic Python SDK, `client.beta.messages.tool_runner` | Runs the tool loop and returns typed output with no extra framework. Replaced Strands Agents, which pulled in boto3. |
| Relational + vector DB | PostgreSQL 18 + pgvector, in Docker Compose | Runs anywhere Docker does. Concurrent writes and pgvector for RAG. Replaced DuckDB and Aurora Serverless v2. |
| Secrets and settings | `.env` read by `pydantic-settings` | One gitignored file; `.env.example` lists every variable. |
| Auth | None; every port binds to 127.0.0.1 | Single-user local app. Replaced Cognito. |
| App hosting | One `app` container in Docker Compose | FastAPI serves the API under `/api` and the static frontend at `/`. |
| Backend framework | FastAPI + Pydantic | Typed request and response models, OpenAPI for free. |
| Python toolchain | uv, ruff, pytest | Fast, one tool per job, lockfile pinned. |
| DB migrations | Alembic | Versioned schema changes; `uv run alembic upgrade head` against the Compose Postgres. |
| Dev-loop evals | pydantic-evals golden set in pytest | Scores the agent against the real model in seconds. |
| Frontend framework | Next.js + React + Tailwind, static export | Builds to plain files, so no Node server at runtime. |
| Code host + CI runner | GitHub + GitHub Actions | `lint-test` runs ruff and pytest against a Postgres service container. |
| Containers | Docker + Docker Compose | Open standard; the whole stack starts with one command. |

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
├── migrations/            # Alembic versioned schema changes
├── frontend/              # Next.js app, static export served by FastAPI
├── evals/                 # golden set; hits a real model, so slow and costs money
├── scripts/               # one-shot operational scripts, never imported
├── data/                  # local synthetic data and vocabularies, gitignored
├── docs/                  # long-form docs the README links to
└── .github/workflows/     # CI; GitHub reads this exact path only
```

What each directory is for, which of these are real conventions and which are choices, and why
`src/` exists at all: see `aws/LAYOUT.md` in [project-template](https://github.com/toddcreasy/project-template/blob/main/aws/LAYOUT.md).

## Conventions

- Everything runs in `docker-compose.yml`. Bind every published port to 127.0.0.1; there is no auth.
- Model tiering: default to `MODEL_SMALL` (Haiku class) for extraction, filtering, and routing. Use `MODEL_LARGE` only for final synthesis. Prompt caching on for any repeated prefix. Batch API for offline jobs.

## Settled decisions

Do not re-ask. Rationale and history in `docs/SETUP.md`.

| Decision | Value |
|---|---|
| API key and spend limit | Personal key scoped to the `ehr-rwe-eln` workspace in the Claude Console, which carries the monthly spend limit. The key lives only in `.env` as `ANTHROPIC_API_KEY`. No macOS Keychain, no shell export: an exported variable would override `.env` |
| Python | 3.14, pinned in `.python-version` |
| Database | PostgreSQL 18 + pgvector 0.8.7, image `pgvector/pgvector:0.8.7-pg18-trixie`, defined in `docker-compose.yml`. Moved from 17 on 2026-10-13: 17 only matched the retired Aurora cluster |
| `MODEL_SMALL` | `claude-haiku-5-5` on the Anthropic API. Probed 2026-10-12: works (all 12 evals pass) |
| `MODEL_LARGE` | `claude-sonnet-5-5` on the Anthropic API. Probed 2026-10-12: works. Final synthesis only |
