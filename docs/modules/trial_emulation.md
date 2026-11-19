# Target trial emulation toolkit

Package: `ehr_rwe_eln.tte`. Back to the [README](../../README.md). Terms are defined in the [glossary](../GLOSSARY.md).

Target trial emulation asks a causal question of observational data the way a randomized trial would. You write the protocol of the trial you would have run (who is eligible, what each arm does, when follow-up starts, what counts as the outcome), then apply it to records. Fixing time zero and eligibility in advance avoids the biases that sink casual comparisons, such as counting follow-up time before anyone could have started treatment.

This module takes a protocol in YAML, builds its analysis table from [OMOP](https://ohdsi.github.io/CommonDataModel/cdm54.html), estimates the effect with propensity score weighting, and writes a bias report that says whether the estimate can be trusted.

## A protocol

From `protocols/lisinopril_vs_amlodipine_ckd.yaml`, which emulates a trial of starting lisinopril against amlodipine for new hypertension, with progression to chronic kidney disease (CKD) stage 3 or worse as the outcome:

```yaml
eligibility:
  diagnosis: {concept_ids: [320128]}   # essential hypertension
  max_days_from_diagnosis: 365
  min_age: 18
  prior_observation_days: 365
strategies:
  treatment: {name: lisinopril, drugs: {concept_ids: [1308216]}}
  comparator: {name: amlodipine, drugs: {concept_ids: [1332418]}}
outcome:
  name: ckd_stage_3_or_worse
  conditions: {concept_ids: [443597, 443612, 193782]}
follow_up: {max_days: 1825}
causal_contrast: intention_to_treat
```

The full file adds the covariates to adjust for (conditions and the latest measurements before time zero) and four negative control outcomes. There are four protocols: lisinopril against amlodipine and metformin against insulin, each with CKD and with myocardial infarction (MI) as the outcome.

## The analysis

1. **Analysis table** (`cohort.py`, `covariates.py`). Time zero is the first use of either drug. Each eligibility rule is applied in order, and the attrition is kept.
2. **Propensity scores** (`propensity.py`). A logistic regression predicts each person's arm from the covariates. The score becomes a stabilized weight, truncated at the 1st and 99th percentiles, so the weighted arms look alike on every covariate. Covariates too rare to fit are dropped and reported.
3. **Not estimable check.** When the covariates nearly predict the arm, the arms don't overlap enough to compare, and the module says so instead of reporting a number.
4. **Survival** (`survival.py`). Weighted Kaplan-Meier risk at 1, 3, and 5 years, and a weighted Cox model for the hazard ratio, with a robust (sandwich) interval and a 500-replicate bootstrap interval.
5. **Negative controls** (`report.py`). Outcomes neither drug plausibly causes, such as viral sinusitis, run through the same analysis. Their hazard ratios should sit near 1; one far from 1 points to confounding the weights did not remove.

## Run it

```bash
uv run python scripts/run_tte.py
```

It needs the full 23,421-person build; 1,172 people give too few outcome events for an estimate. It takes about a minute, prints each protocol's bias report, and stores the run in the `tte` schema. The page at http://127.0.0.1:8000/tte/ shows it.

## Results

| Protocol | Persons (treatment / comparator) | Events | Hazard ratio, weighted (95% CI) |
|---|---|---|---|
| Lisinopril vs amlodipine, CKD | 1,214 / 676 | 18 / 8 | 0.97 (0.42 to 2.26) |
| Lisinopril vs amlodipine, MI | 1,223 / 676 | 10 / 9 | 0.58 (0.23 to 1.44) |
| Metformin vs insulin, CKD | 219 / 612 | 1 / 102 | Not estimable |
| Metformin vs insulin, MI | 215 / 579 | 11 / 16 | Not estimable |

For lisinopril against amlodipine, weighting brings every covariate's standardized mean difference (SMD) under 0.1, the usual threshold for balanced, and no one has a propensity score outside 0.05 to 0.95. All four negative controls have intervals that include 1. Both estimates are uncertain; with 26 and 19 events, the intervals are wide.

The metformin protocols are not estimable. In [Synthea](https://github.com/synthetichealth/synthea), diabetes treatment follows fixed rules, so the covariates almost decide who gets insulin, and no weighting can make the arms comparable. The module reporting that instead of a number is the bias check doing its job.

These are synthetic patients whose treatments follow Synthea's rules. The numbers test the method, not the drugs, and carry no clinical meaning.
