# Smoke test 2: HADES reads the lake. Run with: uv run python scripts/hades.py smoke_lake.R
# Proves the tunnel, the temporary IAM login, Lake Formation's grants, and that SqlRender's
# Redshift translation keeps the three-part table name (awsdatacatalog.omop_cdm.person).

source("connection.R")

con <- DatabaseConnector::connect(lake_connection_details())
on.exit(DatabaseConnector::disconnect(con))

sql <- SqlRender::render("SELECT COUNT(*) AS persons FROM @cdm.person;", cdm = cdm_schema())
sql <- SqlRender::translate(sql, targetDialect = "redshift")
cat("SQL sent:", sql, "\n")
# DatabaseConnector 8 keeps the column names Redshift returns (lowercase), so read by position.
persons <- DatabaseConnector::querySql(con, sql)[[1]]
cat("persons in the lake:", persons, "\n")
if (persons != 23421) stop("expected 23,421 persons")
cat("smoke test 2 passed\n")
