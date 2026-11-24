# SETUP

Build history for `ehr-rwe-eln`. These phases lived in `CLAUDE.md` while the platform was built
from the `aws/BUILD.md` template in [toddcreasy/project-template](https://github.com/toddcreasy/project-template/tree/main/aws).
Phase 10 moved them here once infrastructure was done, so `CLAUDE.md` carries only the rules every
session needs. Each phase lists the tools it introduced, why they were picked, the checklist as
completed, and the STOP gate that verified it.

The first AWS stacks were destroyed on 2026-10-12 and their `infra/` was deleted after that; the build
phases below are the record of what was built then, and their AWS commands no longer run. The run
steps for the current setup are in [INSTALL.md](INSTALL.md).

The project moved back to AWS from 2026-11-19 to 2026-11-23, on Terraform this time (`infra/terraform/`). That move and the local-first one before it are at the end of this file, moved from `CLAUDE.md` once done.

# Build phases

## Phase 0: Repo scaffold

Do this first, before any code: **enable Cost Explorer in the billing console.** It takes one
click and up to 24 hours to ingest. Until it has data, `ce:GetCostAndUsage` fails, the Phase 1
budget alarm reads `null` for actual and forecast so it cannot fire, and cost allocation tag keys
cannot be activated because they only become activatable after appearing in billing data. Enable
it on day one or the entire build runs with no working spend guard.


Goal: a clean Python repo that lints, tests, and installs from lockfile.

Tools in this phase:
- **uv**: one fast tool for Python installs, environments, and lockfiles. It replaces pip, venv, and poetry. Why: reproducible installs and no manual venv activation.
- **ruff**: linter and formatter in one binary. Why: catches errors and enforces one style in milliseconds, so checks never feel optional.
- **pytest**: the standard Python test runner. Why: every STOP gate in this file needs a runnable proof, and pytest is that proof.
- **pre-commit**: runs ruff and other checks before each commit lands. Why: broken code never enters the repo.

- [x] `uv init` with `pyproject.toml`: project metadata, Python >= 3.12
- [x] Add dev deps: `ruff`, `pytest`, `pre-commit`
- [x] `ruff` config in `pyproject.toml` (lint + format), pre-commit hook wired
- [x] Directory layout created as above, with placeholder `__init__.py` and one passing placeholder test
- [x] `.gitignore` (Python, node, `.env`, CDK out, IDE)
- [x] `.env.example` created (empty vars added as phases introduce them)
- [x] README stub: project name, one-line purpose, setup commands
- [x] Initial commit pushed

STOP gate 0: `uv run ruff check .` is clean and `uv run pytest` passes. Show both outputs.

## Phase 1: AWS guardrails before any resources

Goal: spending alarms and deploy identity exist before anything can cost money.

Tools in this phase:
- **AWS CDK**: you describe AWS resources in Python code; `cdk deploy` creates them, `cdk destroy` removes them. Why: the whole infrastructure is versioned in git and rebuildable, and it stays in the language you already use.
- **AWS Budgets**: a monthly spending limit that emails you at thresholds. Why: the number one risk in a personal cloud project is silent spend.
- **Amazon SNS**: AWS's notification service; topics fan out messages to email or other targets. Why: one topic carries every alert in this project.
- **IAM with GitHub OIDC**: IAM is AWS's permission system. OIDC lets GitHub Actions prove its identity to AWS and assume a role for minutes. Why: no long-lived AWS keys stored anywhere, so nothing can leak.
- **Cost allocation tags**: labels on every resource that Cost Explorer can group by. Why: when the bill surprises you, tags tell you which part did it.

- [x] Confirm AWS account ID and `us-east-1` with maintainer
- [x] `infra/` CDK app skeleton (`app.py`, `cdk.json`, stacks package)
- [x] `cdk bootstrap` the account/region
- [x] `OpsStack`: AWS Budget with monthly limit (ask maintainer for the number, suggest $30) + SNS email alert at 50/80/100%
- [x] Cost allocation tags activated for `project` and `env`. Blocked until Cost Explorer has ingested a day of data and the keys have appeared in a bill, so this lands late even though it belongs here
- [x] IAM role for GitHub Actions OIDC (trust policy scoped to this repo), no access keys created
- [x] Document teardown: `cdk destroy` order in README

STOP gate 1: budget visible in console, maintainer confirms the SNS subscription email arrived, `cdk deploy OpsStack` output shown.

## Phase 2: Data layer

Goal: a Postgres database with vector search, reachable from a local script, credentials in Secrets Manager.

Tools in this phase:
- **Aurora Serverless v2 (PostgreSQL)**: AWS-managed Postgres that scales its compute up and down, including to zero when idle. Why: real Postgres with near-zero cost while you are not using it, and no server patching.
- **pgvector**: a Postgres extension that stores embeddings and runs similarity search. Why: one database handles both normal tables and vector search, so no separate vector product to pay for and operate.
- **AWS Secrets Manager**: stores credentials; apps fetch them at runtime by ARN. Why: passwords never sit in code, `.env` files in git, or CI settings.
- **Amazon S3**: durable object storage for files and documents. Why: pennies per GB and every AWS service reads from it.
- **Alembic**: versioned database schema migrations for Python. Why: schema changes become reviewable files that replay identically in every environment.
- **VPC**: your private network inside AWS. Why: the database gets no public address; only your services can reach it.

- [x] `DataStack`: VPC (2 AZs, no NAT gateway if avoidable; use isolated subnets + endpoints), Aurora Serverless v2 PostgreSQL
- [x] Serverless v2 scaling: min capacity 0 ACU (auto-pause) for dev, max 1
- [x] DB credentials generated into Secrets Manager by CDK
- [x] `pgvector` extension enabled (`CREATE EXTENSION vector`)
- [x] S3 bucket for documents (versioned, private, lifecycle rule to Infrequent Access at 30 days)
- [x] Alembic initialized; migration 001 creates a schema-version table only
- [x] `scripts/db_check.py`: connects via the secret, runs a vector insert + cosine similarity query
- [x] `.env.example` updated: `DATABASE_SECRET_ARN`, `AWS_REGION`

STOP gate 2: run `uv run python scripts/db_check.py`; show the round-trip output including a similarity score. Confirm the cluster pauses to 0 ACU after idle (console check).

## Phase 3: Backend API

Goal: a deployed FastAPI service that reaches the database.

Tools in this phase:
- **FastAPI**: the standard modern Python web framework. Type hints define request and response shapes; docs generate themselves. Why: it shares Pydantic models with the agent layer, so one set of types flows through the whole system.
- **Pydantic / pydantic-settings**: data validation from type hints, plus typed config loaded from env vars or Secrets Manager. Why: bad data fails loudly at the boundary instead of deep in a handler.
- **Docker**: packages the app and its dependencies into an image that runs the same everywhere. Why: "works on my machine" becomes "works on Fargate".
- **Amazon ECR**: AWS's private registry that stores those images. Why: ECS pulls images straight from it..
- **Amazon ECS Express Mode**: give it a container image and two IAM roles; it builds the load balancer, HTTPS certificate, security groups and autoscaling in your account and runs the container on Fargate. Why: AWS closed App Runner to new customers and points here; every piece it creates is a normal AWS resource you can inspect. Scale to 0 tasks when idle with `cdk deploy BackendStack -c backend_tasks=0`.
- **Amazon CloudWatch**: AWS's built-in logs, metrics, dashboards, and alarms. Why: it is already there; every log line from the container lands in it with no setup.

- [x] `src/ehr_rwe_eln/api/`: FastAPI app with `GET /health` (static) and `GET /health/db` (runs `SELECT 1`)
- [x] `pydantic-settings` config module; secrets resolved from Secrets Manager when deployed, `.env` locally
- [x] Dockerfile (multi-stage, uv-based, non-root user)
- [x] `BackendStack`: ECS Express Mode service from the container image (ECR), public subnets for the load balancer, task security group to Aurora, DB secret injected as env
- [x] Structured JSON logging to CloudWatch, retention 30 days
- [x] Local run documented: `uv run fastapi dev`

STOP gate 3: `curl` both health endpoints on the deployed Express Mode endpoint; show responses. Show one structured log line in CloudWatch.

## Phase 4: Agent layer

Goal: one working agent on Bedrock, deployed to AgentCore Runtime, with visible token usage.

Tools in this phase:
- **Amazon Bedrock**: one AWS API in front of many models (Claude, Nova, Llama, and others), billed per token, with IAM auth and no separate API keys. Why: model access stays inside the AWS account, permissions, and bill.
- **Strands Agents SDK**: AWS's open-source Python agent framework. An agent is a model, a prompt, typed output, and tools; the SDK runs the reasoning loop. Why: first-class Bedrock and AgentCore support, and small enough to read.
- **Bedrock AgentCore Runtime**: a managed place to run agent code, with per-session isolation and support for long-running work. Why: the agent runs server-side with its own identity and scaling, not inside the web backend.
- **Prompt caching**: Bedrock reuses a repeated prompt prefix (system prompt, tool definitions) across calls at a fraction of the token price. Why: agents resend the same prefix constantly; caching is the single cheapest cost fix.

- [x] Enable Bedrock model access for the chosen Claude models in `us-east-1` (maintainer action; provide exact console steps)
- [x] `src/ehr_rwe_eln/agents/`: one Strands agent, typed output model, one local tool (echo/time), prompt caching enabled
- [x] Model tiering config: `MODEL_SMALL`, `MODEL_LARGE` env vars; agent defaults to small
- [x] Token/cost logging per run (structured log fields: input_tokens, output_tokens, cache_read, model)
- [x] `AgentStack`: deploy the agent to AgentCore Runtime via CDK/CLI
- [x] `scripts/agent_smoke.py`: invokes the deployed agent, prints typed output + usage

STOP gate 4: run the smoke script; show the typed response and the token usage log line from the deployed runtime.

## Phase 5: Tools over MCP

Goal: the agent reaches the backend through AgentCore Gateway as MCP tools.

Tools in this phase:
- **MCP (Model Context Protocol)**: the open standard for connecting agents to tools and data, adopted by every major AI provider. A tool exposed over MCP works with any compliant agent. Why: tool integrations written once stay portable across frameworks and models.
- **AgentCore Gateway**: takes an existing API or Lambda function and publishes it as MCP tools, with IAM auth and per-tool permissions. Why: the backend stays a plain FastAPI app; the Gateway does the MCP plumbing and enforces who may call what.

- [x] Expose one backend endpoint (start with `GET /health/db`) as a Gateway MCP tool
- [x] Gateway auth wired to IAM; least-privilege policy for the agent identity
- [x] Agent updated: the MCP tool is in its toolset; system prompt mentions when to use it
- [x] Local dev path documented: how to run the agent against the tool without deploying

STOP gate 5: smoke script shows the agent calling the Gateway tool and returning its result. Show the trace of the tool call.

## Phase 6: Observability and evals

Goal: every agent run is traceable; quality is measurable before deploys.

Tools in this phase:
- **AgentCore Observability**: records every agent run as a trace: each model call, tool call, latency, and token count as spans. Why: without traces, a misbehaving agent is a black box and token waste is invisible.
- **CloudWatch dashboards and alarms**: charts on top of the metrics, plus alerts to the Phase 1 SNS topic. Why: you find out about error spikes and token spend from an email, not from the bill.
- **pydantic-evals**: local eval framework from the Pydantic team. A golden set of inputs with expected typed outputs, scored in seconds under pytest. Why: before any change deploys, you know whether agent quality moved.
- **AgentCore Evaluations**: managed evaluators (response quality, safety, tool usage) that score real production traces continuously. Why: local evals catch regressions before deploy; this catches drift after.

- [x] AgentCore Observability enabled on the runtime: `aws-opentelemetry-distro` in the image, `opentelemetry-instrument` in front of the entrypoint, and `tracingEnabled` on the runtime
- [x] CloudWatch Transaction Search enabled. It needs a CloudWatch Logs resource policy letting `xray.amazonaws.com` write to `aws/spans`, which the CFN resource does not create for itself, and the runtime's traces delivery must depend on it explicitly or CloudFormation builds them in parallel and the delivery loses the race
- [x] CloudWatch dashboard: agent invocations, errors, latency, daily token totals
- [x] CloudWatch alarms: error rate and a daily token-spend threshold, both to the Phase 1 SNS topic
- [x] `evals/`: 10 to 15 golden cases with `pydantic-evals`; assertions on typed output fields
- [x] Evals run via `uv run pytest evals` and are marked so they can be skipped in fast unit runs
- [x] AgentCore Evaluations configured with at least response-quality and tool-usage evaluators on production traces. Set `executionStatus` to ENABLED and raise `samplingPercentage`: the defaults are DISABLED and 10%, so it deploys clean and scores nothing
- [x] Token metrics: AgentCore does not publish them. Derive them from a metric filter over your own structured run log, and know that the filter only sees the deployed runtime, not local or CI runs

STOP gate 6: show one full trace for an agent run (spans for model calls and tool calls). Show `uv run pytest evals` passing. Show the dashboard.

## Phase 7: Frontend

Goal: a deployed web UI behind sign-in that calls the backend.

Tools in this phase:
- **Next.js + React**: React builds UIs from components; Next.js adds routing, server rendering, and the build system around it. The standard frontend stack. Why: largest ecosystem, best AI-tool support, and non-technical users get a polished app instead of a developer demo.
- **Tailwind CSS**: styling as utility classes in the markup instead of separate CSS files. Why: fast to build, consistent by default, and the style every component library assumes.
- **Amazon Cognito**: managed sign-up, sign-in, and password reset. It issues JWTs, which are signed tokens the frontend attaches to each API call. Why: authentication is a solved problem you should never hand-build; the backend just verifies the token signature.
- **AWS Amplify Hosting**: watches the repo, builds the frontend on every push, and serves it on a CDN with HTTPS. Why: frontend deployment becomes a side effect of `git push`.

- [x] `frontend/`: Next.js + Tailwind, one page that calls the backend and renders the result
- [x] Cognito user pool + app client, hosted UI or Amplify Auth components. Put it in `BackendStack`, not `FrontendStack`: the API verifies the tokens and the frontend needs the API's URL, so a downstream pool makes the two stacks import each other and CloudFormation rejects cyclic exports
- [x] Backend validates Cognito JWTs on protected routes
- [x] Amplify Hosting serving `frontend/`. CloudFormation cannot create a Git-backed Amplify app without a stored GitHub token (`AccessToken` or `OauthToken` is required), so either accept a long-lived credential in the account or create the app with no repository and have CI upload the build through the Amplify deployment API
- [x] Route the API through an Amplify rewrite (`/api/<*>` to the backend) so the browser stays same-origin. This removes the need for CORS entirely and breaks the other half of the stack cycle
- [x] A visible disclaimer/footer component slot (project-specific text comes later)

STOP gate 7: maintainer signs up, logs in on the deployed Amplify URL, and sees data returned from an authenticated backend call. Unauthenticated calls return 401 (show it).

## Phase 8: CI/CD

Goal: every merge to main deploys itself; no AWS keys stored anywhere.

Tools in this phase:
- **GitHub Actions**: workflows defined in YAML that run on every push or pull request: lint, test, deploy. Why: it lives where the code lives, the free tier covers a personal project, and via the Phase 1 OIDC role it deploys to AWS with no stored credentials.
- **Branch protection**: a GitHub setting that blocks direct pushes to main and requires passing checks. Why: the pipeline is only a guarantee if it cannot be bypassed.
- **cdk diff in CI**: prints the infrastructure changes a PR would cause. Why: you review infrastructure changes the same way you review code changes, before they happen.

- [x] Workflow `ci.yml`: on PR run ruff, pytest (unit), and `cdk diff` via the OIDC role
- [x] Workflow `deploy.yml`: on main run tests, evals, `cdk deploy --all`, then build the frontend and upload it. Amplify only auto-builds on push if the app is Git-connected, which needs a stored token; otherwise CI does the upload
- [x] `docker/setup-qemu-action` and `setup-buildx-action` if any image is arm64. Runners are amd64, and emulated builds are slow enough to dominate the deploy
- [x] Branch protection on main: PR + passing checks required. Needs GitHub Pro on a private repo; both the protection and rulesets APIs return 403 on the free plan. Set `enforce_admins` or it will not stop the repo owner, which on a solo project means it stops nobody
- [x] OIDC trust policy: GitHub now issues subjects with numeric owner and repo ids embedded (`repo:owner@123/repo@456:ref:...`). A policy matching only `repo:owner/repo:*` is denied, and the action retries so the job hangs rather than failing. CloudTrail is the only place the reason appears
- [x] Concurrency guard so two deploys cannot overlap

STOP gate 8: merge a trivial change (README typo). Show the green pipeline and the change live.

## Phase 9: Hardening and cost review

Goal: safe defaults locked in; spend understood.

Tools in this phase:
- **Bedrock Guardrails**: a filter attached to model calls that masks PII, blocks denied topics, and screens harmful content on the way in and out. Why: policy lives in one managed place instead of scattered through prompts.
- **AWS Cost Explorer**: the console view that breaks the bill down by service, tag, and day. Why: paired with the Phase 1 tags, it answers "what is costing me money" in one screen.
- **IAM least privilege review**: narrowing each role to only the actions and resources it uses. Why: an agent that can call tools is an actor in your account; its blast radius should be as small as its job.

- [x] Bedrock Guardrails: a basic policy (PII masking, denied topics placeholder) attached to agent calls. Three traps: guardrail versions are immutable and the CFN version resource does not cut a new one when the policy changes, so pin a hash of the config into its logical id or the runtime silently keeps the old policy; a topic definition is capped at 200 characters; and streaming must run in `sync` mode, because `async` delivers chunks before the guardrail sees them and never masks PII
- [x] Handle the block path: a guardrail intervention ends the agent loop before the model can produce structured output, so a naive handler returns None and the runtime answers 500. A working safety control should not look like a server error
- [x] Cold database path: Aurora takes about 15 s to resume from 0 ACU, and the MCP client gives up at 30 s by default. Order the timeouts so each inner one is shorter than the one outside it (DB connect under the Gateway's 55 s, under the agent's MCP client), and have the backend answer a clear "may be resuming, retry" 503 that the agent passes on
- [x] Verify log retention on every log group is 30 days. Services create their own groups and default to never expiring; so do CDK custom-resource providers, whose Lambda names are generated, so build the group name from the handler's ref
- [x] Review IAM: agent, backend, and CI roles are least-privilege; no wildcards on resources where avoidable
- [x] Cost Explorer review with maintainer: line-item actuals vs the table below
- [x] `scripts/teardown_check.py` or documented `cdk destroy` runbook tested against `cdk diff`

STOP gate 9: present the cost review table (expected vs actual) and the IAM summary. Maintainer signs off. Infrastructure is done; feature work starts.

## Phase 10: Archive the build plan

Goal: CLAUDE.md becomes small again. Claude Code loads this file every session, so after the build it must carry only the always-needed rules.

- [x] Create `docs/SETUP.md` and move into it: the entire "Build phases" section (Phases 0 through 10, with their completed checklists and tool definitions) and the "Expected monthly cost" table
- [x] Keep in CLAUDE.md: "How Claude Code must use this file" (rewritten for the maintenance era, see next item), "Operating rules", "Stack decisions", "Repository layout", "Conventions"
- [x] Rewrite the "How Claude Code must use this file" section to two lines: follow the operating rules; the infrastructure history and runbooks live in `docs/SETUP.md`
- [x] Add one pointer line under the stack table: "How each piece was built, verified, and what it costs: see `docs/SETUP.md`"
- [x] Commit as its own change, no other edits mixed in

[`aws/CLAUDE.md`](https://github.com/toddcreasy/project-template/blob/main/aws/CLAUDE.md) in the template repo is the target shape for this rewrite, already generalized.
Start from it rather than deleting sections by hand.

STOP gate 10: show CLAUDE.md under roughly 100 lines, `docs/SETUP.md` containing the full history, and both rendering correctly on GitHub.

## Expected monthly cost (dev, personal scale)

### Now, since the move back to AWS (2026-11-23)

The budget is $100 a month on resources tagged `project = ehr-rwe-eln`, with email at 50% and 80% of actual spend and 100% forecast.

| Item | Expected |
|---|---|
| ECS Express Mode (load balancer + the app's one task) | About $24 to $36, the largest fixed cost (the first build's estimate below) |
| Redshift Serverless | Per second of compute; capped at 150 RPU-hours a month, at most about $56. A full DQD run is about 4.5 RPU-hours |
| Aurora Serverless v2 | About $0 while paused, plus storage |
| S3 Tables, the genomics bucket, ECR | A few dollars at this scale |
| Fargate jobs | Per run: Exomiser or LIRICAL on 5,000 people about $2 to $2.60, an evaluation of every synthetic release 9 cents, a GWAS a few cents |
| CodeBuild | Per build minute; an image takes about 5 minutes |
| Bedrock tokens | Usage-driven; `/api/agent` is held to 150,000 tokens a day |
| CloudWatch, CloudTrail, Budgets | A few dollars |

No NAT gateway or interface endpoints: they would cost more than the whole budget.

### The first AWS build (until 2026-10-12)

| Item | Expected |
|---|---|
| Aurora Serverless v2 (auto-pause) | ~$0 compute idle + ~$0.10/GB storage |
| ECS Express Mode (load balancer + 1 Fargate task) | about $24 paused, about $36 running all month |
| Amplify Hosting | $0 to $5 |
| Cognito | $0 at personal scale |
| CloudWatch + alarms | $1 to $5 |
| AgentCore (consumption) | Low single digits at dev usage |
| Bedrock tokens | Usage-driven; controlled by tiering, caching, batch |
| Budgets, IAM, OIDC, tags | $0 |
| Target total (excluding tokens) | About $26 to $42, against a $50 budget |

If actuals exceed the budget alarm, stop feature work and find the line item first.

# AWS move

## Done 2026-11-23: move to AWS

Decided 2026-11-19, reversing the local-first move below: the app runs on AWS (the `default` profile's account, `us-east-1`), with OMOP in a lakehouse. The plan, open items, and reasons are in `notes/TODO_IMPROVEMENTS.md` (`notes/` is gitignored: personal planning, `TODO.md`, the industry comparison). Six steps, one PR each; until a step lands, the local Docker Compose stack keeps running that part:

- [x] 1. `CLAUDE.md` and the Terraform foundation (`infra/terraform/`): VPC, S3 Tables lake, Lake Formation and Glue catalog, Redshift Serverless, Aurora Serverless v2, budget
- [x] 2. OMOP in the lake: the ETL still builds in a staging Postgres (decided 2026-11-19, stage then publish); `scripts/publish_omop.py` copies all 39 tables (60,890,645 rows) to Iceberg in S3 Tables, and `scripts/reconcile_lake.py` checks every column of every table through Redshift (1,038 checks, cohorts 550 and 885)
- [x] 3. OMOP readers on Redshift: trial emulation, synthetic data sources, and the genomics, curation, and ELN scripts read the lake through `connect_omop()` (Redshift Data API, `OMOP_SOURCE=staging` for the staging Postgres), in SQL that runs unchanged on both. `scripts/compare_omop_sources.py`: identical tables for 4 protocols, 14 negative controls, 2 synthetic specs. Decided 2026-11-19: OMOP writers (ETL, cohorts, ELN bridge) stay on staging and republish; data quality stays on staging until DQD in R (step 6)
- [x] 4. App on ECS Express Mode (`infra/terraform/app/`), a public demo with no sign-in (decided 2026-11-20, as glia-nav): `/api/agent` bounded by a daily token limit and a per-address limit, curator decisions off (`PUBLIC_DEMO`). Module data in Aurora (migrations and a data-only copy through the bastion tunnel, row counts identical). The privacy monitor runs daily as a scheduled ECS task on the lake
- [x] 5. Bedrock (Claude Opus 4.6, `us.anthropic.claude-opus-4-6-v1`) replaces the Anthropic API through `AnthropicBedrock` and `claude_client()` (`agents/config.py`); every call sets adaptive thinking. ELN extraction runs as direct calls (Bedrock has no Message Batches API; decided 2026-11-20). Every eval re-ran on Opus 4.6 and matched Opus 5.5: ELN extraction 1.000 on the default, hard, and adversarial sets; literature precision 83%
- [x] 6. R and HADES, LangGraph for literature curation, then the genomics, curation, and synthetic data items in `notes/TODO_IMPROVEMENTS.md`. One PR each:
  - [x] 6a. R and HADES foundation: `docker/hades.Dockerfile` (R 4.6.1, Java 21, HADES from OHDSI's r-universe and a dated CRAN snapshot; versions in `r/installed-versions.txt`), `r/`, and `scripts/hades.py` (bastion tunnel to Redshift, temporary IAM login). Smoke tests pass on Eunomia and on the lake (23,421 persons)
  - [x] 6b. DataQualityDashboard 2.9.1 (R) on the lake: `r/run_dqd.R`, loaded into the `dq` schema by `scripts/load_dqd.py` (Aurora through the RDS Data API). Same 2,384 checks and the same 14 failures as the Python port, which was removed 2026-11-20; 32 minutes, about 4.5 RPU-hours
  - [x] 6c. CohortMethod and TrialEmulation (2026-11-21). CohortMethod 6.0.3: `r/run_cohortmethod.R` on the two lisinopril protocols from `results.cohort` in Redshift (`scripts/write_cohorts.py`), 12 negative controls each, large-scale propensity score, IPTW, Cox, empirical calibration; every OHDSI diagnostic passes (balance by the sample-size test, `sdmAlpha` 0.05). Covariates end the day before time zero, in R and Python (a panel drawn on the start day had failed balance). TrialEmulation 0.0.5: `r/run_trialemulation.R` on person-periods from `tte/per_protocol.py`, per-protocol (strict: stopping or adding the other drug ends follow-up; lenient: stopping only) with switch weights, CKD protocol. Decided 2026-11-21: the Python `tte` analysis stays as the readable version behind `/tte`; CohortMethod is the OHDSI check, TrialEmulation the per-protocol estimate
  - [x] 6c+. OMOP MCP server (added 2026-11-20, done 2026-11-21): bounded tools over the lake (vocabulary concept search, patient counts for a concept set with small counts suppressed, trial emulation and data quality results), used by `/api/agent` and by Claude Code; no free-form SQL on the public demo. A Bedrock Guardrail on `/api/agent` (content filters and prompt-attack detection; the token limits cap cost, not content). Agent stays in the ECS app, not AgentCore Runtime (decided 2026-11-20: short stateless calls, no sign-in, already on ECS). Decided 2026-11-21: counts precomputed in Aurora (`omop_stats`, built by `scripts/build_omop_stats.py`; public tool calls never reach Redshift); one concept at a time, rolled up through descendants; counts under 11 suppressed and never stored; MCP only locally, over stdio (`agents/mcp_server.py`, `.mcp.json`; no port, nothing public), `/api/agent` calls the same functions in-process. Three PRs: (1) `omop_stats` and the four tool functions (`agents/omop_tools.py`) [done], (2) the agent on them (`agents/workbench.py`), evals (`evals/test_workbench_agent.py`), the stdio MCP server [done], (3) the Guardrail [done]: `infra/terraform/app/guardrail.tf`, prompt checked first with ApplyGuardrail, every model call through it with only the visitor's text tagged (untagged, the system prompt reads as a prompt attack), IAM requires it on InvokeModel, alarm at 20 interventions an hour
  - [x] 6d. LangGraph for literature curation (2026-11-21): `curation/literature_graph.py` runs the existing steps as nodes (retrieve, propose, verify, store), then pauses at a curator node with `interrupt()`; the decisions route resumes it, and it pauses again, since decisions keep history. Checkpoints in the app database's `langgraph` schema (migration 021, the library's own tables); one thread per literature run and variant. Decided 2026-11-21: Claude through `propose()` and `claude_client()`, not `langchain-aws`; a straight port, no retry on rejected claims. On the same 6 variants the graph scores as the direct calls (5 agreed, 1 extra, 3 missed; every claim verified); pilot run 14, 10 variants, precision 69%, recall 64%, $0.74
  - [x] 6e. stdpopsim, PLINK 2, REGENIE, panel variants into OMOP (2026-11-21). Three PRs: (1) stdpopsim's `OutOfAfrica_3G09` in `genomics/simulate.py`, each person's population from their OMOP race (decided 2026-11-21: a simulation convention that ties ancestry to hypertension, so the GWAS has confounding to correct) [done: the uncorrected score test gives lambda 4.0 and 12 false loci], (2) PLINK 2 QC and principal components, REGENIE, on AWS: CodeBuild builds the x86 image, an on-demand x86 Fargate task runs it (`infra/terraform/app/gwas.tf`, `scripts/run_regenie.py`; decided 2026-11-21: REGENIE ships no ARM build, and nothing runs in local Docker). The score test stays as the readable check, with the same PCs, and its null runs calibrate REGENIE [done: lambda 0.98 with REGENIE and 0.95 with the score test, the planted variant found at p 1.5e-11, no other loci], (3) panel carriers as `measurement` rows with OMOP Genomic concepts (vocabulary downloaded from Athena into `data/vocab_genomic/`; decided 2026-11-21: carriers only, dated at each person's observation period end; the most specific concept, else the gene's) [done: 46,596 rows matching every carrier; 6 of 48 variants have a concept of their own]
  - [x] 6f. Exomiser and BIAS-2015 (2026-11-22). Three PRs: (1) Exomiser 15.1.0 on Fargate (`infra/terraform/app/exomiser.tf`, `scripts/run_exomiser.py`, `curation/exomiser.py`; decided 2026-11-22: data release 2609 in S3, unpacked on each task's disk; REVEL, MVP, AlphaMissense, no SpliceAI (non-commercial), CADD, or REMM; split across parallel tasks, capped by the Fargate vCPU quota) [done: 5,000 subjects in 6 tasks, 75 minutes; the variant score puts every planted gene first, since Exomiser's data includes ClinVar; the phenotype score 36 of 123 (chance about 15%), AUC 0.97 on MSH2 and 0.55 on LDLR, against 0.88 and 0.69 for our Resnik score], (2) Exomiser's rank on `/curation/` as context, not PP4 (`curation.exomiser`, migration 022; the phenotype rank only, since the variant score includes ClinVar) [done], (3) BIAS-2015 as a baseline on the Evidence Repository variants, with and without its ClinVar-based criteria (`infra/terraform/app/bias.tf`, `scripts/run_bias.py`, `curation/bias.py`; decided 2026-11-22: VEP 115, the release BIAS's tables were built for, on Fargate; three runs: all codes, without the per-variant ClinVar codes, without any ClinVar-derived code) [done: 883 of 883 variants back; agreement 87.2% with all codes (PP5 and PS4 read ClinVar), 59.9% without ClinVar, against 56.9% for the rules; without ClinVar BIAS finds 130 of 385 pathogenic variants against our 50, but its P/LP calls are right 76% of the time against our 94%, with 3 reversals against none]
  - [x] 6g. MST and AIM, two PRs: (1) MST (`synth/mst.py`; decided 2026-11-22: `mbi` 2.1.0, private-pgm's library, with the authors' MST adapted, since dpmm needs Python below 3.12 and SmartNoise needs opacus below 0.15; seeded sources only, as the VAE) [done: releases 19 to 22; at epsilon 4 column TVD 0.001, pair TVD 0.021, TSTR AUC 0.754, best of every release; trial draws 100% cover, 0% spurious], (2) AIM with a workload from the trial emulation and cohort queries (`synth/aim.py`; decided 2026-11-23: the authors' AIM adapted on `mbi`, workload in each spec at weight 5 plus every pair at 1; releases made and scored on Fargate, `scripts/run_synth.py`) [done: releases 23, 24, 56, 57; on the person summary at epsilon 4 pair TVD 0.006, under the noise floor, TSTR AUC 0.790 against 0.804 real, best of every release; on the trial worse than MST, 10% of draws spurious at both epsilons, and release 23 gives HR 0.14 against the real 1.00, kept as the example]

# Local-first move

## Done 2026-10-12: run locally, no AWS (superseded 2026-11-19)

Goal: anyone can clone the repo, install it, and run every module on their own machine without an AWS account. It came before module 4 and changed the platform the remaining modules build on.

Decided 2026-10-12: PostgreSQL with pgvector replaces both DuckDB and Aurora (17 at first, to match Aurora; 18 later the same day). The app will have concurrent writers and large vector search (RAG), which DuckDB's single-writer file does not fit. It runs locally from `docker-compose.yml`, and tests run against that database.

- [x] `docker-compose.yml` with the database service
- [x] Port module 1 from DuckDB to Postgres. The 1,325,353-row reconciliation, the counts in `docs/etl_synthea_comparison.md`, and both cohorts reproduce exactly
- [x] CI runs the tests against a Postgres service container
- [x] Plan the move (agreed 2026-10-12): Anthropic API replaces Bedrock (each user brings `ANTHROPIC_API_KEY`); no auth, the app binds to 127.0.0.1; everything runs in Docker Compose (`db` plus one `app` container serving the API, agent, and static frontend). Dropped: Guardrail, AgentCore (Runtime, Gateway, Observability, Evaluations), S3, Secrets Manager, Cognito, Budgets, CDK. Work in four PRs:
  - [x] 1. Agent on the Anthropic API, served at `POST /agent`; evals run against it
  - [x] 2. Remove auth; FastAPI serves the frontend; `app` service in Compose
  - [x] 3. Delete `infra/`, the AWS scripts and dependencies; migrations run with plain Alembic
- [x] Rewrite "Stack decisions", "Conventions", and the README install steps for the local stack
- [x] Tear down the deployed AWS stacks (2026-10-12). `deploy.yml` and the `cdk-diff` CI job are gone; `lint-test` is the only required check
