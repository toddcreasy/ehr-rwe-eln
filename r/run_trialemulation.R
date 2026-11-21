# Per-protocol estimate with TrialEmulation, from the person-period table that
# scripts/write_person_periods.py writes (tte/per_protocol.py). No database.
# Run with: OMOP_SOURCE=staging uv run python scripts/write_person_periods.py
#           uv run python scripts/hades.py --local run_trialemulation.R [PROTOCOL ...]
#
# One emulated trial per protocol, starting at each person's own time zero (eligible only in
# period 0). Three analyses through the same pipeline:
# - itt: everyone in the arm they started; a check against the Cox intention-to-treat estimate
# - pp_strict: follow-up ends at stopping the drug or starting the other arm's drug
# - pp_lenient: follow-up ends at stopping the drug only
# For the per-protocol ones, TrialEmulation censors each person at their first deviation and
# weights the people who stay by the inverse probability of staying (switch weights): logistic
# models of deviating, by period, on baseline covariates (numerator) and baseline plus each
# period's latest measurements (denominator), so the weights correct for who deviates, for
# instance people whose blood pressure stays high. Weights truncated at the 99th percentile.
# The outcome model is a pooled logistic regression on follow-up time (quadratic) and the baseline
# covariates; with rare events its odds ratio approximates a hazard ratio. Robust (sandwich) 95%
# intervals.
#
# Writes data/hades/trialemulation/<protocol>/summary.json.

suppressMessages(library(TrialEmulation))

root <- "/work/data/hades/trialemulation"
wanted <- commandArgs(trailingOnly = TRUE)
protocols <- if (length(wanted) > 0) wanted else list.dirs(root, full.names = FALSE, recursive = FALSE)

terms <- function(names) as.formula(paste("~", paste(names, collapse = " + ")))

# A person's rows up to and including the period they first leave their strategy: the switch
# models are about who deviates, so they are fitted only where deviating is still possible.
# (Keeping later rows, where nobody deviates again, gave weights up to 59,520 on 2026-11-21.)
until_deviation <- function(data, treatment) {
  data <- data[order(data$id, data$period), ]
  assigned <- ave(data[[treatment]], data$id, FUN = function(x) x[1])
  off <- as.integer(data[[treatment]] != assigned)
  data[ave(off, data$id, FUN = function(x) cumsum(cumsum(x))) <= 1, ]
}

estimate <- function(estimand, data, columns, treatment, work) {
  baseline <- terms(columns$baseline_covariates)
  # Deviation is mostly a first-month event (Synthea adds the second drug about day 30), so the
  # switch models get follow-up time: period 1 on its own, and a quadratic after.
  # A copy of period: TrialEmulation renames period when it expands the data, but still looks up
  # every column the formulas name.
  time <- c("I(months == 1)", "months", "I(months^2)")
  data$months <- data$period
  if (estimand == "PP") data <- until_deviation(data, treatment)
  trial <- trial_sequence(estimand) |>
    set_data(data = data, id = "id", period = "period", treatment = treatment,
             outcome = "outcome", eligible = "eligible")
  if (estimand == "PP") {
    trial <- trial |>
      set_switch_weight_model(
        numerator = terms(c(columns$baseline_covariates, time)),
        denominator = terms(c(columns$baseline_covariates, columns$time_varying_covariates, time)),
        model_fitter = stats_glm_logit(save_path = file.path(work, "switch_models"))
      ) |>
      calculate_weights()
  }
  trial <- trial |>
    set_outcome_model(adjustment_terms = baseline, trial_period_terms = ~1) |>
    set_expansion_options(output = save_to_datatable(), chunk_size = 500,
                          first_period = 0, last_period = 0) |>
    expand_trials() |>
    load_expanded_data(seed = 1)
  weights <- trial@outcome_data@data$weight
  truncate <- function(w) pmin(w, quantile(w, 0.99))
  trial <- fit_msm(trial, weight_cols = "weight", modify_weights = truncate)
  tidy <- trial@outcome_model@fitted@summary$tidy
  row <- tidy[tidy$term == "assigned_treatment", ]
  expanded <- trial@outcome_data@data
  list(
    odds_ratio = exp(row$estimate),
    lb = exp(row$conf.low), ub = exp(row$conf.high),
    persons = length(unique(expanded$id)),
    person_periods = nrow(expanded),
    events = c(treatment = sum(expanded$outcome[expanded$assigned_treatment == 1]),
               comparator = sum(expanded$outcome[expanded$assigned_treatment == 0])),
    weight = c(min = min(weights), median = median(weights), mean = mean(weights),
               p99 = unname(quantile(weights, 0.99)), max = max(weights))
  )
}

for (protocol in protocols) {
  dir <- file.path(root, protocol)
  columns <- jsonlite::fromJSON(file.path(dir, "columns.json"))
  data <- data.table::fread(file.path(dir, "person_periods.csv"))
  work <- file.path(dir, "work")
  unlink(work, recursive = TRUE)
  dir.create(work)

  results <- list(
    itt = estimate("ITT", data, columns, "treatment_strict", work),
    pp_strict = estimate("PP", data, columns, "treatment_strict", work),
    pp_lenient = estimate("PP", data, columns, "treatment_lenient", work)
  )
  jsonlite::write_json(c(list(protocol = protocol, arms = columns$arms), results),
                       file.path(dir, "summary.json"), auto_unbox = TRUE, digits = NA,
                       pretty = TRUE)
  for (name in names(results)) {
    r <- results[[name]]
    cat(sprintf("%s %-10s OR %.2f (%.2f to %.2f); events %d / %d; weights %.2f to %.2f, mean %.2f\n",
                protocol, name, r$odds_ratio, r$lb, r$ub, r$events[["treatment"]],
                r$events[["comparator"]], r$weight[["min"]], r$weight[["max"]],
                r$weight[["mean"]]))
  }
}
