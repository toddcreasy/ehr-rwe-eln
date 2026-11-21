# OHDSI CohortMethod on the trial emulation protocols, on the OMOP lake.
# Run with: uv run python scripts/write_cohorts.py
#           uv run python scripts/hades.py run_cohortmethod.R [PROTOCOL ...]
#           uv run python scripts/hades.py --local run_cohortmethod.R --summarize [PROTOCOL ...]
# --summarize redoes only the summary from a finished run's files, with no database.
#
# Reads the cohorts scripts/write_cohorts.py put in results.cohort (each protocol's arms, its
# outcome, and its negative controls; IDs in data/hades/cohortmethod/cohorts.json). For each
# protocol: thousands of baseline covariates from FeatureExtraction (every condition, drug,
# procedure, and measurement in the year before time zero, plus demographics), a large-scale
# propensity score (L1-regularized logistic regression in Cyclops, which keeps only covariates
# that predict the arm), inverse probability of treatment weights as in the Python analysis, a
# weighted Cox model per outcome, and empirical calibration of the outcome's estimate against the
# negative controls (their true hazard ratio is 1). Only the data download touches Redshift; the
# models run in this container.
#
# Writes, per protocol, to data/hades/cohortmethod/<protocol>/: results.csv (one row per outcome,
# raw and calibrated), diagnostics.csv (OHDSI's study diagnostics: balance, equipoise), balance.csv
# (the 25 covariates with the largest standardized difference after weighting), summary.json, and
# CohortMethod's own files in cm/. Calibration is done here with EmpiricalCalibration, as
# CohortMethod 6.0.3's results summary left it empty: a systematic error model fitted to the
# negative controls (true hazard ratio 1), the outcome's interval recalibrated with it, and EASE
# (expected absolute systematic error; OHDSI's diagnostic passes below 0.25).

source("connection.R")
suppressMessages(library(CohortMethod))

root <- "/work/data/hades/cohortmethod"
args <- commandArgs(trailingOnly = TRUE)
summarize_only <- "--summarize" %in% args
wanted <- setdiff(args, "--summarize")
protocols <- jsonlite::fromJSON(file.path(root, "cohorts.json"), simplifyVector = FALSE)
if (length(wanted) > 0) protocols <- Filter(function(p) p$protocol %in% wanted, protocols)

summarize <- function(p, out) {
  cm <- file.path(out, "cm")
  names <- c(
    setNames(p$outcome$name, p$outcome$id),
    setNames(vapply(p$negative_controls, `[[`, "", "name"),
             vapply(p$negative_controls, function(nc) as.character(nc$id), ""))
  )
  results <- getResultsSummary(cm)
  results$outcomeName <- names[as.character(results$outcomeId)]
  nc <- results[results$outcomeId != p$outcome$id & !is.na(results$seLogRr), ]
  model <- EmpiricalCalibration::fitSystematicErrorModel(nc$logRr, nc$seLogRr, rep(0, nrow(nc)))
  calibrated <- EmpiricalCalibration::calibrateConfidenceInterval(
    results$logRr, results$seLogRr, model
  )
  results$calibratedRr <- exp(calibrated$logRr)
  results$calibratedCi95Lb <- exp(calibrated$logLb95Rr)
  results$calibratedCi95Ub <- exp(calibrated$logUb95Rr)
  results$calibratedSeLogRr <- calibrated$seLogRr
  set.seed(1) # fitMcmcNull samples; a fixed seed makes EASE repeatable
  ease <- EmpiricalCalibration::computeExpectedAbsoluteSystematicError(
    EmpiricalCalibration::fitMcmcNull(nc$logRr, nc$seLogRr)
  )$ease
  write.csv(results, file.path(out, "results.csv"), row.names = FALSE)
  diagnostics <- getDiagnosticsSummary(cm)
  write.csv(diagnostics, file.path(out, "diagnostics.csv"), row.names = FALSE)
  main_diagnostics <- diagnostics[diagnostics$outcomeId == p$outcome$id, ]

  balance <- readRDS(file.path(cm, unique(getFileReference(cm)$sharedBalanceFile)[1]))
  balance <- balance[order(-abs(balance$afterMatchingStdDiff)), ]
  write.csv(head(balance[, c("covariateId", "covariateName", "beforeMatchingMeanTarget",
                             "beforeMatchingMeanComparator", "beforeMatchingStdDiff",
                             "afterMatchingMeanTarget", "afterMatchingMeanComparator",
                             "afterMatchingStdDiff")], 25),
            file.path(out, "balance.csv"), row.names = FALSE)

  main <- results[results$outcomeId == p$outcome$id, ]
  summary <- list(
    protocol = p$protocol,
    covariates = nrow(balance),
    covariates_over_0_1_before = sum(abs(balance$beforeMatchingStdDiff) > 0.1, na.rm = TRUE),
    covariates_over_0_1_after = sum(abs(balance$afterMatchingStdDiff) > 0.1, na.rm = TRUE),
    max_abs_smd_after = max(abs(balance$afterMatchingStdDiff), na.rm = TRUE),
    # Two verdicts on balance: OHDSI's test (is any SDM significantly over 0.1, Bonferroni
    # adjusted; sdmAlpha below) and the plain rule (is any SDM over 0.1 at all). With ~1,900
    # people, chance alone puts the largest of ~2,800 SDMs near 0.17, so the plain rule fails
    # even when nothing is out of balance.
    balance_test = main_diagnostics$sharedBalanceDiagnostic,
    balance_test_family_wise_min_p = main_diagnostics$sharedSdmFamilyWiseMinP,
    balance_rule_0_1 = if (max(abs(balance$afterMatchingStdDiff), na.rm = TRUE) <= 0.1) "PASS" else "FAIL",
    negative_controls_estimated = nrow(nc),
    negative_controls_excluding_1 = sum(nc$ci95Lb > 1 | nc$ci95Ub < 1),
    systematic_error_mean = unname(model["meanIntercept"]),
    systematic_error_sd = unname(model["sdIntercept"]),
    ease = ease,
    hr = main$rr, hr_lb = main$ci95Lb, hr_ub = main$ci95Ub,
    calibrated_hr = main$calibratedRr, calibrated_lb = main$calibratedCi95Lb,
    calibrated_ub = main$calibratedCi95Ub,
    target_subjects = main$targetSubjects, comparator_subjects = main$comparatorSubjects,
    target_outcomes = main$targetOutcomes, comparator_outcomes = main$comparatorOutcomes
  )
  jsonlite::write_json(summary, file.path(out, "summary.json"), auto_unbox = TRUE, digits = NA,
                       pretty = TRUE)
  cat(sprintf(
    "%s: HR %.2f (%.2f to %.2f); calibrated %.2f (%.2f to %.2f); EASE %.2f; balance test %s; %d of %d covariates over 0.1 after weighting\n",
    p$protocol, main$rr, main$ci95Lb, main$ci95Ub, main$calibratedRr, main$calibratedCi95Lb,
    main$calibratedCi95Ub, ease, summary$balance_test, summary$covariates_over_0_1_after,
    summary$covariates
  ))
}

