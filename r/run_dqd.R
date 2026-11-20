# OHDSI DataQualityDashboard on the OMOP lake.
# Run with: uv run python scripts/hades.py run_dqd.R [TABLE|FIELD|CONCEPT ...]
# then:     uv run python scripts/load_dqd.py data/hades/dqd/<file>.json
#
# Runs DQD's checks (conformance, completeness, plausibility) against awsdatacatalog.omop_cdm and
# writes DQD's own JSON to data/hades/dqd/. Nothing is written to Redshift: the lake is read-only
# here, and the results go to the dq schema in Aurora through scripts/load_dqd.py, which the /dq/
# page reads. Check levels given as arguments limit the run (to time a sample); none means all.

source("connection.R")

levels <- commandArgs(trailingOnly = TRUE)
if (length(levels) == 0) levels <- c("TABLE", "FIELD", "CONCEPT")

con <- DatabaseConnector::connect(lake_connection_details())
source_name <- DatabaseConnector::querySql(
  con,
  SqlRender::translate(
    SqlRender::render("SELECT cdm_source_name FROM @cdm.cdm_source;", cdm = cdm_schema()),
    targetDialect = "redshift"
  )
)[[1]]
DatabaseConnector::disconnect(con)

output_folder <- "/work/data/hades/dqd"
output_file <- sprintf("dqd_%s_%s.json", paste(tolower(levels), collapse = "-"),
                       format(Sys.time(), "%Y%m%dT%H%M%S"))
started <- Sys.time()

# DQD 2.9.1 with numThreads > 1 and writeToTable = FALSE ends by disconnecting a main-thread
# connection it never opened ("is.jnull ... object of class NULL"), after the JSON is written.
# Tolerate exactly that, and only when the output file exists.
output_path <- file.path(output_folder, output_file)
tryCatch(DataQualityDashboard::executeDqChecks(
  connectionDetails = lake_connection_details(),
  cdmDatabaseSchema = cdm_schema(),
  resultsDatabaseSchema = cdm_schema(), # unused: writeToTable is FALSE
  cdmSourceName = source_name,
  cdmVersion = "5.4", # the default is 5.3; check definitions differ by version
  # DQD opens a connection per check (about 3 s each through the tunnel); 8 threads keeps a full
  # run well inside the hour the temporary password and the bastion last.
  numThreads = 8,
  outputFolder = output_folder,
  outputFile = output_file,
  writeToTable = FALSE,
  checkLevels = levels
), error = function(e) {
  if (!(file.exists(output_path) && grepl("NULL", conditionMessage(e)))) stop(e)
  message("ignored DQD cleanup error after the results were written: ", conditionMessage(e))
})

cat(sprintf("DQD %s finished in %.1f minutes: %s/%s\n", paste(levels, collapse = ","),
            as.numeric(difftime(Sys.time(), started, units = "mins")), output_folder, output_file))
