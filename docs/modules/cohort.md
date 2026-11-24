# EHR to RWE cohort pipeline

Package: `ehr_rwe_eln.cohort`. Back to the [README](../../README.md). Terms are defined in the [glossary](../GLOSSARY.md).

Turns synthetic electronic health records (EHR) into an [OMOP CDM v5.4](https://ohdsi.github.io/CommonDataModel/cdm54.html) database, then builds the cohorts real world evidence (RWE) studies start from. Every other module reads what this one writes.

## What it does

1. **Generate patients.** [Synthea](https://github.com/synthetichealth/synthea) 3.3.0 simulates each person's medical history and writes CSV files. The seed (42) and reference date (2026-01-01) are fixed, so the same command always makes the same people.
2. **Load vocabularies.** The [OHDSI Athena](https://athena.ohdsi.org) tables that define every standard concept: [SNOMED](https://www.snomed.org) for conditions, [RxNorm](https://www.nlm.nih.gov/research/umls/rxnorm/index.html) for drugs, [LOINC](https://loinc.org) for lab tests, [CVX](https://www2.cdc.gov/vaccines/iis/iisstandards/vaccines.asp?rpt=cvx) for vaccines.
3. **Run the ETL** (`etl.py`). Maps each [Synthea](https://github.com/synthetichealth/synthea) code to its standard concept and routes the row to the table its concept's domain names, so a Synthea procedure whose concept is a drug lands in `drug_exposure`.
4. **Build eras** (`eras.py`). Condition and drug eras: spans of continuous illness or exposure, as [OHDSI](https://www.ohdsi.org) tools expect.
5. **Add keys and indices** (`cdm.py`), after the load, which is faster than loading into an indexed table.
6. **Build cohorts** (`spec.py`) from YAML definitions into the OMOP `cohort` table.
7. **Publish to the lake** (`lake.py`). Copies every OMOP table from the staging Postgres into Apache Iceberg tables in the S3 table bucket `ehr-rwe-eln-omop`, namespace `cdm`, then checks the copy table by table through Redshift. On AWS, OMOP is served only from the lake; the Postgres the ETL runs in is staging.

## Cohort definitions

A definition names the entry event, the inclusion rules, and when follow-up ends. From `definitions/t2dm_new_diagnosis.yaml`:

```yaml
entry:
  domain: condition
  concept_ids: [201826] # Type 2 diabetes mellitus (SNOMED), with descendants
inclusion:
  prior_observation_days: 365
  min_age: 18
  index_from: 2015-01-01
exit:
  strategy: end_of_observation
```

Concept IDs include their descendants, so one SNOMED code covers every more specific diagnosis under it. `build_cohorts.py` prints an attrition table: how many people survive each rule.

## Run it

```bash
uv run python scripts/generate_synthea.py
uv run python scripts/build_omop.py
uv run python scripts/build_cohorts.py
uv run python scripts/publish_omop.py      # needs LAKE_TABLE_BUCKET_ARN in .env and AWS credentials
uv run python scripts/reconcile_lake.py    # exits 1 if any table differs from Postgres
```

`publish_omop.py --tables person cohort` republishes only those tables. Each table is purged, recreated, and filled in one Iceberg transaction, so it is complete or empty, never partial.

### How the copy is checked

For every table, `reconcile_lake.py` runs one summary query on Postgres and the same query on the lake through the Redshift Data API: the row count, and for each column the non-null count plus its sum (integers), total length (text), or earliest and latest value (dates). Then it compares the cohort sizes. OMOP's `numeric` columns have no fixed precision in Postgres and Iceberg decimals need one, so they are stored as 64-bit floats and their sums compared within one part in a billion.

Redshift reads the lake as `awsdatacatalog.omop_cdm.<table>`, through a Glue resource link that points at the table bucket's catalog (see `infra/terraform/README.md`).

### Who reads the lake

Code that reads OMOP for analysis reads the lake through Redshift: trial emulation (`run_tte.py`), the synthetic data sources (`synthesize.py`, `evaluate_synth.py`, the privacy monitor), and the genomics and ELN scripts (`generate_genomics.py`, `generate_panel.py`, `match_phenotypes.py`, `generate_eln.py`). They connect through `connect_omop()` in `src/ehr_rwe_eln/omop.py`, which uses the Redshift Data API: SQL over HTTPS with your AWS login, one session per run so temp tables last across statements. `OMOP_SOURCE=staging` points them at the staging Postgres instead; the local Compose monitor uses that, since its container has no AWS credentials. On AWS the monitor runs daily as a scheduled ECS task and reads the lake as its own IAM role.

Their SQL runs unchanged on both engines (no Postgres arrays, `DISTINCT ON`, `FILTER`, `make_date`, or correlated `EXISTS`; values written in as integers), so the tests keep checking it on Postgres. `scripts/compare_omop_sources.py` runs every trial protocol, negative control, and synthetic data spec on both and requires identical tables, column types included; it takes about 17 minutes and a few RPU-hours.

Code that writes OMOP stays on staging: the ETL, cohort building (`cdm.cohort`), the ELN bridge (`specimen`, `measurement`, `fact_relationship`), and the genomics panel (`write_panel_omop.py`, `measurement`). After any of them, republish the tables it changed (`publish_omop.py --tables cohort`) and reconcile. Data quality runs OHDSI's DataQualityDashboard on the lake, through Redshift ([data quality](data_quality.md)). One session per run is billed until it ends, so `RedshiftSession` ends it when its `with` block ends, and a script reads what it needs inside the block and computes after it.

## Results

On the 23,421-person build:

| Table | Rows |
|---|---:|
| person | 23,421 |
| visit_occurrence | 1,719,208 |
| condition_occurrence | 418,421 |
| drug_exposure | 1,877,146 |
| measurement | 16,330,385 |
| observation | 7,942,852 |

The two cohorts end with 550 people (new type 2 diabetes diagnoses since 2015) and 885 (new metformin users). The measurement count includes the ELN bridge's lab results.

## Checked against ETL-Synthea

OHDSI's own [ETL-Synthea](https://github.com/OHDSI/ETL-Synthea), written in R, ran on the same input. Every difference is explained in [etl_synthea_comparison.md](../etl_synthea_comparison.md). Most come from choices: this ETL keeps visit classes and vaccines [ETL-Synthea](https://github.com/OHDSI/ETL-Synthea) drops, and routes rows by their concept's domain. Two are bugs in ETL-Synthea. It reads vaccine codes as numbers, so `08` becomes `8` and stops matching, and it selects encounter class `urgent` where Synthea writes `urgentcare`.

## Gaps

- Allergies are not converted; ETL-Synthea writes 993 observation rows from them.
- Cause of death (`death.cause_concept_id`) is not recorded.
- No location is loaded, so there is no geography for linkage testing.
