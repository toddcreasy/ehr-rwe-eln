# Run OHDSI DataQualityDashboard, the correctness reference for module 7, on the local CDM.
#
# Tested with DataQualityDashboard v2.9.0, installed with
#   remotes::install_github("OHDSI/DataQualityDashboard@v2.9.0")
# into data/r-lib. Runs all three check levels: TABLE, FIELD, and CONCEPT.
#
# Usage (from the repo root, with the Compose database running):
#   R_LIBS_USER=$PWD/data/r-lib Rscript scripts/dqd_reference.R [database] [schema] [output file]
# Defaults: ehr_rwe_eln, cdm, dqd-results.json.
# rJava needs JAVA_HOME when Java comes from Homebrew, which macOS's java_home does not see:
#   JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | awk -F'= ' '/java.home/{print $2}')
#
# Reads DB_* from .env. Writes nothing to the database: results go to data/dqd/.
# Then compare with scripts/compare_dqd.py.

repo <- getwd()
readRenviron(file.path(repo, ".env"))
args <- commandArgs(trailingOnly = TRUE)
database <- if (length(args) >= 1) args[1] else "ehr_rwe_eln"
schema <- if (length(args) >= 2) args[2] else "cdm"
output_file <- if (length(args) >= 3) args[3] else "dqd-results.json"

driver_dir <- file.path(repo, "data", "jdbc")
dir.create(driver_dir, showWarnings = FALSE, recursive = TRUE)
if (length(list.files(driver_dir, pattern = "postgresql")) == 0) {
  DatabaseConnector::downloadJdbcDrivers("postgresql", pathToDriver = driver_dir)
}

env <- function(name, default) {
  value <- Sys.getenv(name)
  if (value == "") default else value
}

cd <- DatabaseConnector::createConnectionDetails(
  dbms = "postgresql",
  server = paste0(env("DB_HOST", "localhost"), "/", database),
  user = env("DB_USER", "postgres"),
  password = Sys.getenv("DB_PASSWORD"),
  port = as.integer(env("DB_PORT", "5432")),
  pathToDriver = driver_dir
)

output_dir <- file.path(repo, "data", "dqd")
dir.create(output_dir, showWarnings = FALSE, recursive = TRUE)

started <- Sys.time()
DataQualityDashboard::executeDqChecks(
  connectionDetails = cd,
  cdmDatabaseSchema = schema,
  # Only used for writing results, which this run does not do.
  resultsDatabaseSchema = "dq",
  # The cohort table lives in the CDM schema here.
  cohortDatabaseSchema = schema,
  cdmSourceName = "ehr-rwe-eln Synthea",
  cdmVersion = "5.4",
  checkLevels = c("TABLE", "FIELD", "CONCEPT"),
  outputFolder = output_dir,
  outputFile = output_file,
  writeToTable = FALSE
)
message(sprintf("DQD finished in %.0f s", as.numeric(Sys.time() - started, units = "secs")))
