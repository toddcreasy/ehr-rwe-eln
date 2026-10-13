# ehr-rwe-eln

Real world evidence from synthetic electronic health records, linked to electronic lab notebook data. One OMOP CDM v5.4 database feeds four modules: a cohort pipeline, an ELN to EHR bridge, a target trial emulation toolkit, and a data quality dashboard. Runs entirely on your machine in Docker Compose: PostgreSQL 17 with pgvector, plus one app container. No cloud account needed; the agent calls the Anthropic API with your own key.

> **Synthetic data only.** This project uses Synthea output, the MIMIC-IV demo, and synthetic ELN entries. It contains no real patient data and makes no clinical claims. Outputs are for research and demonstration.

## Modules

### 1. EHR to RWE cohort pipeline (`ehr_rwe_eln.cohort`)

Generates synthetic patients with Synthea, loads them into OMOP CDM v5.4, and builds analysis-ready cohorts from YAML definitions.

- Synthea CSV to OMOP ETL, checked against OHDSI ETL-Synthea as the reference
- Standard concepts from OHDSI vocabularies (SNOMED, RxNorm, LOINC)
- Cohort definitions as versioned YAML: entry events, inclusion criteria, exit rules
- Cohort tables written back to the OMOP `cohort` table for every downstream module

### 2. ELN to EHR bridge (`ehr_rwe_eln.eln`)

Reads unstructured lab notebook entries and turns them into structured, linkable records.

- Extracts sample IDs, assays, biomarkers, dosing, and results with an LLM agent on the Anthropic API
- Every extraction validates against a typed Pydantic model before it is written
- Writes OMOP `specimen` and `measurement` rows and FHIR R4 `Specimen` and `Observation` resources
- Links bench results to patient phenotypes through shared subject and specimen identifiers
- Precision and recall scored against a labeled set of synthetic ELN entries in `evals/`

### 4. Target trial emulation toolkit (`ehr_rwe_eln.tte`)

Turns a written protocol into a reproducible observational analysis.

- Protocol spec in YAML: eligibility, treatment strategies, time zero, follow up, outcomes
- Generates the cohort SQL from the spec against OMOP
- Propensity score estimation, matching or weighting, and balance diagnostics
- Kaplan-Meier curves and Cox models for time to event outcomes
- Bias report: immortal time checks, positivity, covariate balance, and E-values

### 7. RWE data quality dashboard (`ehr_rwe_eln.dq`)

Profiles the OMOP database before anyone trusts an analysis from it.

- Checks grouped by the Kahn framework: conformance, completeness, plausibility
- Missingness, implausible values, temporal inconsistencies, and concept coverage
- Pass and fail scores per table and per check, tracked across loads
- Results shown in the web frontend and exportable as JSON

## How the modules fit

```
Synthea / MIMIC-IV demo ──> [1] OMOP CDM v5.4 <── [2] ELN entries (LLM extraction)
                                  │
                    ┌─────────────┴─────────────┐
                    v                           v
           [7] data quality checks     [4] target trial emulation
```

Build order: 1, then 7, then 4, then 2. Every module reads the OMOP tables module 1 produces.

## Stack

- **Python 3.14+** with uv, ruff, pytest, pre-commit
- **Data**: OMOP CDM v5.4 on PostgreSQL 17 with pgvector, in Docker Compose; schema changes with Alembic
- **Analysis**: scikit-learn, statsmodels, lifelines
- **Interoperability**: FHIR R4 via `fhir.resources`
- **LLM**: Claude on the Anthropic API, through the Anthropic Python SDK's tool runner
- **App**: FastAPI serving the API under `/api` and a static Next.js build at `/`
- **CI**: GitHub Actions, lint and tests against a Postgres service container

The platform was first built and deployed on AWS, then moved to this local stack on 2026-10-12. That history is in `docs/SETUP.md`.

## Status

| Part | Status |
|---|---|
| Local platform: Postgres, API, agent, frontend in Compose | Done |
| Module 1: cohort pipeline | Done |
| Module 7: data quality | In progress: checks and scoring done; dashboard next |
| Modules 4, 2 | Not started |

## Setup

Requires [uv](https://docs.astral.sh/uv/), Docker, and Node.js 24 (only for frontend work outside Docker).

```bash
git clone https://github.com/toddcreasy/ehr-rwe-eln.git
cd ehr-rwe-eln
cp .env.example .env    # set DB_PASSWORD and ANTHROPIC_API_KEY
uv sync
uv run pre-commit install
```

`.env` is gitignored and is the only place secrets live. Every variable the app reads is listed in `.env.example`. A variable exported in your shell overrides the same one in `.env`, so don't export `ANTHROPIC_API_KEY` or the `DB_*` variables.

### Run it

```bash
docker compose up -d --build --wait   # Postgres on 127.0.0.1:5432, app on http://127.0.0.1:8000
uv run alembic upgrade head           # apply pending migrations
curl localhost:8000/api/health/db
curl -X POST localhost:8000/api/agent -H 'Content-Type: application/json' \
  -d '{"prompt": "Is the database reachable?"}'
```

The `app` service serves the API under `/api` and the built frontend at `/`. There is no sign-in, so both ports bind to 127.0.0.1 only. Each `POST /api/agent` call costs a fraction of a cent on your Anthropic key.

For a reload-on-save loop, run the database in Compose and the API on the host:

```bash
docker compose up -d --wait db
(cd frontend && npm ci && npm run build)   # once, and after frontend changes
uv run fastapi dev                         # http://localhost:8000, reloads on save
```

`uv run python scripts/db_check.py` runs a pgvector round trip against the database and leaves nothing behind.

`uv run python scripts/run_dq.py` runs the 1,912 table and field checks from OHDSI DataQualityDashboard v2.9.0 against the CDM (about 20 s) and stores the run in the `dq` schema.

```bash
docker compose down      # stop; data stays in the ehr-rwe-eln-db volume
docker compose down -v   # stop and delete the data
```

### Tests and evals

```bash
uv run ruff check .
uv run pytest          # fast tests; needs the Compose db running
uv run pytest evals    # golden cases against the real model, about 10 s and a few cents
```

Plain `uv run pytest` never collects `evals/`.

## Data and licensing

- Synthea output is synthetic and carries no patient privacy risk.
- MIMIC-IV demo data is used under its PhysioNet license. Follow its terms.
- OMOP vocabularies are downloaded from OHDSI Athena under their own licenses. They are never committed.
- Nothing under `data/` is committed.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
