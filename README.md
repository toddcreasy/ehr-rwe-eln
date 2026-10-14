# ehr-rwe-eln

Real world evidence from synthetic electronic health records, linked to electronic lab notebook data. One OMOP CDM v5.4 database feeds five modules: a cohort pipeline, an ELN to EHR bridge, a target trial emulation toolkit, a data quality dashboard, and privacy-preserving synthetic data releases. Runs entirely on your machine in Docker Compose: PostgreSQL 18 with pgvector, plus one app container. No cloud account needed; the agent calls the Anthropic API with your own key.

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

### Privacy-preserving synthetic data (`ehr_rwe_eln.synth`)

Treats the OMOP build as if it were a controlled-access source and releases synthetic copies of it under differential privacy, so they can be shared and tested against without exposing the people in it.

- Release specs in YAML: the source table's columns, each column's domain (fixed in the spec, never read from the data), and a declared Bayesian network structure
- A differentially private Bayesian network synthesizer on diffprivlib: noisy histograms of each column with its parents, the privacy budget (epsilon) split across them and enforced by a budget accountant, then sampling from the noisy counts
- An independent-columns baseline, which keeps each column's distribution and loses every relationship between columns
- Each release stored in the `synth` schema with its provenance: the spec as run, each histogram's epsilon, the source, the seed, and the code version
- A variational autoencoder (PyTorch) trained with DP-SGD through Opacus, using the same encoding, as a generative model to compare against
- A fixed 30% of people held out of every release (by a hash of `person_id`), to evaluate against
- Fidelity and utility reports per release: total variation distance per column and per pair of columns, KS statistics, the correlation gap, and train-on-synthetic, test-on-real AUC, each read against the noise floor of the real holdout against the real training set
- Downstream parity: a second spec synthesizes the analysis table of module 4's lisinopril versus amlodipine trial, and each release is run through the trial's own propensity-weighted Cox analysis, once and over 20 more draws, counting how often the interval covers the real hazard ratio and how often it shows an effect the real data does not
- Privacy risk reports per release: distance to closest record, a membership inference attack, and attribute inference through quasi-identifiers, each comparing training people with held-out people and read against the same attacks on a plain copy of the training data, plus a plain-language summary
- A data card per release: what it is, how it was made, its privacy spend per mechanism, fidelity against the noise floor, trial parity, privacy risk against a copy of the training data, intended use, and limitations
- For reviewers: the [methodology](docs/synthetic_data_methodology.md) (threat model, mechanisms, evaluation, results, limits) and a [NIST AI RMF mapping](docs/nist_ai_rmf.md) with its gaps

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
- **Data**: OMOP CDM v5.4 on PostgreSQL 18 with pgvector, in Docker Compose; schema changes with Alembic
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
| Module 7: data quality | Done: all DQD v2.9.0 checks, scoring, and dashboard, matched against DQD itself ([comparison](docs/dqd_comparison.md)) |
| Module 4: target trial emulation | Done: protocols, propensity scores, survival estimates, bias report with negative controls, and its page |
| Synthetic data | In progress: DP Bayesian network synthesizer, DP-SGD variational autoencoder, and independent baseline, with versioned releases, provenance, fidelity and utility reports, trial parity, privacy risk reports, and a data card per release |
| Module 2: ELN to EHR bridge | Done: synthetic ELN entries (default and hard), batch extraction on MODEL_SMALL with a per-trap precision and recall eval, written to OMOP specimen and measurement rows and a FHIR R4 bundle of Specimen and Observation resources |

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

`uv run python scripts/run_dq.py` runs the 2,384 checks from OHDSI DataQualityDashboard v2.9.0 against the CDM (about 20 s) and stores the run in the `dq` schema. The dashboard at http://127.0.0.1:8000/dq/ shows the latest run.

`uv run python scripts/run_tte.py` runs each target trial protocol in `src/ehr_rwe_eln/tte/protocols/`, prints its bias report, and stores the run in the `tte` schema (about 1 minute on 23,420 patients). The page at http://127.0.0.1:8000/tte/ shows it. The 1,172-patient default has too few outcome events for estimates; module 4 uses a 20,000-patient build in its own database, `DB_NAME=ehr_rwe_eln_tte` (see `scripts/generate_synthea.py` and `scripts/build_omop.py`). The app shows runs from whichever database `DB_NAME` names.

`uv run python scripts/generate_eln.py` writes 300 synthetic ELN entries on 200 hypertension subjects to `data/eln/`, each with the extraction it should produce, plus the registry linking study codes (`HTN-0001`) to OMOP persons. `uv run python scripts/extract_eln.py` loads them into the `eln` schema and extracts every entry with `MODEL_SMALL` through the Message Batches API (half price; about 8 minutes for 300 entries), then scores the extractions against the known answers. `uv run python scripts/write_eln_omop.py` writes them to OMOP `specimen` and `measurement` rows, linked through `fact_relationship`, and can be rerun. `uv run python scripts/export_eln_fhir.py` writes the same samples and results to `data/eln/fhir_bundle.json` as FHIR R4 `Specimen` and `Observation` resources; samples without a stated collection date carry none there.

`DB_NAME=ehr_rwe_eln_tte uv run python scripts/synthesize.py` makes every release in `src/ehr_rwe_eln/synth/specs/person_summary.yaml` from the 20,000-patient build (under a minute; the VAE releases train on CPU) and stores each in the `synth` schema. The spec is seeded because its source is synthetic; a spec over real data must leave `seed` null, so the noise comes from a secure generator and cannot be regenerated. Each release trains on 70% of people; `DB_NAME=ehr_rwe_eln_tte uv run python scripts/evaluate_synth.py` scores every release against the 30% held out, stores the reports in `synth.report`, and prints them under the noise floor. `--spec src/ehr_rwe_eln/synth/specs/trial_lisinopril_amlodipine_ckd.yaml` on `synthesize.py` makes trial-table releases, which the same evaluation also reruns the trial on (about a minute in all). The reports read real data and are for internal review, not for release: they are not differentially private. `DB_NAME=ehr_rwe_eln_tte uv run python scripts/synth_cards.py` then writes a data card per release to `data/synth/cards/`.

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
