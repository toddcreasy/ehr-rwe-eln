# Install and run

Everything runs on one machine. There is no cloud account to set up; the only outside service is the [Anthropic API](https://docs.claude.com), on your own key, and only the ELN (electronic lab notebook) extraction and the agent call it.

Terms are defined in the [glossary](GLOSSARY.md). A full build from a fresh clone takes about an hour, most of it [Synthea](https://github.com/synthetichealth/synthea) and the 20,000-patient load. One step needs you at a browser: the vocabulary download from [OHDSI Athena](https://athena.ohdsi.org).

## Contents

1. [Prerequisites](#prerequisites)
2. [Clone and configure](#clone-and-configure)
3. [Start the database](#start-the-database)
4. [Get the vocabularies](#get-the-vocabularies)
5. [Build the data](#build-the-data)
6. [Run the modules](#run-the-modules)
7. [Run the app](#run-the-app)
8. [Tests and evals](#tests-and-evals)
9. [Stop and clean up](#stop-and-clean-up)
10. [Troubleshooting](#troubleshooting)

## Prerequisites

| Tool | Why | Check |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Installs Python 3.14 and every dependency from `uv.lock` | `uv --version` |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | Runs Postgres and the app | `docker compose version` |
| Java 17 or newer | Synthea, the synthetic patient generator, is a Java program | `java -version` |
| Node.js 24 | Builds the frontend; only needed outside Docker | `node --version` |
| AWS credentials with Bedrock access (`aws sso login`) | ELN extraction, the agent, the evals, and the lake | Your AWS account |

On a Mac, `brew install openjdk@21` gives you Java. Homebrew installs it keg-only, so either put `/opt/homebrew/opt/openjdk@21/bin` on your `PATH` or prefix the Synthea commands with it.

## Clone and configure

```bash
git clone https://github.com/toddcreasy/ehr-rwe-eln.git
cd ehr-rwe-eln
cp .env.example .env
uv sync
uv run pre-commit install
```

Open `.env` and set `DB_PASSWORD` (any long random string; `openssl rand -hex 24` makes one) and `LAKE_TABLE_BUCKET_ARN`. Leave the rest blank to take the defaults. Claude runs on Amazon Bedrock with your AWS credentials; there is no API key.

| Variable | Default | Notes |
|---|---|---|
| `DB_HOST`, `DB_PORT`, `DB_USER` | `localhost`, `5432`, `postgres` | Match `docker-compose.yml` |
| `DB_NAME` | `ehr_rwe_eln` | The database the scripts and the app use |
| `DB_PASSWORD` | none | Required |
| `MODEL` | `us.anthropic.claude-opus-4-6-v1` | Every model call uses it, on Amazon Bedrock |
| `LOG_LEVEL`, `FRONTEND_DIR`, `APP_PORT` | `INFO`, `frontend/out`, `8000` | |

`.env` is gitignored and is the only place secrets live. A variable exported in your shell overrides the one in `.env`, so don't export the `DB_*` or `MODEL` variables.

## Start the database

```bash
docker compose up -d --wait db
uv run alembic upgrade head
uv run python scripts/db_check.py
```

Postgres 18 with [pgvector](https://github.com/pgvector/pgvector) listens on 127.0.0.1:5432. `alembic upgrade head` creates the `dq`, `tte`, `eln`, `synth`, and `curation` schemas. `db_check.py` runs a pgvector round trip and leaves nothing behind.

## Get the vocabularies

[OMOP](https://ohdsi.github.io/CommonDataModel/cdm54.html) stores every diagnosis, drug, and lab test as a numeric concept. The tables that define those concepts come from [OHDSI Athena](https://athena.ohdsi.org), under each vocabulary's own license, so they are never committed and you download them yourself. Make two downloads:

1. **Clinical vocabularies**: tick [SNOMED](https://www.snomed.org), [LOINC](https://loinc.org), [RxNorm](https://www.nlm.nih.gov/research/umls/rxnorm/index.html), [CVX](https://www2.cdc.gov/vaccines/iis/iisstandards/vaccines.asp?rpt=cvx), and [ICD10CM](https://www.cdc.gov/nchs/icd/icd-10-cm/index.html), and nothing else. Athena adds the small ones the ETL also needs ([UCUM](https://ucum.org) units, Visit, Type Concept, CDM) on its own. Unzip into `data/vocab/`.
2. **Demographics**: Gender, Race, and Ethnicity. Unzip into `data/vocab_extra/`.

Leave [CPT4](https://www.ama-assn.org/practice-management/cpt) unticked. A download that includes it ships the CPT4 relationships without the CPT4 concepts, which Athena fills in only after you run its `cpt.sh` with a [UMLS](https://www.nlm.nih.gov/research/umls/index.html) key, and the build then fails adding foreign keys (`Key (concept_id_1)=(2102101) is not present in table "concept"`). This project uses no CPT4 codes.

The published counts were built from SNOMED 2026-03 US, LOINC 2.82, RxNorm 2026-06-01, CVX 2026-04, and ICD10CM FY2027. Other versions work; the counts will differ slightly. `data/vocab/VOCABULARY.csv` lists what you got.

## Build the data

One Synthea population, loaded into `ehr_rwe_eln`:

```bash
uv run python scripts/generate_synthea.py
uv run python scripts/build_omop.py
uv run python scripts/build_cohorts.py
```

`generate_synthea.py` downloads Synthea 3.3.0, checks its SHA-256, and runs it with a fixed seed and reference date, so the same arguments always give the same people: 23,421 by default (20,000 living plus those who died during the simulation). `build_omop.py` loads the vocabularies, runs the ETL (extract, transform, load), builds condition and drug eras, then adds keys and indices. The build takes about five minutes.

## Run the modules

Each module has its own page with what it does and how to read its output. The commands, in build order:

```bash
# Data quality (about 2 minutes)
uv run python scripts/run_dq.py

# Target trial emulation (about 1 minute)
uv run python scripts/run_tte.py

# ELN bridge (extraction takes minutes and is billed)
uv run python scripts/generate_eln.py
uv run python scripts/extract_eln.py
uv run python scripts/write_eln_omop.py
uv run python scripts/export_eln_fhir.py

# Synthetic genomics
uv run python scripts/generate_genomics.py
uv run python scripts/run_gwas.py
docker compose run --rm --build hail      # optional: the same GWAS in Hail, a 2.4 GB image
uv run python scripts/generate_panel.py   # clinical panel: downloads ClinVar (200 MB) once

# Variant curation
uv run python scripts/curate_variants.py --set panel   # the panel's 48 variants
uv run python scripts/curate_variants.py --set eval    # scored against ClinVar expert panels
uv run python scripts/curate_variants.py --set erepo   # criterion by criterion, ClinGen Evidence Repository
uv run python scripts/curate_literature.py --dry-run   # literature retrieval and token count; drop --dry-run to call Claude

# Synthetic data
export SPEC=src/ehr_rwe_eln/synth/specs/trial_lisinopril_amlodipine_ckd.yaml
uv run python scripts/synthesize.py
uv run python scripts/synthesize.py --spec $SPEC
uv run python scripts/evaluate_synth.py
uv run python scripts/synth_cards.py
```

Details: [cohort pipeline](modules/cohort.md), [data quality](modules/data_quality.md), [target trial emulation](modules/trial_emulation.md), [ELN bridge](modules/eln.md), [synthetic genomics](modules/genomics.md), [synthetic data](modules/synthetic_data.md).

## Run the app

```bash
(cd frontend && npm ci && npm run build)   # once, and after frontend changes
uv run fastapi dev                         # http://127.0.0.1:8000, reloads on save
```

To run the app in Docker instead, `docker compose up -d --build --wait` builds the frontend into the image and serves everything on http://127.0.0.1:8000. Both ports bind to 127.0.0.1 only, because there is no sign-in. The same command starts the `monitor` service, which reruns the privacy checks on the synthetic releases every `MONITOR_INTERVAL_HOURS` (default 24) when a source or the synth code has changed; outside Docker, `uv run python -m ehr_rwe_eln.synth.monitor --once` runs one check.

```bash
curl localhost:8000/api/health/db
curl -X POST localhost:8000/api/agent -H 'Content-Type: application/json' \
  -d '{"prompt": "Is the database reachable?"}'
```

## Tests and evals

```bash
uv run ruff check .
uv run pytest          # fast tests against the Compose Postgres, about 20 s
uv run pytest evals    # golden cases against the real model, about 6 minutes, billed
```

Tests run in their own database, `ehr_rwe_eln_test`, and roll back everything they write. Plain `uv run pytest` never collects `evals/`.

## Stop and clean up

```bash
docker compose down      # stop; data stays in the ehr-rwe-eln-db volume
docker compose down -v   # stop and delete the databases
```

Generated files live under `data/`, which is gitignored: Synthea output, vocabularies, ELN entries, the genotype study, data cards, and the code-to-person registries in `data/registry/`.

## Troubleshooting

**`docker: command not found` after installing Docker Desktop.** In its user install mode, Docker Desktop puts its command-line links in `~/.docker/bin`. Add `export PATH="$HOME/.docker/bin:$PATH"` to `~/.zshrc`, or switch to the system install under Settings, Advanced.

**`Unable to locate a Java Runtime`.** macOS ships a `java` stub with no runtime behind it. Install one (see [Prerequisites](#prerequisites)).

**`schema cdm already exists`.** `build_omop.py` refuses to load over an existing build. Drop it first: `docker compose exec -T db psql -U postgres -d <database> -c "DROP SCHEMA cdm CASCADE"`.

**`StaticFiles directory 'frontend/out' does not exist`.** The frontend has not been built in this checkout. Run `npm ci && npm run build` in `frontend/`.
