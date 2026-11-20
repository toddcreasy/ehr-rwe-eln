# Smoke test 1: HADES on OHDSI's built-in sample CDM (Eunomia), with no network.
# Run with: uv run python scripts/hades.py --local smoke_eunomia.R
#
# Proves R, Java, and the packages by running a miniature of the 6c analysis: celecoxib against
# diclofenac, outcome GI bleed (Eunomia's own example cohorts), with FeatureExtraction's default
# covariates (thousands per person), a large-scale propensity score (L1-regularized regression in
# Cyclops picks the covariates), 5 propensity strata, and a stratified Cox model.

suppressMessages(library(CohortMethod))

connection_details <- Eunomia::getEunomiaConnectionDetails()
cohorts <- Eunomia::createCohorts(connection_details)
print(cohorts)

data <- getDbCohortMethodData(
  connectionDetails = connection_details,
  cdmDatabaseSchema = "main",
  targetId = 1, # celecoxib
  comparatorId = 2, # diclofenac
  outcomeIds = 3, # GI bleed
  exposureDatabaseSchema = "main",
  exposureTable = "cohort",
  outcomeDatabaseSchema = "main",
  outcomeTable = "cohort",
  getDbCohortMethodDataArgs = createGetDbCohortMethodDataArgs(
    # The two drugs define the arms, so they can't also be covariates: they would predict the arm
    # perfectly. createPs stops with "High correlation" if they are left in.
    covariateSettings = FeatureExtraction::createDefaultCovariateSettings(
      excludedCovariateConceptIds = c(1118084, 1124300), # celecoxib, diclofenac
      addDescendantsToExclude = TRUE
    )
  )
)
population <- createStudyPopulation(
  data,
  outcomeId = 3,
  createStudyPopulationArgs = createCreateStudyPopulationArgs(riskWindowEnd = 30)
)
ps <- createPs(data, population)
strata <- stratifyByPs(ps, createStratifyByPsArgs(numberOfStrata = 5))
model <- fitOutcomeModel(strata, fitOutcomeModelArgs = createFitOutcomeModelArgs(stratified = TRUE))

cat("persons:", nrow(population), " covariates available:",
    nrow(dplyr::collect(data$covariateRef)), "\n")
print(model)
if (is.null(model$outcomeModelTreatmentEstimate)) stop("no estimate")
cat("smoke test 1 passed\n")
