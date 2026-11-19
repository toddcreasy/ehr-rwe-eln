# RWE data quality dashboard

Package: `ehr_rwe_eln.dq`. Back to the [README](../../README.md). Terms are defined in the [glossary](../GLOSSARY.md).

Profiles the [OMOP](https://ohdsi.github.io/CommonDataModel/cdm54.html) database before anyone trusts an analysis from it. It runs every check in [OHDSI](https://www.ohdsi.org)'s [DataQualityDashboard](https://github.com/OHDSI/DataQualityDashboard) (DQD) v2.9.0, reimplemented in Python, and its results match DQD's on every check.

## What it checks

2,384 checks at three levels, from DQD's own check and threshold files (`dq/csv/`):

| Level | Asks | Example |
|---|---|---|
| Table | Does each table exist, and does it have records? | `measurement` is not empty |
| Field | Are values present, of the right type, in range, and pointing at real rows? | `person.year_of_birth` is not before 1850 |
| Concept | Do specific concepts behave plausibly? | A female-only condition is never recorded on a male |

Each check falls into one category of the [Kahn framework](https://doi.org/10.13063/2327-9214.1244), the standard way to group data quality checks:

- **Conformance**: values follow the CDM's rules (types, keys, valid concepts).
- **Completeness**: the expected values are there.
- **Plausibility**: values make sense, including over time (no visit ends before it starts).

A check fails when its share of violating rows passes its threshold. It is not applicable when there is nothing to check, such as a unit check for a lab that never appears. Scoring follows DQD's rules (`scoring.py` ports its R code).

## Run it

```bash
uv run python scripts/run_dq.py
```

About 2 minutes on the 23,421-person build. Each run is stored in the `dq` schema with every check's counts and SQL, and the dashboard at http://127.0.0.1:8000/dq/ shows the latest. The API serves runs as JSON at `/api/dq/runs`.

## Results

On the 23,421-person build, 99.41% of checks pass (DQD's `percentPassed`, which counts not-applicable checks as passing), with no errors. Fourteen checks fail, all from [Synthea](https://github.com/synthetichealth/synthea) data. Eleven come from how it maps to OMOP: procedure and device codes with no standard concept, observation rows with no unit, start and end dates earlier than DQD's plausible lower bound, and 28 of 209,849 drug strength rows whose ingredient is not classed as one. Three are conditions Synthea gave the wrong sex: prostate cancer in 12 women, ovarian cancer in 4 men, and uterine fibroids in 1 man.

The [DQD comparison](../dqd_comparison.md) ran on an earlier 1,172-person build, where 99.62% passed; the five extra failures here appear only in the larger population.

## Checked against DataQualityDashboard

DQD itself, in R, ran on the same databases. [dqd_comparison.md](../dqd_comparison.md) has the details:

- Every one of the 2,384 checks matches DQD on every field compared, on the real build and on a planted database built to reach the paths real data never does (a missing table, a duplicate key, a female-only condition on a male, a lab in an implausible unit).
- DQD's Overview summary matches line for line.
- The comparison found one limitation in DQD: a missing column stops its whole run. This version keeps going and scores that field's checks as not applicable.
