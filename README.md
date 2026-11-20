# ehr-rwe-eln

Real world evidence (RWE) from synthetic electronic health records (EHR), linked to electronic lab notebook (ELN) data. Seven modules share one [OMOP CDM v5.4](https://ohdsi.github.io/CommonDataModel/cdm54.html) database: they build it from synthetic patients, check its quality, emulate target trials on it, write lab results into it, release private synthetic copies of it, simulate a genotyping study on its people, and curate the real variants planted in them.

ELN platforms capture bench data well, and few reach past the lab. Revvity's Signals Translational joins biomarker results to clinical trial data, and LabKey links assay results to study participants, but none of them writes notebook results into OMOP or EHR data. The ELN bridge works in that gap: it reads free-text notebook entries with Claude and writes the results next to the clinical record. [Background on ELN platforms and the gap](docs/modules/eln.md#background-what-eln-platforms-do).

The web app is called **RWE Workbench**. Its home page at http://127.0.0.1:8000 describes the project and shows the five sections (data quality, trial emulation, lab notebook, variant curation, synthetic data) as tabs, each with a live figure from that section's data.

Acronyms and services are defined in the [glossary](docs/GLOSSARY.md).

Everything runs on one machine in [Docker Compose](https://docs.docker.com/compose/). No cloud account; the only outside service is the [Anthropic API](https://docs.claude.com), on your own key.

> **Synthetic data only.** [Synthea](https://github.com/synthetichealth/synthea) patients, generated ELN entries, and simulated genotypes. No real patient data, and no clinical claims. Outputs are for research and demonstration.

## Modules

| Module | What it does | Result |
|---|---|---|
| [Cohort pipeline](docs/modules/cohort.md) | Synthea patients to OMOP CDM v5.4; cohorts from YAML | Checked against [OHDSI](https://www.ohdsi.org) [ETL-Synthea](https://github.com/OHDSI/ETL-Synthea), [every difference explained](docs/etl_synthea_comparison.md) |
| [Data quality](docs/modules/data_quality.md) | All 2,384 OHDSI [DataQualityDashboard](https://github.com/OHDSI/DataQualityDashboard) checks, scored, with a dashboard | [Identical to DQD](docs/dqd_comparison.md) on every check; 99.41% pass |
| [Target trial emulation](docs/modules/trial_emulation.md) | Trial protocols in YAML; propensity weighting, survival, a bias report | Weighted hazard ratios with negative controls; says "not estimable" when arms don't overlap |
| [ELN to EHR bridge](docs/modules/eln.md) | Claude extracts samples and results from notebook text into OMOP and [FHIR R4](https://hl7.org/fhir/R4/) | Precision and recall 1.000 on 300 entries; resists prompt injection |
| [Synthetic genomics](docs/modules/genomics.md) | A [dbGaP](https://www.ncbi.nlm.nih.gov/gap/)-style genotype study with a planted effect, and a GWAS; a clinical panel of real ClinVar variants at their GRCh38 positions | Finds the planted effect; calibrated across 16 rebuilt studies |
| [Variant curation](docs/modules/curation.md) | ACMG/AMP criteria with each gene's [ClinGen](https://clinicalgenome.org) expert panel thresholds, from gnomAD and Ensembl VEP; Claude proposes literature evidence, every quote checked against its paper; HPO phenotype scores as context; a curator decides on `/curation/`, with who and when | On 578 ClinVar expert-panel variants, its pathogenic calls agree 98% of the time and its benign calls 96%; no reversals. Criterion by criterion against 883 Evidence Repository curations, PM2, PVS1, and PS3 match the panel 96% to 97% of the time |
| [Synthetic data](docs/modules/synthetic_data.md) | Differentially private releases with fidelity, privacy, and trial parity reports | Every release at chance on every privacy attack; [methodology](docs/synthetic_data_methodology.md) |

The table is in run order: the cohort pipeline builds the OMOP tables every other module reads, and the rest follow.

## Architecture

<a href="https://toddcreasy.github.io/ehr-rwe-eln/architecture.svg"><img src="docs/architecture.svg" alt="ehr-rwe-eln architecture. Top: a browser reaches the app container (FastAPI plus a static Next.js frontend), which reads Postgres 18 with pgvector; scripts on the host write to Postgres; a Hail container runs on request. Middle: Synthea output and Athena vocabularies feed the cohort pipeline, which builds the OMOP CDM v5.4 tables. Data quality, target trial emulation, synthetic data, and synthetic genomics read OMOP and write their own schemas and files. The ELN bridge sends free-text entries to Claude on the Anthropic API and writes specimen and measurement rows into OMOP and a FHIR R4 bundle. Variant curation classifies the genomics panel's variants, with literature evidence proposed by Claude, and a curator decides. Bottom: pre-commit, pull requests, GitHub Actions, pytest, and evals." width="100%"></a>

Click the diagram for [the interactive version](https://toddcreasy.github.io/ehr-rwe-eln/architecture.svg): hover a box for what it does and why, and click it for its source or docs. GitHub shows the diagram above as a plain image. [ARCHITECTURE.md](docs/ARCHITECTURE.md) walks through it, with the stack and the known gaps.

## Install

[INSTALL.md](docs/INSTALL.md) has every step, from prerequisites to running each module and the app. You need uv, Docker Desktop, Java for Synthea, an Anthropic API key, and a free vocabulary download from [OHDSI Athena](https://athena.ohdsi.org). A full build takes about an hour.

## Documentation

| Document | What's in it |
|---|---|
| [INSTALL.md](docs/INSTALL.md) | Prerequisites, configuration, building the data, running the modules and the app, troubleshooting |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | The diagram, how data moves, the stack and why, design decisions, known gaps |
| [Module pages](#modules) | One per module: what it does, how to run it, results |
| [GLOSSARY.md](docs/GLOSSARY.md) | Every acronym, standard, method, and service, defined, with links to their official pages |
| [ETL-Synthea comparison](docs/etl_synthea_comparison.md) | The cohort pipeline against OHDSI's reference ETL |
| [DQD comparison](docs/dqd_comparison.md) | The former Python data quality checks against OHDSI's DataQualityDashboard (historical) |
| [Synthetic data methodology](docs/synthetic_data_methodology.md) | Threat model, mechanisms, evaluation, and results, for reviewers |
| [NIST AI RMF mapping](docs/nist_ai_rmf.md) | The synthetic data work against NIST's AI Risk Management Framework |
| [NIH and HHS requirements](docs/nih_hhs_requirements.md) | What a real controlled-access source would require |
| [SETUP.md](docs/SETUP.md) | Build history, including the AWS version this replaced |

## Data and licensing

- Synthea output is synthetic and carries no patient privacy risk.
- OMOP vocabularies come from OHDSI Athena under their own licenses and are never committed.
- Nothing under `data/` is committed.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
