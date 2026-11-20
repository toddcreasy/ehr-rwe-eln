# Connection to the lake on Redshift, from the REDSHIFT_* variables scripts/hades.py sets: the
# tunnel's local end, and a temporary password for the caller's IAM identity. SSL is on; the
# certificate's hostname can't match host.docker.internal through the tunnel, so it isn't checked.

lake_connection_details <- function() {
  DatabaseConnector::createConnectionDetails(
    dbms = "redshift",
    server = Sys.getenv("REDSHIFT_SERVER"),
    port = as.integer(Sys.getenv("REDSHIFT_PORT")),
    user = Sys.getenv("REDSHIFT_USER"),
    password = Sys.getenv("REDSHIFT_PASSWORD"),
    extraSettings = "ssl=true&sslfactory=com.amazon.redshift.ssl.NonValidatingFactory"
  )
}

# The OMOP tables: awsdatacatalog.omop_cdm, the Glue resource link to the S3 Tables lake.
cdm_schema <- function() Sys.getenv("CDM_SCHEMA", "awsdatacatalog.omop_cdm")
