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
- **App**: FastAPI on ECS Express Mode, Next.js on Amplify, Cognito auth
- **Infra**: AWS CDK (Python), GitHub Actions with OIDC, CloudWatch, AWS Budgets

The platform is built in phases from the [project-template AWS build plan](https://github.com/toddcreasy/project-template/tree/main/aws). See `CLAUDE.md` for the plan and its STOP gates.

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Repo scaffold | Done |
| 1 | AWS guardrails: budget, alerts, GitHub OIDC role | Done |
| 2 | Data layer: Aurora Serverless v2 + pgvector, S3, Alembic | Done |
| 3 | Backend API: FastAPI on ECS Express Mode | Done |
| 4 | Agent: Strands on Bedrock, AgentCore Runtime | Done |
| 5 | MCP tools: AgentCore Gateway over the backend | Done |
| 6 | Observability and evals | Done |
| 7 | Frontend: Next.js on Amplify, Cognito sign-in | Done |
| 8 | CI/CD: GitHub Actions, deploy on merge to main | Done |
| 9 | Hardening and cost review | Not started |
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

### Database access

Aurora sits in isolated subnets with no public address. Local scripts reach it through the RDS Data API using `DATABASE_SECRET_ARN` and your AWS credentials, so no bastion or VPN is needed.

```bash
uv run python scripts/migrate.py    # apply pending Alembic migrations
uv run python scripts/db_check.py   # pgvector round trip, leaves nothing behind
```

`migrate.py` renders migrations with Alembic offline mode and runs the SQL in one Data API transaction. The cluster auto-pauses to 0 ACU after 5 minutes idle; the first call after a pause takes about 15 seconds while it resumes.

### Run the API locally

The deployed API talks to Aurora; locally it talks to Postgres in Docker. `.env` needs `DB_HOST=localhost` and `DB_PASSWORD=localdev` (see `.env.example`).

```bash
docker run -d --name ehr-rwe-eln-pg -e POSTGRES_PASSWORD=localdev -e POSTGRES_DB=ehr_rwe_eln \
  -p 5432:5432 pgvector/pgvector:pg17   # first time; afterwards: docker start ehr-rwe-eln-pg
uv run fastapi dev                      # http://localhost:8000/health and /health/db, reloads on save
```

### Run the agent locally

The agent (`src/ehr_rwe_eln/agents/`) is a Strands agent on Bedrock, deployed to AgentCore Runtime. Locally it uses your AWS credentials to call Claude, so each call costs a fraction of a cent.

```bash
uv run python -m ehr_rwe_eln.agents.app        # serves /ping and /invocations on :8080
curl -X POST localhost:8080/invocations -H 'Content-Type: application/json' \
  -d '{"prompt": "What time is it in UTC?"}'
uv run python scripts/agent_smoke.py           # calls the deployed runtime (needs AGENT_RUNTIME_ARN)
```

The agent reaches the backend through AgentCore Gateway, which publishes `GET /health/db` as the MCP tool `backend___checkDatabaseHealth`. To use the Gateway tool locally without deploying the agent, set `GATEWAY_URL` in `.env` (AgentStack output `GatewayUrl`). The local agent signs MCP requests with your own AWS credentials, which need `bedrock-agentcore:InvokeGateway`. The backend must be running (`backend_tasks=1`). Leave `GATEWAY_URL` unset to run with local tools only.

### Evals and observability

```bash
uv run pytest evals    # 12 golden cases against real Bedrock models, about 20 s and a few cents
```

Plain `uv run pytest` never collects `evals/`. The three Gateway cases skip unless `GATEWAY_URL` is set and the backend is running.

Deployed runs are traced end to end (model calls, tool calls, the Gateway hop) with ADOT and CloudWatch Transaction Search: CloudWatch console, **GenAI Observability**, agent `ehr_rwe_eln_hello`. The `ehr-rwe-eln-agent` dashboard shows invocations, errors, latency, Gateway tool time, and daily tokens. Alarms on error rate and daily tokens email the Phase 1 alerts topic. AgentCore Evaluations scores every live run for helpfulness and tool selection.

### Pause the backend when idle

The API runs on ECS Express Mode (Fargate). A running task costs about $13 a month; the load balancer costs about $24 a month whether or not a task runs. Scale to zero tasks when you stop working:

```bash
cd infra
cdk deploy BackendStack -c backend_tasks=0   # pause
cdk deploy BackendStack                      # resume (backend_tasks=1 in cdk.json)
```

## Teardown

CDK app lives in `infra/`. Deployed stacks are named `ehr-rwe-eln-<Stack>`; other projects in the same account own the bare names. CDK commands take the short ID (`OpsStack`).

Destroy in reverse dependency order, `OpsStack` last so budget alerts stay live until everything else is gone:

```bash
cd infra
cdk destroy FrontendStack
cdk destroy AgentStack
cdk destroy BackendStack
cdk destroy DataStack
cdk destroy OpsStack
```

Skip any stack not deployed yet (`cdk list` shows what the app defines). Run `cdk diff <Stack>` first to confirm what will go. Left in place on purpose: the `CDKToolkit` bootstrap stack and the GitHub OIDC provider, both shared with other projects in the account. CloudWatch Transaction Search, which agent tracing needs, is an account-wide setting owned by the glia-nav project; if that project disables it, traces from this one stop.

`DataStack` leaves two things behind after destroy: a final Aurora snapshot (the cluster default) and the documents bucket (S3 default is retain). Delete both by hand once you are sure nothing in them is needed.

## Data and licensing

- Synthea output is synthetic and carries no patient privacy risk.
- MIMIC-IV demo data is used under its PhysioNet license. Follow its terms.
- OMOP vocabularies are downloaded from OHDSI Athena under their own licenses. They are never committed.
- Nothing under `data/` is committed.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
