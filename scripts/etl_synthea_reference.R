# Run OHDSI ETL-Synthea, the correctness reference for our ETL, on the same Synthea output.
#
# Tested with ETL-Synthea commit 9ee6eb1 (ETLSyntheaBuilder 2.1), installed with
#   remotes::install_github("OHDSI/ETL-Synthea@9ee6eb1b933c70af7b80711332aa92327af1f7c5")
# into data/r-lib. Needs schemas cdm_synthea and native to exist.
#
# Usage (from the repo root, with the throwaway Postgres container running on 127.0.0.1:5433):
#   R_LIBS_USER=$PWD/data/r-lib Rscript scripts/etl_synthea_reference.R
# rJava needs JAVA_HOME when Java comes from Homebrew, which macOS's java_home does not see:
#   JAVA_HOME=$(java -XshowSettings:properties -version 2>&1 | awk -F'= ' '/java.home/{print $2}')
#
# Reads the container password from data/etl-synthea/pgpass. Writes the CDM to schema
# cdm_synthea in database "synthea". Then compare with scripts/compare_etl_synthea.py.

library(ETLSyntheaBuilder)

repo <- getwd()
driver_dir <- file.path(repo, "data", "jdbc")
dir.create(driver_dir, showWarnings = FALSE, recursive = TRUE)
if (length(list.files(driver_dir, pattern = "postgresql")) == 0) {
  DatabaseConnector::downloadJdbcDrivers("postgresql", pathToDriver = driver_dir)
}

cd <- DatabaseConnector::createConnectionDetails(
  dbms = "postgresql",
  server = "localhost/synthea",
  user = "postgres",
  password = trimws(readLines(file.path(repo, "data", "etl-synthea", "pgpass"))),
  port = 5433,
  pathToDriver = driver_dir
)

cdm_schema <- "cdm_synthea"
cdm_version <- "5.4"
# Must match scripts/generate_synthea.py.
synthea_version <- "3.3.0"
synthea_schema <- "native"
synthea_csv <- file.path(repo, "data", "synthea", "output", "csv")
# Main Athena download only: ETL-Synthea hardcodes gender, race, and ethnicity concept ids.
vocab_csv <- file.path(repo, "data", "vocab")

step <- function(name, expr) {
  started <- Sys.time()
  force(expr)
  message(sprintf("%-28s %6.0fs", name, as.numeric(Sys.time() - started, units = "secs")))
}

step("CreateCDMTables", CreateCDMTables(cd, cdm_schema, cdm_version))
step("CreateSyntheaTables", CreateSyntheaTables(cd, synthea_schema, synthea_version))
step("LoadSyntheaTables", LoadSyntheaTables(cd, synthea_schema, synthea_csv))
step("LoadVocabFromCsv", LoadVocabFromCsv(cd, cdm_schema, vocab_csv, delimiter = "\t"))
step(
  "CreateMapAndRollupTables",
  CreateMapAndRollupTables(cd, cdm_schema, synthea_schema, cdm_version, synthea_version)
)
step("CreateExtraIndices", CreateExtraIndices(cd, cdm_schema, synthea_schema, synthea_version))
step(
  "LoadEventTables",
  LoadEventTables(cd, cdm_schema, synthea_schema, cdm_version, synthea_version)
)
