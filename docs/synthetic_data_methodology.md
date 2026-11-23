# Synthetic data releases: methodology

How this repository makes differentially private synthetic copies of an [OMOP](https://ohdsi.github.io/CommonDataModel/cdm54.html) database, how it checks them, and what the checks found. Written for a reviewer such as a Data Access Committee (DAC): someone who decides whether a dataset may be shared and needs to know what it protects, what it costs in accuracy, and what it should not be used for.

The source here is [Synthea](https://github.com/synthetichealth/synthea) output, not real patients. It stands in for a controlled-access source so the whole process can be run and inspected in the open. The methods carry over to real data; the numbers describe this source only. Code: `src/ehr_rwe_eln/synth/`. Every figure below comes from the reports stored in the `synth.report` table of the 23,421-patient build and from the per-release data cards (`scripts/synth_cards.py`).

## 1. What is released

Two kinds of table, each defined by a YAML spec in `src/ehr_rwe_eln/synth/specs/`.

- **Person summary** (`person_summary.yaml`): one row per person, 21 columns. Age at the end of observation, sex, race, ethnicity; whether each of eight conditions and four drugs was ever recorded; the latest of four measurements (systolic blood pressure, BMI, eGFR, HbA1c); and death. 23,421 people.
- **Trial table** (`trial_lisinopril_amlodipine_ckd.yaml`): the analysis table of the trial emulation module's target trial of lisinopril against amlodipine, with chronic kidney disease stage 3 or worse as the outcome. One row per eligible person: treatment arm, age, sex, six condition and four measurement covariates, follow-up days, and outcome. 1,890 people, 26 outcome events.

Neither table carries a direct identifier. `person_id` is used to build and split the source and never reaches a synthesizer. Dates are not released; ages and follow-up lengths are.

## 2. What it protects against

The unit of privacy is one person: one row of the source. The question differential privacy answers is how much the release could differ if any one person's row were added or removed.

The attacker has the full synthetic release and the spec, and may hold auxiliary data about a real person: their full record, or only their quasi-identifiers (age, sex, race, ethnicity: fields that are not identifying alone but can be in combination). The attacker wants to learn:

- **Membership**: whether a given person was in the source. Being in a disease cohort can itself be sensitive.
- **Attributes**: a person's conditions, drugs, measurements, or death, from what they already know.
- **Identity**: which synthetic row, if any, is a near-copy of a real person.

Synthetic rows are not real people, so a match between a synthetic row and a real one is not by itself a disclosure. The risk is that the synthesizer copied or memorized real rows, or that the release lets someone infer something about a specific person that they could not infer from population-level patterns.

## 3. How privacy is enforced

**Differential privacy (DP).** A mechanism is epsilon-differentially private if, for any two sources that differ by one person, the probability of any output changes by at most a factor of e^epsilon. Smaller epsilon means more noise and stronger protection. Spending privacy more than once adds up: running mechanisms with epsilon 1 and epsilon 2 on the same people costs epsilon 3 (sequential composition). Anything computed only from a DP output costs nothing more (post-processing).

**Fixed domains.** Every category list and every numeric range and bin is written in the spec before the data is read. A range taken from the data would leak on its own: the top bin edge would be the oldest person's age. Values outside a range are clamped into its end bins. Age's last bin is open: it means 90 or older and decodes to 90, never to an age inside it, as HIPAA [Safe Harbor](https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html) requires.

**Declared structure.** For the Bayesian network, each column's parents (the columns its distribution is measured against) are declared in the spec from domain knowledge, so choosing the structure costs no privacy. Example: lisinopril depends on hypertension; diabetes on age and obesity; in the trial table, treatment on diabetes and early kidney disease, following public prescribing guidance.

**Bayesian network synthesizer** (`synth/bayes_net.py`). One histogram per column over the column and its parents. Each count gets noise from the truncated geometric mechanism (integer noise, the discrete form of the Laplace mechanism) through IBM's [diffprivlib](https://github.com/IBM/differential-privacy-library). Adding or removing one person changes one cell of each histogram by 1, so the sensitivity is 1. Every histogram counts every person, so the release's epsilon is split evenly across the histograms (21 for the person summary, 15 for the trial table), and diffprivlib's budget accountant refuses any spend beyond it. Each share is reduced by one part in a trillion so that floating-point rounding can only underspend. New rows are sampled from the noisy counts alone. The row count is the noisy total of the first histogram, not the true count.

**Variational autoencoder (VAE)** (`synth/vae.py`). A neural network that compresses each row to 16 numbers and rebuilds it, trained with DP-SGD through Meta's [Opacus](https://opacus.ai). Each training step clips every person's gradient to length 1 and adds Gaussian noise; Opacus chooses the noise for the target epsilon over the planned steps. The guarantee is (epsilon, delta)-DP: delta is a small probability that the guarantee does not hold, set to 1e-5, well under one over the number of people. Privacy is tracked with the Rényi DP (RDP) accountant, whose epsilon is a guaranteed upper bound; Opacus's default accountant warned that its numerical integration was divergent on this data. One percent of epsilon buys a noisy row count. The person summary's VAE is conditional on age (`vae.condition`): 10% of epsilon buys a noisy age histogram (one count per ten-year bin; each person is in one bin, so the bins together cost that 10%), the decoder takes each row's age band as an input instead of generating it, and a release draws ages from the noisy histogram before the decoder fills in the rest. DP-SGD gets the remaining 89%. Training settings are fixed in the spec, not tuned on the source: every training run on private data spends privacy, tuning runs included.

**MST** (`synth/mst.py`). The general form of the mechanism that won the 2018 NIST synthetic data contest ([McKenna, Miklau, and Sheldon 2021](https://arxiv.org/abs/2108.04978)), adapted from its authors' code in [private-pgm](https://github.com/ryan112358/private-pgm) and fitted with their `mbi` library. It ignores the spec's parents and picks its own structure, paying privacy for the choice. A third of the budget measures every column's histogram with Gaussian noise. A third chooses a tree of column pairs (each column joined to the rest, 20 pairs for 21 columns), one pair at a time with the exponential mechanism: it favors the pairs that a model of the single columns gets most wrong, with enough chance that no one person decides the choice. The last third measures each chosen pair's histogram. A graphical model (a Markov random field: one table of weights per measured pair) is then fitted to all the noisy histograms by mirror descent and sampled, which costs nothing more. The budget is tracked in zero-concentrated DP (zCDP), whose cost rho adds up across the three steps; rho is converted to (epsilon, delta) with delta 1e-9, the authors' default. Columns use the Bayesian network's encoding, so the two release the same bins.

**AIM** (`synth/aim.py`). MST's successor from the same group ([McKenna, Mullins, Sheldon, and Miklau 2022](https://arxiv.org/abs/2201.12677)), adapted from private-pgm the same way. MST picks one tree of pairs; AIM is given a workload, the marginals analysts will ask for, each with a weight, and spends its budget on them in rounds. The workload is the spec's `workload` plus every pair of columns at weight 1. For the person summary that is 11 marginals at weight 5: the cohort protocols' drug and condition triples (hypertension with lisinopril and amlodipine, the drugs with each outcome, and the same for diabetes, metformin, and insulin), diabetes and metformin by age, and age, sex, and race against each other. For the trial table it is 25: arm with follow-up and outcome, arm with each covariate (the propensity model), and each covariate with the outcome (confounding). Weights are fixed in the spec before any release. AIM first measures every column's histogram with Gaussian noise. Each round then picks, with the exponential mechanism, the workload marginal (or a smaller one inside it) that the current model fits worst, measures it, and refits the model by mirror descent. A round gives 10% of its rho to the choice and 90% to the measurement. When a measurement barely moves the model, the noise was too large to tell, so the noise is halved and the remaining rounds cost more each. A size limit, rising with the budget spent, keeps the model from outgrowing memory. The person summary took 40 rounds at epsilon 1 and 68 at epsilon 4.

**Randomness.** The specs here are seeded so that each release can be remade exactly. That is acceptable only because the source is synthetic: anyone who knows the seed can regenerate the noise and subtract it. A spec over real data must set `seed: null`, which makes diffprivlib draw from a cryptographically secure generator. The VAE would need Opacus's secure mode, which depends on the `torchcsprng` package; its last release (2021) supports only torch 1.8 and Python up to 3.9, so it cannot be installed on this stack. The spec therefore refuses VAE releases without a seed. MST and AIM are refused without one too: its Gaussian noise comes from numpy's floating-point generator, which can leak the value it hides ([Mironov 2012](https://doi.org/10.1145/2382196.2382264)). On real data, only the Bayesian network can be used here.

**What is not covered by DP.** The evaluation reports in sections 4 and 5 are computed on the source and are not differentially private. They are for reviewers and stay internal. The holdout split is by a hash of `person_id`, which is not sensitive.

## 4. How releases are checked

**Holdout.** For the person summary, 30% of people are held out of every release (chosen by a hash of the spec name and `person_id`, so the same person always lands on the same side). They are the real test set for utility and the non-members for the privacy attacks. The trial table keeps no holdout: its parity check compares against the data the synthesizer learned from, and holding out 30% would remove about 8 of its 26 events.

**Fidelity** (`synth/fidelity.py`), on the spec's encoding:

- Total variation distance (TVD) per column and per pair of columns (all 210 pairs). 0 means identical distributions, 1 means no overlap. Pairs show whether relationships survived, including ones the synthesizer was not told about.
- Kolmogorov-Smirnov statistic for numeric columns.
- Correlation gap: mean absolute difference between the two Pearson correlation matrices.
- Read against a **noise floor**: the same measures between two real samples (holdout against training). No release can be expected to beat it.
- **By subgroup**: the spec names columns to split by (race, ethnicity, sex, and age by its ten-year bins). Within each group of at least 11 people: its share of the release against its share of the real data, its mean column TVD, and its own noise floor, which is higher for a small group because two small samples differ more. Groups under 11 are left out, as CMS suppresses cells under 11. The spec also names pairs of columns (age by race, age by sex, race by sex), reported cell by cell the same way; cells under 11 are listed without numbers, so the report shows how much of an intersection is too small to read.

**Utility.** Train on synthetic, test on real (TSTR): a logistic regression predicting death, trained on the release and scored on held-out real people by AUC (the chance that a random person who died ranks above one who did not; 0.5 is guessing). Compared with the same model trained on real data (TRTR). Both models are also scored within each subgroup's held-out people, where the group has at least 11 people on each side of the outcome.

**Downstream parity** (`synth/parity.py`). The trial's own propensity-weighted Cox analysis from the trial emulation module, unchanged, run on the real trial table and on synthetic ones. One synthetic draw varies like a fresh small sample, so each method and epsilon is redrawn 20 more times with different seeds. Reported: share estimable, share whose 95% interval covers the real hazard ratio, and share showing a spurious effect (an interval excluding 1 when the real interval includes it).

**Privacy attacks** (`synth/privacy.py`). Each compares members (training people) with non-members (held-out people), because what an attacker learns equally about both is population knowledge, which is the purpose of a release.

- Distance to closest record: for 2,000 synthetic rows, is the nearest real record a member or a non-member? 50% means no sign of copying.
- Membership inference: an attacker scores how close a real record sits to the release and guesses that close means member. AUC over 2,000 members and 2,000 non-members; 0.5 is a coin flip.
- Attribute inference: from age group, sex, race, and ethnicity, guess each sensitive flag as the most common value among matching synthetic rows. The leak is how much more accurate this is for members.
- Quasi-identifier uniqueness of the source: the share of people who are the only one with their combination.
- All read against the same attacks on a **plain copy of the training data**, which shows what real leakage looks like.

A failed attack shows only that this attack failed. These checks bound risk from below; differential privacy is the guarantee.

## 5. Results

### Person summary (16,385 training people, 7,036 held out)

| Release | Column TVD mean | Pair TVD mean | Worst pair (TVD) | Correlation gap | TSTR AUC |
|---|---|---|---|---|---|
| Noise floor (real against real) | 0.006 | 0.012 | age x systolic BP (0.050) | 0.015 | 0.804 (TRTR) |
| Independent columns, epsilon 1 | 0.005 | 0.071 | age x BMI (0.333) | 0.231 | 0.497 |
| Bayesian network, epsilon 1 | 0.014 | 0.039 | hyperlipidemia x eGFR (0.160) | 0.087 | 0.709 |
| Bayesian network, epsilon 4 | 0.005 | 0.023 | hyperlipidemia x eGFR (0.150) | 0.075 | 0.685 |
| VAE conditional on age, epsilon 1 (17) | 0.040 | 0.076 | age x BMI (0.347) | 0.200 | 0.733 |
| VAE conditional on age, epsilon 4 (18) | 0.041 | 0.069 | age x BMI (0.193) | 0.126 | 0.727 |
| VAE, epsilon 1 (5, before) | 0.038 | 0.073 | age x BMI (0.386) | 0.210 | 0.730 |
| VAE, epsilon 4 (6, before) | 0.046 | 0.077 | age x BMI (0.270) | 0.128 | 0.724 |
| MST, epsilon 1 (19) | 0.003 | 0.026 | diabetes x HbA1c (0.158) | 0.093 | 0.747 |
| MST, epsilon 4 (20) | 0.001 | 0.021 | diabetes x HbA1c (0.150) | 0.081 | 0.754 |
| AIM, epsilon 1 (56) | 0.003 | 0.013 | eGFR x HbA1c (0.067) | 0.036 | 0.761 |
| AIM, epsilon 4 (57) | 0.001 | 0.006 | eGFR x HbA1c (0.034) | 0.016 | 0.790 |

- The Bayesian network at epsilon 4 matches single columns at the noise floor and comes closest on relationships (pair TVD 0.023 against a floor of 0.012). At epsilon 1 the four measurement columns carry more noise (worst, BMI, at 0.069).
- Its worst pair is now hyperlipidemia x eGFR, a relationship the spec does not declare: eGFR depends on chronic kidney disease and age, hyperlipidemia on age, so the spec links them only through age.
- The VAE matches single columns worse (DP noise on 63,100 network weights trained from 16,385 people) but predicts death better, because in the Bayesian network death depends on age alone. Its worst pair is still age x BMI: it learns structure from data, not from the spec.
- MST is the best release on almost every measure: single columns below the noise floor at epsilon 4 (0.001; the floor is the gap between two real samples, and MST is fitted to the training sample itself), the lowest pair TVD (0.021), and the best death prediction (TSTR 0.754 against 0.685 for the Bayesian network). At epsilon 1 it still beats the Bayesian network at epsilon 4 on single columns, pairs, and utility. Its tree finds relationships the spec left out: age x BMI, the VAE's worst pair, and hyperlipidemia x eGFR, the Bayesian network's, are both chosen, and death is tied to eGFR (and heart failure at epsilon 4) instead of age alone. Its own worst pair, diabetes x HbA1c, is one the tree reaches only through insulin and age.
- AIM is the best release on every measure, tied with MST on single columns. At epsilon 4 its pairs are below the noise floor (0.006 against 0.012) and its correlation gap is at the floor (0.016 against 0.015); a model trained on it predicts death within 0.014 AUC of one trained on the real data. Its worst pair, eGFR x HbA1c at 0.034, is under a quarter of any other release's worst pair (0.150 or more). At epsilon 1 it beats MST at epsilon 4 on pairs, correlations, and death prediction. Its rounds go where the workload and the data say the model is wrong; MST spends a third of its budget once on a tree.
- The independent-columns baseline keeps every column and loses every relationship, and predicts death no better than guessing: the checks can tell a useless release from a useful one.

**Structure: age as a parent of the measurements.** Releases 2 to 4 gave each measurement only its condition as a parent, so BMI, blood pressure, eGFR, and HbA1c ignored age: age x BMI was the worst pair in every release, and children were off in every release, because their values came from the adult-heavy whole. The current spec adds age as each measurement's second parent (releases 13 and 14). That costs no privacy, since the structure is declared, but gives each measurement's histogram ten times the cells for the same noise:

| | Epsilon 0.25 (2 → 12) | Epsilon 1 (3 → 13) | Epsilon 4 (4 → 14) |
|---|---|---|---|
| Worst pair TVD | 0.258 → 0.311 | 0.247 → 0.160 | 0.244 → 0.150 |
| Pair TVD mean | 0.049 → 0.085 | 0.035 → 0.039 | 0.032 → 0.023 |
| Worst single column TVD | 0.057 → 0.190 | 0.015 → 0.069 | 0.015 → 0.018 |
| Ages 0 to 9, excess over floor | +0.071 → +0.053 | +0.059 → +0.012 | +0.059 → +0.001 |
| Ages 90 or more, excess over floor | +0.096 → +0.158 | +0.019 → +0.047 | +0.016 → +0.003 |
| TSTR AUC | 0.689 → 0.665 | 0.698 → 0.709 | 0.686 → 0.685 |

At epsilon 4 the structure is a clear gain: children and the oldest groups reach their noise floor. At epsilon 1 it fixes children at some cost to single columns. At epsilon 0.25 the noise outweighs it almost everywhere, so the spec no longer makes a Bayesian network release at 0.25. Releases 2 to 4 and 12 stay in the database for comparison; the tables in this section show the current ones.

| Release | Nearer a member | Exact match, member / non-member | Membership AUC | Attribute gap, mean / max |
|---|---|---|---|---|
| Copy of the training data | 62.9% | 68.7% / 44.4% | 0.650 | +0.5% / +1.6% |
| Independent columns, epsilon 1 | 50.0% | 2.0% / 2.1% | 0.512 | +0.2% / +1.2% |
| Bayesian network, epsilon 1 | 51.2% | 29.0% / 29.1% | 0.506 | +0.1% / +1.4% |
| Bayesian network, epsilon 4 | 49.2% | 35.0% / 35.5% | 0.503 | +0.2% / +1.3% |
| VAE, epsilon 1 | 50.9% | 9.4% / 8.8% | 0.509 | +0.2% / +1.2% |
| VAE, epsilon 4 | 50.5% | 19.6% / 19.5% | 0.506 | +0.2% / +1.3% |
| MST, epsilon 1 | 50.9% | 32.9% / 32.6% | 0.505 | +0.2% / +1.4% |
| MST, epsilon 4 | 50.6% | 32.5% / 32.0% | 0.503 | +0.1% / +1.2% |
| AIM, epsilon 1 | 50.6% | 40.2% / 38.6% | 0.503 | +0.1% / +1.1% |
| AIM, epsilon 4 | 49.9% | 43.2% / 43.1% | 0.509 | +0.2% / +1.0% |

- Every release is at chance on every attack; the copy shows the attacks detect leakage when it exists.
- AIM has the most exact matches (43% at epsilon 4), for held-out people as much as training ones. The closer a release is to the population on this coarse encoding, the more twins anyone has in it; a copy of the training data gives held-out people 44%.
- Exact matches rose with the age parents (from 21% to 35% at epsilon 4), equally for training and held-out people. That is the release resembling the population more closely on a coarse encoding, not copying: a held-out person, whom the synthesizer never saw, is as likely to have a twin in it.
- The copy's own numbers are modest because the encoding is coarse: 44% of held-out people have an exact twin among training people on all 21 binned columns. In the source, 2.4% of people are unique on exact age, sex, race, and ethnicity, and 0.2% with age in ten-year groups (the last one 90 or older). With these quasi-identifiers, a linkage attack has almost no one to single out.

### Person summary by subgroup

Column TVD within each group, past the group's own noise floor (excess), and the group's share of the release against its real share. The full table for every release is on its data card. The VAE columns here are releases 5 and 6, before conditioning on age; the conditional VAE is compared with them below.

| Group (training people) | Floor | Bayes net 1 | Bayes net 4 | VAE 1 | VAE 4 |
|---|---|---|---|---|---|
| Race: white (13,429) | 0.008 | +0.009, 1.00 | -0.001, 1.00 | +0.034, 1.00 | +0.040, 1.01 |
| Race: Black (1,435) | 0.022 | +0.020, 1.00 | +0.008, 0.99 | +0.030, 0.93 | +0.046, 0.99 |
| Race: Asian (1,067) | 0.025 | +0.009, 0.95 | +0.012, 0.95 | +0.017, 1.00 | +0.033, 0.94 |
| Race: Native American (69) | 0.077 | +0.003, 1.01 | -0.014, 0.96 | +0.002, 1.69 | +0.049, 0.87 |
| Race: other (193) | 0.068 | -0.001, 1.08 | -0.031, 1.06 | -0.012, 0.98 | -0.017, 1.02 |
| Sex: female (8,162) | 0.009 | +0.020, 1.00 | +0.012, 1.00 | +0.015, 1.03 | +0.026, 1.02 |
| Sex: male (8,223) | 0.008 | +0.020, 1.00 | +0.014, 1.00 | +0.047, 0.97 | +0.053, 0.98 |
| Age 0 to 9 (1,621) | 0.007 | +0.012, 1.04 | +0.001, 1.04 | +0.149, 1.13 | +0.086, 1.01 |
| Age 40 to 49 (2,121) | 0.016 | +0.006, 0.98 | -0.005, 0.99 | +0.059, 0.98 | +0.050, 1.11 |
| Age 70 to 79 (1,244) | 0.023 | +0.025, 0.95 | -0.000, 0.95 | +0.200, 0.77 | +0.133, 0.79 |
| Age 80 to 89 (561) | 0.035 | +0.036, 0.98 | +0.005, 0.97 | +0.221, 0.72 | +0.172, 0.80 |
| Age 90 or more (310) | 0.047 | +0.047, 0.98 | +0.003, 1.07 | +0.223, 0.81 | +0.187, 0.81 |

- The Bayesian network at epsilon 4 is within 0.014 of the floor for every group: no group is distorted past sampling noise by more than that.
- Age is where the VAE falls short. It has 19 to 28% too few people aged 70 and over, and the ones it has are far from real older patients: up to 0.22 past the floor. Those are the people the cohort's conditions affect most. Children are off too (+0.149 at epsilon 1).
- Race is close to the floor in the Bayesian network. The VAE at epsilon 1 makes Native American people 1.69 times as common as they are; DP noise is the same size for every count, so the smallest groups move most.
- The VAE distorts men two to three times as much as women; the Bayesian network treats them alike.
- Utility within groups: release models lose about as much AUC for Black patients (0.687 to 0.722 against 0.780 for the real-data model) as for white patients (0.688 to 0.732 against 0.806). Native American, Hawaiian, and other groups have too few deaths in the holdout to score.
- Each data card lists every group and, under intended use, names any group or intersection cell whose share is off by more than 20% and by more than sampling explains (three standard errors, about 3 / sqrt(people)), with an instruction not to study it in that release.

**Intersections.** Age by race, age by sex, and race by sex give 92 cells; 81 have at least 11 training people. The 11 too small to report are all age by race: Native American people in every age band but 40 to 49, and Hawaiian and "other" from 80 up.

| Release | Worst cell, excess over its floor (share) | Worst single group |
|---|---|---|
| Bayesian network, epsilon 1 | Men 90 or more, +0.074 (0.86); share: Black, 80 to 89, 2.03 | Ages 90 or more, +0.047 |
| Bayesian network, epsilon 4 | Black, 50 to 59, +0.028 (0.97); share: Black, 80 to 89, 2.03 | Men, +0.014 |
| VAE, epsilon 1 | Men 90 or more, +0.259 (0.77); men 80 to 89, +0.238 (0.62) | Ages 90 or more, +0.223 |
| VAE, epsilon 4 | Men 90 or more, +0.218 (0.80) | Ages 90 or more, +0.187 |

- Within each cell, the Bayesian network at epsilon 4 is faithful: all 81 reported cells are within 0.028 of their floor on the other columns.
- The VAE's trouble with older people falls hardest on older men. At epsilon 1 it has 38% too few men aged 80 to 89, against 28% too few of everyone that age.
- Cell sizes are where the Bayesian network falls short: Black people aged 80 to 89 appear at 2.03 times their real share at both epsilons, and Black teenagers at 0.78 at epsilon 4. That is the spec's structure, not noise: neither age nor race is a parent of the other, so the release draws race independently of age (the independent-columns baseline shows the same 2.03). In the source, older people are less often Black (5.2% of those 80 to 89, against 8.8% overall). The cards flag such cells, since an age-by-race analysis on these releases would be wrong.

**Race with age as its parent, tested and not kept.** Making race depend on age (releases 15 and 16, against 13 and 14) turns race's 6-cell histogram into 60 age-by-race cells under the same budget:

| | Epsilon 1 (13 → 15) | Epsilon 4 (14 → 16) |
|---|---|---|
| Black, 80 to 89, share | 2.03 → 0.82 | 2.03 → 1.17 |
| Black, 10 to 19, share | 0.79 → 0.93 | 0.78 → 0.92 |
| Native American, share | 1.01 → 1.65 | 0.96 → 0.96 |
| Groups flagged on the card | 1 → 17 | 2 → 2 |
| TSTR AUC | 0.709 → 0.690 | 0.685 → 0.675 |

At epsilon 4 it removes the structural error. At epsilon 1 the noise swamps the cells of the smallest races, many holding 11 to 30 people: seven come out empty (none did before) and Native American people overall reach 1.65 times their share. One structure serves every epsilon, and trading one group's error for noise across all the smallest groups is the wrong direction for fairness, so race keeps no parent and the doubled share of older Black people stays a documented, flagged limitation.
- The person summary reads 74 HbA1c results the ELN bridge wrote to OMOP after releases 1 to 6 were made, which moves their figures at the third decimal; releases 13 and 14 were made after.

**VAE conditional on age (releases 17 and 18, against 5 and 6).** Releases 5 and 6 had 19% to 28% too few people aged 70 and over. DP-SGD caps how much each person can move the model and adds the same noise for everyone, so people unlike most others (older patients, with more conditions and measurements) have the least pull on what it learns ([Bagdasaryan et al. 2019](https://arxiv.org/abs/1905.12101)). Conditioning on age takes their share out of the model's hands and tells the decoder which age it is generating:

| Age band | Share, epsilon 1 (5 → 17) | Share, epsilon 4 (6 → 18) | Excess, epsilon 1 (5 → 17) | Excess, epsilon 4 (6 → 18) |
|---|---|---|---|---|
| 0 to 9 | 1.13 → 1.03 | 1.01 → 1.03 | +0.149 → +0.128 | +0.086 → +0.055 |
| 10 to 19 | 1.18 → 0.95 | 1.09 → 0.95 | +0.142 → +0.113 | +0.071 → +0.036 |
| 60 to 69 | 0.83 → 1.04 | 0.87 → 1.03 | +0.156 → +0.129 | +0.101 → +0.062 |
| 70 to 79 | 0.77 → 0.95 | 0.79 → 0.95 | +0.200 → +0.189 | +0.133 → +0.123 |
| 80 to 89 | 0.72 → 0.95 | 0.80 → 0.96 | +0.221 → +0.237 | +0.172 → +0.208 |
| 90 or more | 0.81 → 1.10 | 0.81 → 1.11 | +0.223 → +0.228 | +0.187 → +0.214 |
| Groups and cells flagged on the card | 15 → 7 | | 8 → 5 | |

- Every age band's share is now within 11% of real, and no age or age-by-sex group is flagged; before, every band from 70 up and older men were.
- People under 70 come out much closer to real at epsilon 4 (children +0.086 to +0.055, teenagers +0.071 to +0.036), and overall the worst pair improves from 0.270 to 0.193.
- People 80 and over are not more realistic: their other columns are as far from real as before, or further (80 to 89 at epsilon 4, +0.172 to +0.208; one run each, so a difference this size may be run to run variation). Conditioning fixes how many older people there are, not what the model learned about them, which is still limited by DP-SGD's clipping.
- The cards' remaining flags are small race cells (Native American people at 1.89 times their share at epsilon 1, from 1.69): DP-SGD has 10% less budget than before.
- Privacy attacks stay at chance (membership AUC 0.507 and 0.504).
- Releases 5 and 6 were made before the ELN bridge added 74 HbA1c results; 17 and 18 after, which moves figures at the third decimal.

Kept: the shares are right at both epsilons and overall fidelity improves at epsilon 4. Making older people realistic remains open (section 7).

**MST by subgroup (releases 19 and 20, against the Bayesian network's 13 and 14).**

| Group | Bayes net 1 | MST 1 | Bayes net 4 | MST 4 |
|---|---|---|---|---|
| Age 0 to 9 | +0.012, 1.04 | +0.014, 1.00 | +0.001, 1.04 | +0.008, 1.00 |
| Age 80 to 89 | +0.036, 0.98 | +0.045, 0.91 | +0.005, 0.97 | +0.007, 0.97 |
| Age 90 or more | +0.047, 0.98 | +0.068, 0.96 | +0.003, 1.07 | +0.020, 0.97 |
| Race: Black | +0.020, 1.00 | +0.015, 1.01 | +0.008, 0.99 | +0.010, 1.00 |
| Race: Native American | +0.003, 1.01 | +0.029, 0.98 | -0.014, 0.96 | -0.003, 1.19 |
| Black, 80 to 89, share | 2.03 | 1.62 | 2.03 | 2.00 |
| Groups and cells flagged on the card | 1 | 4 | 2 | 4 |

- MST is closer overall but not within every group: people 90 and over are +0.020 past their floor at epsilon 4, against +0.003 for the Bayesian network, whose spec gives age to every measurement. MST's tree ties age to seven columns and reaches the rest through them.
- It did not choose age x race either (race joins the tree through hypertension), so older Black people are still about twice their share at epsilon 4, and the cards flag the same age-by-race cells. A structure learned from noisy data favors the relationships that move the most people; a small group's relationship rarely wins.
- Privacy attacks are at chance (membership AUC 0.505 and 0.503). Exact matches (32%) sit between the Bayesian network at epsilon 1 and 4, equally for training and held-out people.

### Trial table (1,890 people, 26 events)

The real analysis gives a weighted hazard ratio of 1.00 (95% CI 0.43 to 2.32) for lisinopril against amlodipine, and a crude (unweighted) hazard ratio of 1.22. (0.97, 0.42 to 2.25, before step 6c ended covariate windows the day before time zero; the table below was rerun on 2026-11-22, on AWS.)

| Release | Events | Release HR (95% CI) | Estimable | Covers real HR | Spurious effect | Median HR, 20 draws |
|---|---|---|---|---|---|---|
| Bayesian network, epsilon 1 | 118 | 5.47 (2.85 to 10.52) | 90% | 45% | 45% | 0.76 |
| Bayesian network, epsilon 4 | 46 | 12.22 (2.96 to 50.40) | 90% | 75% | 15% | 0.87 |
| Bayesian network, epsilon 16 | 35 | 4.38 (1.55 to 12.37) | 95% | 90% | 5% | 1.19 |
| Bayesian network, epsilon 1000 (no real privacy) | 26 | 0.63 (0.29 to 1.37) | 100% | 95% | 5% | 1.65 |
| VAE, epsilon 4 | 27 | 1.62 (0.69 to 3.81) | 95% | 95% | 0% | 0.96 |
| MST, epsilon 1 | 36 | 1.42 (0.69 to 2.90) | 85% | 70% | 15% | 0.96 |
| MST, epsilon 4 | 22 | 1.65 (0.63 to 4.30) | 100% | 100% | 0% | 0.99 |
| AIM, epsilon 1 | 45 | 0.14 (0.07 to 0.28) | 70% | 60% | 10% | 1.05 |
| AIM, epsilon 4 | 14 | 0.38 (0.13 to 1.12) | 100% | 90% | 10% | 0.86 |

- With 26 events, DP synthetic tables give confident wrong answers often: 45% of the Bayesian network's draws at epsilon 1, and 15% at epsilon 4, show an effect the real data does not.
- Noise is clipped at zero, which can only raise sparse counts: the epsilon 1 release has 118 events against 26 real ones.
- MST at epsilon 4 and the VAE do best: every MST draw and 95% of the VAE's cover the real hazard ratio, and none shows a spurious effect. MST at epsilon 1 is better than the Bayesian network at epsilon 1 (15% spurious against 45%) but not safe. Its event counts stay near the real 26 (36 and 22): its model is fitted to the noisy counts as a whole, not clipped at zero cell by cell.
- AIM, the best method on the person summary, is worse than MST here. Its draws center near the truth (medians 1.05 and 0.86), but they spread wider: at epsilon 1, 30% of draws cannot estimate a hazard ratio and 10% show a spurious effect, and at epsilon 4 10% still do, against none for MST. The stored epsilon 1 release (23) is one of the spurious ones: a hazard ratio of 0.14 (0.07 to 0.28), a strong protective effect that is not there. It is kept, with its card, as the clearest example of why a single release cannot be trusted on a cohort this small. A likely cause, not tested: with 1,890 people and 26 events, AIM's budget is split over many rounds, so each measurement carries more noise than MST's few, and the rare outcome cells lose most.
- MST's draws repeat exactly only on the same kind of processor: its model is fitted in 32-bit floating point (JAX), and the last bits differ between the laptop (ARM) and Fargate (x86). On the laptop the epsilon 1 draws gave 65% covering and 20% spurious. Every other number here, and every stored release, is the same on both.
- A single release is not enough to judge a method on a cohort this small. The stored epsilon 4 release gives a hazard ratio of 12.22, though 75% of draws at that setting cover the real one.
- Without real privacy (epsilon 1000), the Bayesian network's median drifts above 1. The spec makes the outcome depend only on arm and follow-up, so propensity weighting has nothing to adjust and the synthetic estimate follows the crude association. This is a structure limit, not a privacy one.

## 6. Recommended use

- Releases like these are fit for building, testing, and demonstrating analyses and pipelines without access to the source: schemas, code paths, and failure modes behave as they would on the real data.
- They are not fit for reporting estimates. On small cohorts with rare outcomes, they produce effects that are not there, at rates measured above.
- Each release's data card states its intended use and, for trial tables, the measured rate of spurious effects at its setting, and names any subgroup whose share of the release is off by more than 20%. Do not study people 70 and over in the VAE releases.
- For a real source, choose epsilon before looking at results, leave seeds unset, and treat the evaluation reports as internal. A spec over a controlled source says so (`source_access: controlled`); the code then refuses a seed, runs the privacy attacks only with `attack_approval` from the data access request, and exports only to its `approved_users` unless a DAC decision allows wider sharing.

**Export and withdrawal.** A release leaves the database only through `scripts/export_release.py`, which writes its rows with its data card and records who received it, how to reach them, and why (`synth.distribution`). If a flaw turns up later, `scripts/withdraw_release.py` marks the release withdrawn with the reason. A withdrawn release keeps its record and reports for review, can no longer be exported, and its card opens with the withdrawal and an instruction to delete every copy. A draft notice is written for each recipient; nothing is sent automatically, so a person reviews and sends them. The notice asks for a reply once every copy is deleted, and `scripts/confirm_deletion.py` records each reply against its export with how it was confirmed. Run with no arguments, it lists every recipient who has not replied and how long ago the release was withdrawn.

**After release.** Each run of `scripts/evaluate_synth.py` rescores every release and lists for review any whose membership inference AUC or nearer-a-member share has moved more than halfway from chance (0.5) toward what a plain copy of the training data shows (0.650 and 62.9% on the person summary, so 0.575 and 56.5%). That is a trigger to investigate and possibly withdraw, not proof of a leak. No current release is flagged.

**On a schedule.** The Compose `monitor` service (`ehr_rwe_eln.synth.monitor`) runs the same privacy check every `MONITOR_INTERVAL_HOURS`, 24 by default. The attacks are seeded, so on unchanged data and code they give the same answer; a release can only drift when its source changes (a rebuild, or the ELN bridge adding lab results) or the code does. Each run therefore fingerprints every spec's source table and the synth code, reruns the attacks only when a fingerprint changed, and records the run, skipped or not, in `synth.monitor_run`. A full check of the 11 releases with a holdout took about 25 seconds (before MST's two); a skipped one, a few. The `/synth/` page shows the last check and any release it flagged. Trial parity is not rerun on the schedule: it redraws releases, and measures how a synthesizer behaves rather than drift.

## 7. Limitations

- Synthea output is cleaner and more regular than real records. Fidelity and attack results on real data will differ.
- The source has no location (the cohort pipeline's ETL does not load addresses), the strongest quasi-identifier for linkage. The attribute inference attack is weaker than a real one would be.
- The attacks are simple. Stronger ones (for example, density-based membership inference that uses reference data) might do better.
- The Bayesian network keeps only declared relationships, with at most two parents per column.
- The VAE's training settings were not tuned. Tuning on a separate public stand-in would likely improve it.
- The VAE, conditional on age, generates the right number of people 80 and over, but their other columns are still about 0.21 to 0.24 past their noise floor, against 0.005 or less for the Bayesian network at epsilon 4 (release 14). DP-SGD's clipping gives them little pull on training; conditioning does not change that. Use the Bayesian network for analyses of older people.
- On real data only the Bayesian network can run here: the VAE, MST, and AIM need a seed, because secure noise for them is not available on this stack (section 3).
- AIM suits large tables with a known workload. On the small trial table it is less reliable than MST (section 5, release 23). A release's data card names its workload; marginals off it are measured only if AIM finds them badly fitted.
- MST's tree keeps one path between any two columns. Relationships off the tree, and small groups' relationships, survive only through it (older Black people at twice their share, section 5).
- Intersections cover pairs of columns; three-way cells (older Black women, for example) would be smaller still, and most would fall under the 11-person cutoff. Cells under 11 people are listed without numbers.
- One spec per table kind and one trial protocol; results on other cohorts will differ.

## 8. Reproducing and provenance

Releases 1 to 22 were made on a laptop and copied to Aurora; from release 23 they are made on AWS, as a Fargate task that writes to Aurora directly. AIM's releases are 23 and 24 (trial table) and 56 and 57 (person summary); there are no releases 25 to 55. Postgres reserves sequence numbers 32 at a time and skips the unused ones when the database restarts, as Aurora does when it wakes from auto-pause. AIM's four releases were made before its candidates had a fixed order (2026-11-23), so their seed remakes them only with Python's string hashing fixed as it was then; later AIM releases repeat from their seed.

```bash
uv run python scripts/run_synth.py synthesize.py
uv run python scripts/run_synth.py synthesize.py --spec src/ehr_rwe_eln/synth/specs/trial_lisinopril_amlodipine_ckd.yaml
uv run python scripts/run_synth.py synthesize.py --method aim   # one method's releases only
uv run python scripts/run_synth.py evaluate_synth.py
uv run python scripts/synth_cards.py

# Hand a release to someone, and withdraw one
uv run python scripts/export_release.py --release 3 --recipient "Pipeline team" --contact team@example.org --purpose "testing the cohort pipeline"
uv run python scripts/withdraw_release.py --release 3 --reason "what is wrong with it"
uv run python scripts/confirm_deletion.py --export 7 --evidence "Dana's reply, 2026-11-20"
```

Each release in `synth.release` records the spec as run, every mechanism's privacy spend, the source database, the training and holdout counts, the seed, and the git version of the code. Each report in `synth.report` records its own code version. The data cards in `data/synth/cards/` are rendered from those two tables only.
