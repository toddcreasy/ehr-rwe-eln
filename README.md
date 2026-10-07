# ehr-rwe-eln

Real world evidence from synthetic electronic health records, linked to electronic lab notebook data. One OMOP CDM v5.4 database feeds four modules: a cohort pipeline, an ELN to EHR bridge, a target trial emulation toolkit, and a data quality dashboard. Runs locally on DuckDB and deploys to AWS.

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

- Extracts sample IDs, assays, biomarkers, dosing, and results with an LLM agent on Amazon Bedrock
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

- **Python 3.12+** with uv, ruff, pytest, pre-commit
- **Data**: OMOP CDM v5.4 on DuckDB locally and Aurora Serverless v2 PostgreSQL with pgvector on AWS
- **Analysis**: scikit-learn, statsmodels, lifelines
- **Interoperability**: FHIR R4 via `fhir.resources`
- **LLM**: Amazon Bedrock (Claude), Strands Agents, AgentCore Runtime and Gateway (MCP)
- **App**: FastAPI on App Runner, Next.js on Amplify, Cognito auth
- **Infra**: AWS CDK (Python), GitHub Actions with OIDC, CloudWatch, AWS Budgets

The platform is built in phases from the [project-template AWS build plan](https://github.com/toddcreasy/project-template/tree/main/aws). See `CLAUDE.md` for the plan and its STOP gates.

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Repo scaffold | Done |
| 1 to 9 | AWS platform: guardrails, data, API, agent, MCP, observability, frontend, CI/CD, hardening | Not started |
| 10 | Archive the build plan to `docs/SETUP.md` | Not started |
| Modules | 1, 7, 4, 2 | Not started |

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/toddcreasy/ehr-rwe-eln.git
cd ehr-rwe-eln
uv sync
uv run pre-commit install
uv run ruff check .
uv run pytest
```

Copy `.env.example` to `.env` and fill in values as phases add them.

## Teardown

AWS teardown order is added in Phase 1.

## Data and licensing

- Synthea output is synthetic and carries no patient privacy risk.
- MIMIC-IV demo data is used under its PhysioNet license. Follow its terms.
- OMOP vocabularies are downloaded from OHDSI Athena under their own licenses. They are never committed.
- Nothing under `data/` is committed.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
