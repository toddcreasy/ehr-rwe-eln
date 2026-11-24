# DataQualityDashboard comparison

Historical. This compared the Python port of DQD's checks with DQD itself. The port was removed on 2026-11-20, once DQD ran on the lake and matched it check for check; data quality now runs DQD directly ([data_quality.md](modules/data_quality.md)). The scripts named below are in git history before that date.

The data quality checks (`src/ehr_rwe_eln/dq/`) checked against [OHDSI](https://www.ohdsi.org) [DataQualityDashboard](https://github.com/OHDSI/DataQualityDashboard)
(DQD), the reference implementation, on the same databases. Run on 2026-10-13, last on
PostgreSQL 18.6 after the ETL fixes in #35 and #36.

**Reference:** DQD v2.9.0 in R (`data/r-lib`), `executeDqChecks` with `cdmVersion = "5.4"`,
all three check levels (TABLE, FIELD, CONCEPT), default thresholds and default excluded tables.

**Inputs:**
- The local CDM: 1,172 [Synthea](https://github.com/synthetichealth/synthea) patients (`scripts/generate_synthea.py --patients 1000`; the project now builds 23,421 by default), as built by the cohort pipeline and the data quality module's prerequisites (keys,
  `cdm_source`, eras).
- A planted CDM (`scripts/build_dq_edge_cdm.py`, schema `dq_edge` in the test database) with
  a missing table, a duplicate primary key, a dangling foreign key, an implausible birth year,
  reversed dates, a condition with no era, a female-only condition on a male, a descendant of a
  male-only finding on a female, and a lab in an implausible unit. It exists to reach the
  scoring paths the real data never does: errors, missing objects, and failing concept checks.

## Result

Identical on both inputs. Every one of the 2,384 checks matches on every field compared, and
DQD's Overview matches line for line.

Fields compared per check: `numViolatedRows`, `numDenominatorRows`, `pctViolatedRows`,
`thresholdValue`, `failed`, `passed`, `isError`, `notApplicable`, `notApplicableReason`,
`checkDescription`, `category`, `subcategory`, `context`. Matching on `checkId` also checks the
ids themselves, including concept checks on two concepts (`..._4090861,4025213`).

| | Local CDM | Planted CDM |
|---|---:|---:|
| Checks, ours and DQD | 2,384 | 2,384 |
| Checks with any field different | 0 | 0 |
| Failed | 9 | 28 |
| Queries that errored (`countErrorFailed`) | 0 | 75 |
| Scored as errors (`isError`) | 0 | 59 |
| Not applicable | 1,139 | 1,733 |
| DQD `percentPassed` | 99.62 | 98.83 |

No concept check fails on the local CDM: Synthea writes no records for the wrong sex and no lab
in an unlisted unit. 395 of the 472 concept checks are not applicable there, because the
concept (or, for unit checks, a mapped unit) never appears.

On the planted CDM both sides fail the same 28 checks. They include `cdmTable` for the missing
SPECIMEN table (scored as failed, not as an error, because the error says the table does not
exist), the duplicate `person_id`, the dangling `person_id`, the concept foreign keys on
populated rows (the planted CDM has no vocabulary), the 1849 birth year, the reversed drug
dates (caught by both `plausibleStartBeforeEnd` and the older `plausibleTemporalAfter`), the
condition with no era, and all three concept checks: `plausibleGender` (1 of 1),
`plausibleGenderUseDescendants` (1 of 1), and `plausibleUnitConceptIds` (1 of 2). All 75
errored queries are on SPECIMEN: `cdmTable` (failed), 15 `cdmField` checks (not applicable,
since the table itself is missing), and 59 other checks, scored as errors and not applicable.

Run time on the local CDM: about 20 s for ours, 60 s for DQD.

## Differences that are not differences

**DQD's JSON rounds `pctViolatedRows` to 4 decimals.** DQD writes the file with
`jsonlite::toJSON(result)` (`R/writeResultsTo.R`), and jsonlite keeps 4 decimals by default.
Thresholds are evaluated before that, on the unrounded value, which is why `failed` matches on
every check. The comparison rounds ours the same way; without that, 82 checks differ in the
fifth decimal or later.

**DQD's JSON trims trailing spaces from check descriptions.** The CSV text keeps them. The
comparison strips both.

## A DQD limitation: a missing column stops the run

With one column dropped from the planted CDM (`note.note_text`), DQD v2.9.0 does not finish.
`measureValueCompleteness` errors on the missing column, so its denominator is NA, while the
table's other fields return a number. `.calculateNotApplicableStatus` then finds two values
for "is NOTE empty" and calls `stop()` ("Duplicate table names in emptyTables"). This happens
for any missing field, on empty and populated tables alike.

Ours does not stop there: an unknown denominator counts as "not empty", the reading DQD's own
`coalesce(..., FALSE)` gives it, and the field's checks are scored not applicable because
`cdmField` failed. That path was covered by `tests/test_dq.py`, removed with the port, but it cannot be checked against
DQD, so the planted CDM leaves the column in place.

## To rerun

These commands ran the comparison and no longer run on `main`: the three scripts are in git history before 2026-11-20. From the repo root, with the Compose database running and `JAVA_HOME` set as in the R script's
header:

```bash
# Local CDM
R_LIBS_USER=$PWD/data/r-lib Rscript scripts/dqd_reference.R
uv run python scripts/compare_dqd.py

# Planted CDM
uv run python scripts/build_dq_edge_cdm.py
R_LIBS_USER=$PWD/data/r-lib Rscript scripts/dqd_reference.R ehr_rwe_eln_test dq_edge dqd-edge.json
uv run python scripts/compare_dqd.py --database ehr_rwe_eln_test --schema dq_edge --reference dqd-edge.json
```

DQD's JSON goes to `data/dqd/`, which is gitignored.
