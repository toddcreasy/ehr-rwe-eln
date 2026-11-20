# Installs the OHDSI HADES packages this project uses into the image's site library.
#
# CRAN packages come from the dated Posit Package Manager snapshot the rocker image sets, so their
# versions are fixed by that date. HADES packages that are not on CRAN come from OHDSI's
# r-universe, which serves only the latest build: the versions installed are recorded in
# r/installed-versions.txt by docker/hades.Dockerfile, and the image is the reproducible artifact.

cran <- getOption("repos")[["CRAN"]]
options(repos = c(OHDSI = "https://ohdsi.r-universe.dev", CRAN = cran))

packages <- c(
  "DatabaseConnector", # JDBC connections, Redshift among them
  "SqlRender", # OHDSI SQL translated to each database's dialect
  "DataQualityDashboard", # the data quality checks (6b)
  "FeatureExtraction", # covariates for CohortMethod
  "Cyclops", # regularized regression behind large-scale propensity scores
  "CohortMethod", # new-user cohort studies (6c)
  "EmpiricalCalibration", # calibration with negative controls (6c)
  "TrialEmulation", # per-protocol effects with time-varying weights (6c)
  "Eunomia" # a small sample CDM for smoke tests
)

install.packages(packages, Ncpus = parallel::detectCores())
missing <- setdiff(packages, rownames(installed.packages()))
if (length(missing) > 0) stop("not installed: ", paste(missing, collapse = ", "))

DatabaseConnector::downloadJdbcDrivers("redshift")
