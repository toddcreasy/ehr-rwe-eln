# OHDSI HADES (R)

OHDSI's R tools, run against the OMOP lake. Everything here runs in the `hades` container (`docker/hades.Dockerfile`); nothing R is installed on the host.

| Package | Job |
|---|---|
| DatabaseConnector | JDBC connections; Redshift through the Amazon driver in `/opt/jdbc` |
| SqlRender | OHDSI SQL translated to each database's dialect (`@cdm.person` becomes `awsdatacatalog.omop_cdm.person` on Redshift) |
| DataQualityDashboard | The OHDSI data quality checks |
| FeatureExtraction, Cyclops | Covariates and large-scale regularized regression |
| CohortMethod, EmpiricalCalibration | New-user cohort studies and calibration with negative controls |
| TrialEmulation | Per-protocol effects with time-varying weights |
| Eunomia | A small sample CDM for tests |

Exact versions of every installed package: `installed-versions.txt`.

## Run a script

```sh
uv run python scripts/hades.py --local smoke_eunomia.R   # no AWS: Eunomia only
uv run python scripts/hades.py smoke_lake.R              # against the lake
```

Against the lake, `scripts/hades.py`:

1. starts the bastion task (ECS Exec on; it stops itself after an hour),
2. opens a Systems Manager tunnel from `127.0.0.1:15439` to Redshift's port 5439 (the workgroup has no public address, and HADES needs a JDBC connection, not the HTTPS Data API),
3. gets a temporary Redshift password for your AWS identity (`redshift-serverless get-credentials`, one hour, user `IAMR:<role>`), so HADES has exactly your lake grants and no Redshift password is stored,
4. runs `docker compose run --rm hades <script>` with `REDSHIFT_*` and `CDM_SCHEMA` set,
5. closes the tunnel (its whole process group) and stops the bastion, whatever the script did.

Scripts source `connection.R` for `lake_connection_details()` and `cdm_schema()`. The container sees this folder as `/work/r` and `data/hades/` as `/work/data/hades`.

## Scripts

| Script | Job |
|---|---|
| `run_dqd.R` | OHDSI DataQualityDashboard on the lake; JSON to `data/hades/dqd/`, loaded with `scripts/load_dqd.py`. About 32 minutes, 4.5 RPU-hours (`docs/modules/data_quality.md`) |

## Smoke tests

| Script | What it proves | Result 2026-11-20 |
|---|---|---|
| `smoke_eunomia.R` | R, Java, and the packages: celecoxib against diclofenac, GI bleed, on Eunomia, with default covariates, a large-scale propensity score, 5 strata, and a stratified Cox model | 2,627 persons, HR 0.93 (0.66 to 1.34), 8 s |
| `smoke_lake.R` | The tunnel, the temporary IAM login, Lake Formation's grants, and SqlRender keeping the three-part name | 23,421 persons, 59 s including the bastion |

Two lessons from them:

- Exclude the exposure drugs (and descendants) from the covariates: `createDefaultCovariateSettings(excludedCovariateConceptIds = ..., addDescendantsToExclude = TRUE)`. Left in, they predict the arm perfectly and `createPs` stops with "High correlation".
- DatabaseConnector 8 keeps the column names Redshift returns (lowercase); `querySql(...)$PERSONS` is `NULL`. Read by the lowercase name or by position.

## Why no renv lockfile

methyl-flow pins its R packages with renv, which works because CRAN and Bioconductor keep old versions. HADES comes from OHDSI's r-universe, which serves only the latest build, so a lockfile could not restore older HADES versions without GitHub API calls (and a token). Instead: CRAN is pinned by the dated Posit Package Manager snapshot in the rocker base image, `installed-versions.txt` records what each build installed, and the built image is the reproducible artifact. To update, rebuild (`docker compose --profile hades build hades`), rerun both smoke tests, and commit the new `installed-versions.txt`.
