# RWE data quality dashboard

Package: `ehr_rwe_eln.dq`. Back to the [README](../../README.md). Terms are defined in the [glossary](../GLOSSARY.md).

Profiles the [OMOP](https://ohdsi.github.io/CommonDataModel/cdm54.html) database before anyone trusts an analysis from it. It runs [OHDSI](https://www.ohdsi.org)'s own [DataQualityDashboard](https://github.com/OHDSI/DataQualityDashboard) (DQD) 2.9.1, in R, against the OMOP lake, and loads the results into the `dq` schema for the dashboard at `/dq/`.

## What it checks

2,384 checks at three levels, from the check and threshold files bundled with DQD 2.9.1. The repo keeps one of DQD's files, `OMOP_CDMv5.4_Check_Descriptions.csv` (`src/ehr_rwe_eln/dq/csv/`), which `dqd.py` reads for each check's severity:

| Level | Asks | Example |
|---|---|---|
| Table | Does each table exist, and does it have records? | `measurement` is not empty |
| Field | Are values present, of the right type, in range, and pointing at real rows? | `person.year_of_birth` is not before 1850 |
| Concept | Do specific concepts behave plausibly? | A female-only condition is never recorded on a male |

Each check falls into one category of the [Kahn framework](https://doi.org/10.13063/2327-9214.1244), the standard way to group data quality checks:

- **Conformance**: values follow the CDM's rules (types, keys, valid concepts).
- **Completeness**: the expected values are there.
- **Plausibility**: values make sense, including over time (no visit ends before it starts).

A check fails when its share of violating rows passes its threshold. It is not applicable when there is nothing to check, such as a unit check for a lab that never appears. DQD scores its own runs.

## Run it

Since 2026-11-20 the checks are OHDSI's own [DataQualityDashboard](https://ohdsi.github.io/DataQualityDashboard/) 2.9.1, in R, run against the OMOP lake on Redshift:

```bash
uv run python scripts/hades.py run_dqd.R                                  # about 32 minutes
uv run python scripts/load_dqd.py data/hades/dqd/<file>.json --target aurora   # the public app
uv run python scripts/load_dqd.py data/hades/dqd/<file>.json --target local    # the Compose app
```

`r/run_dqd.R` writes DQD's JSON to `data/hades/dqd/`; nothing is written to Redshift. `scripts/load_dqd.py` (`src/ehr_rwe_eln/dq/dqd.py`) stores it in the `dq` schema, filling in each check's severity from DQD's check descriptions and the strict pass rate the page shows. Into Aurora it goes through the RDS Data API, waiting while a paused cluster wakes. The dashboard shows the newest run; the API serves runs as JSON at `/api/dq/runs`.

A full run is 2,384 checks in 32 minutes on 8 threads and about 4.5 Redshift RPU-hours. DQD opens a connection per check, and the tunnel's temporary password and the bastion last an hour, which is why it runs on 8 threads. DQD 2.9.1 ends with an error when it runs on several threads without writing to a table; the results are already written by then, and `run_dqd.R` tolerates exactly that error when the file exists.

Until 2026-11-20 the checks were a Python port of DQD, run on the staging Postgres. It was removed once DQD ran on the lake and matched it:

### DQD on the lake against the Python port

On 2026-11-20 both ran the same 2,384 checks and failed the same 14, check for check, with the same DQD pass rate (99.41%). DQD marked 60 fewer checks not applicable (1,076 against 1,136): all on `SPECIMEN` and `FACT_RELATIONSHIP`, which were empty when the Python run was made and now hold the ELN bridge's 752 specimens and 2,314 links. All 60 pass, so the strict pass rate is 98.93% (Python run, 98.88%).

## Results

On the 23,421-person build, 99.41% of checks pass (DQD's `percentPassed`, which counts not-applicable checks as passing), with no errors. Fourteen checks fail, all from [Synthea](https://github.com/synthetichealth/synthea) data. Eleven come from how it maps to OMOP: procedure and device codes with no standard concept, observation rows with no unit, start and end dates earlier than DQD's plausible lower bound, and 28 of 209,849 drug strength rows whose ingredient is not classed as one. Three are conditions Synthea gave the wrong sex: prostate cancer in 12 women, ovarian cancer in 4 men, and uterine fibroids in 1 man.

The [DQD comparison](../dqd_comparison.md) ran on an earlier 1,172-person build, where 99.62% passed; the five extra failures here appear only in the larger population.

## Checked against DataQualityDashboard (the Python port, historical)

Before DQD ran here, the Python port was checked against DQD on the same databases. [dqd_comparison.md](../dqd_comparison.md) has the details:

- Every one of the 2,384 checks matches DQD on every field compared, on the real build and on a planted database built to reach the paths real data never does (a missing table, a duplicate key, a female-only condition on a male, a lab in an implausible unit).
- DQD's Overview summary matches line for line.
- The comparison found one limitation in DQD: a missing column stops its whole run. The port kept going and scored that field's checks as not applicable; DQD on the lake has every column, so it doesn't arise.
