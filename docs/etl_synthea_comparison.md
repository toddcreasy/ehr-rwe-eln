# ETL-Synthea comparison

Our [Synthea](https://github.com/synthetichealth/synthea) to [OMOP](https://ohdsi.github.io/CommonDataModel/cdm54.html) ETL (`src/ehr_rwe_eln/cohort/etl.py`) checked against [OHDSI](https://www.ohdsi.org) [ETL-Synthea](https://github.com/OHDSI/ETL-Synthea), the
reference implementation, on the same input. Run on 2026-10-12.

**Inputs, identical on both sides:** 1,172 Synthea 3.3.0 patients (`scripts/generate_synthea.py --patients 1000`,
seed 42, reference date 2026-01-01) and the same [Athena](https://athena.ohdsi.org) vocabulary download ([SNOMED](https://www.snomed.org) 2026-03 US,
[LOINC](https://loinc.org) 2.82, [RxNorm](https://www.nlm.nih.gov/research/umls/rxnorm/index.html) 2026-06-01, [CVX](https://www2.cdc.gov/vaccines/iis/iisstandards/vaccines.asp?rpt=cvx) 2026-04, [ICD10CM](https://www.cdc.gov/nchs/icd/icd-10-cm/index.html) FY2027).

**Reference:** ETL-Synthea commit `9ee6eb1` (ETLSyntheaBuilder 2.1), CDM 5.4, Synthea version
3.3.0, on Postgres 16 in a throwaway local container. To rerun: `scripts/etl_synthea_reference.R`,
then `scripts/compare_etl_synthea.py`.

## Result

Every difference is explained. None points to an error in our ETL; two point to bugs in
ETL-Synthea.

"Ours, mapped" leaves out rows with `concept_id = 0`, which ETL-Synthea drops by design.

| Table | Ours | Ours, mapped | ETL-Synthea | Difference |
|---|---:|---:|---:|---:|
| person | 1,172 | 1,172 | 1,172 | 0 |
| observation_period | 1,172 | 1,172 | 1,172 | 0 |
| death | 172 | 172 | 160 | +12 |
| visit_occurrence | 80,726 | 80,726 | 73,194 | +7,532 |
| condition_occurrence | 20,484 | 19,670 | 19,646 | +24 |
| procedure_occurrence | 97,900 | 85,424 | 85,385 | +39 |
| drug_exposure | 87,009 | 87,009 | 84,748 | +2,261 |
| measurement | 748,974 | 719,200 | 719,191 | +9 |
| observation | 368,834 | 368,569 | 351,159 | +17,410 |
| device_exposure | 2,095 | 1,959 | 1,866 | +93 |

## Why each table differs

**Domain routing (conditions +24, procedures +39, measurements +9, devices +93, part of
drugs and observations).** We route every source row by its standard concept's domain. ETL-Synthea
reads a fixed set of source files per table: procedures only from the procedures file, devices
only from devices, observations from allergies, conditions, and observations. So, for example, a
Synthea procedure whose standard concept is a device lands in `device_exposure` for us and nowhere
for ETL-Synthea (93 rows). It also requires a condition's source concept to be in the Condition
domain; we follow the target concept, which is the OMOP convention ("Prematurity of infant", 23
rows).

**drug_exposure +2,261.** Medications match exactly (69,610 both). Vaccines differ by 1,964:

| Rows | Cause |
|---:|---|
| 1,420 | COVID-19 vaccines (CVX 207, 208, 212) map to a standard RxNorm concept. ETL-Synthea only accepts CVX targets for vaccines and drops them. |
| 544 | **ETL-Synthea bug.** Hep B pediatric (CVX `08`) and MMR (CVX `03`): it loads Synthea's code column as a number, `08` becomes `8`, and the code no longer matches Athena. We read codes as text. |
| 297 | Synthea procedures whose standard concept is a drug (domain routing). |

**observation +17,410.** 18,378 rows are Synthea procedures whose standard concept is an
observation (domain routing). Offsetting that, ETL-Synthea converts allergies (993 rows) and we do
not yet.

**visit_occurrence +7,532.**

| Rows | Cause |
|---:|---|
| 3,672 | **ETL-Synthea bug.** It selects encounter class `'urgent'`; Synthea writes `'urgentcare'`, so every urgent care visit is dropped. |
| 738 | Virtual, home, hospice, and skilled nursing encounters: ETL-Synthea drops these classes. We map them to Telehealth, Home Visit, and Non-hospital institution Visit. |
| 3,089 | ETL-Synthea merges outpatient encounters on the same day into one visit; we keep one visit per encounter. |
| 32 | Overlapping inpatient stays merged. |
| 1 | Emergency visits merged. |

**death +12.** ETL-Synthea builds deaths from "Death Certification" encounters (SNOMED 308646001)
whose reason code maps to a SNOMED condition, and records that as the cause of death. 12 deceased
patients do not meet that and are dropped. We take every `DEATHDATE` but record no cause.

## Field values that differ on purpose

Found by the data quality checks (2026-10-13); row counts are unaffected.

- **Units.** ETL-Synthea writes `unit_concept_id = 0` for every observation and for any
  measurement unit it cannot match. We follow the OMOP convention: NULL when the source has no
  unit, 0 only for a unit that does not map. Synthea's annotations on categorical results and
  scores (`{nominal}`, `{presence}`, `n/a`, `{score}`) are not units, so both
  `unit_concept_id` and `unit_source_value` load NULL: DQD counts a NULL unit next to unit text
  as missing, and expects scores to carry no unit. Synthea also spells 10 [UCUM](https://ucum.org) units
  differently from OMOP's codes (`U/L` for `[U]/L`, `/a` for `/y`); `etl.UNIT_CODES`
  translates them. `{#}`, `{count}`, `{SG}`, and `{T-score}` have no OMOP unit and stay 0.
- **Visits.** ETL-Synthea writes `admitted_from_concept_id` and `discharged_to_concept_id` as 0,
  which OMOP defines as "home". Synthea records neither, so we leave them NULL.

## Gaps this exposed in our ETL

- Allergies are not converted (ETL-Synthea writes 993 observation rows from them).
- Cause of death is not recorded (`death.cause_concept_id`); ETL-Synthea fills it from the death
  certification encounter.