# Covariates end the day before time zero. With the default (ending on time zero), a basic metabolic
# panel drawn on the day lisinopril started (monitoring for the ACE inhibitor, so part of the
# treatment decision) became a covariate; the L1 model dropped it and balance failed at 0.16
# (2026-11-21). createDefaultCovariateSettings has no endDays argument, so it's set on the result.
covariate_settings <- FeatureExtraction::createDefaultCovariateSettings(addDescendantsToExclude = TRUE)
covariate_settings$endDays <- -1

analysis <- createCmAnalysis(
  analysisId = 1,
  description = "IPTW, large-scale propensity score, Cox",
  getDbCohortMethodDataArgs = createGetDbCohortMethodDataArgs(covariateSettings = covariate_settings),
  # Same follow-up as the Python analysis: from the day after time zero to the cohort end the
  # protocol wrote (death, end of observation, or its maximum), only people without the outcome
  # on or before time zero.
  createStudyPopulationArgs = createCreateStudyPopulationArgs(
    removeSubjectsWithPriorOutcome = TRUE,
    priorOutcomeLookback = 99999,
    minDaysAtRisk = 1,
    riskWindowStart = 1,
    startAnchor = "cohort start",
    riskWindowEnd = 0,
    endAnchor = "cohort end"
  ),
  createPsArgs = createCreatePsArgs(
    estimator = "ate",
    control = Cyclops::createControl(seed = 1, noiseLevel = "quiet", cvRepetitions = 1)
  ),
  truncateIptwArgs = createTruncateIptwArgs(maxWeight = 10),
  computeSharedCovariateBalanceArgs = createComputeCovariateBalanceArgs(),
  fitOutcomeModelArgs = createFitOutcomeModelArgs(modelType = "cox", inversePtWeighting = TRUE)
)

for (p in protocols) {
  started <- Sys.time()
  out <- file.path(root, p$protocol)
  dir.create(out, recursive = TRUE, showWarnings = FALSE)
  if (summarize_only) {
    summarize(p, out)
    next
  }

  outcomes <- c(
    list(createOutcome(outcomeId = p$outcome$id, outcomeOfInterest = TRUE)),
    lapply(p$negative_controls, function(nc) {
      createOutcome(outcomeId = nc$id, outcomeOfInterest = FALSE, trueEffectSize = 1)
    })
  )
  specifications <- createCmAnalysesSpecifications(
    cmAnalysisList = list(analysis),
    targetComparatorOutcomesList = list(createTargetComparatorOutcomes(
      targetId = p$treatment$id,
      comparatorId = p$comparator$id,
      outcomes = outcomes,
      excludedCovariateConceptIds = unlist(p$excluded_covariate_concept_ids)
    )),
    # Balance fails only if an SDM is significantly over 0.1 (alpha 0.05, Bonferroni adjusted).
    cmDiagnosticThresholds = createCmDiagnosticThresholds(sdmAlpha = 0.05)
  )
  runCmAnalyses(
    connectionDetails = lake_connection_details(),
    cdmDatabaseSchema = cdm_schema(),
    exposureDatabaseSchema = "results",
    exposureTable = "cohort",
    outcomeDatabaseSchema = "results",
    outcomeTable = "cohort",
    outputFolder = file.path(out, "cm"),
    multiThreadingSettings = createDefaultMultiThreadingSettings(parallel::detectCores()),
    cmAnalysesSpecifications = specifications
  )

  summarize(p, out)
  cat(sprintf("%s: %.1f minutes\n", p$protocol,
              as.numeric(difftime(Sys.time(), started, units = "mins"))))
}
