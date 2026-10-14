# Synthetic data releases: methodology

How this repository makes differentially private synthetic copies of an OMOP database, how it checks them, and what the checks found. Written for a reviewer such as a Data Access Committee (DAC): someone who decides whether a dataset may be shared and needs to know what it protects, what it costs in accuracy, and what it should not be used for.

The source here is Synthea output, not real patients. It stands in for a controlled-access source so the whole process can be run and inspected in the open. The methods carry over to real data; the numbers describe this source only. Code: `src/ehr_rwe_eln/synth/`. Every figure below comes from the reports stored in the `synth.report` table of the 23,420-patient build and from the per-release data cards (`scripts/synth_cards.py`).

## 1. What is released

Two kinds of table, each defined by a YAML spec in `src/ehr_rwe_eln/synth/specs/`.

- **Person summary** (`person_summary.yaml`): one row per person, 21 columns. Age at the end of observation, sex, race, ethnicity; whether each of eight conditions and four drugs was ever recorded; the latest of four measurements (systolic blood pressure, BMI, eGFR, HbA1c); and death. 23,420 people.
- **Trial table** (`trial_lisinopril_amlodipine_ckd.yaml`): the analysis table of module 4's target trial of lisinopril against amlodipine, with chronic kidney disease stage 3 or worse as the outcome. One row per eligible person: treatment arm, age, sex, six condition and four measurement covariates, follow-up days, and outcome. 1,890 people, 26 outcome events.

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

**Fixed domains.** Every category list and every numeric range and bin is written in the spec before the data is read. A range taken from the data would leak on its own: the top bin edge would be the oldest person's age. Values outside a range are clamped into its end bins.

**Declared structure.** For the Bayesian network, each column's parents (the columns its distribution is measured against) are declared in the spec from domain knowledge, so choosing the structure costs no privacy. Example: lisinopril depends on hypertension; diabetes on age and obesity; in the trial table, treatment on diabetes and early kidney disease, following public prescribing guidance.

**Bayesian network synthesizer** (`synth/bayes_net.py`). One histogram per column over the column and its parents. Each count gets noise from the truncated geometric mechanism (integer noise, the discrete form of the Laplace mechanism) through IBM's diffprivlib. Adding or removing one person changes one cell of each histogram by 1, so the sensitivity is 1. Every histogram counts every person, so the release's epsilon is split evenly across the histograms (21 for the person summary, 15 for the trial table), and diffprivlib's budget accountant refuses any spend beyond it. Each share is reduced by one part in a trillion so that floating-point rounding can only underspend. New rows are sampled from the noisy counts alone. The row count is the noisy total of the first histogram, not the true count.

**Variational autoencoder (VAE)** (`synth/vae.py`). A neural network that compresses each row to 16 numbers and rebuilds it, trained with DP-SGD through Meta's Opacus. Each training step clips every person's gradient to length 1 and adds Gaussian noise; Opacus chooses the noise for the target epsilon over the planned steps. The guarantee is (epsilon, delta)-DP: delta is a small probability that the guarantee does not hold, set to 1e-5, well under one over the number of people. Privacy is tracked with the Rényi DP (RDP) accountant, whose epsilon is a guaranteed upper bound; Opacus's default accountant warned that its numerical integration was divergent on this data. One percent of epsilon buys a noisy row count. Training settings are fixed in the spec, not tuned on the source: every training run on private data spends privacy, tuning runs included.

**Randomness.** The specs here are seeded so that each release can be remade exactly. That is acceptable only because the source is synthetic: anyone who knows the seed can regenerate the noise and subtract it. A spec over real data must set `seed: null`, which makes diffprivlib draw from a cryptographically secure generator. The VAE would need Opacus's secure mode, which depends on the `torchcsprng` package; its last release (2021) supports only torch 1.8 and Python up to 3.9, so it cannot be installed on this stack. The spec therefore refuses VAE releases without a seed: on real data, only the Bayesian network can be used here.

**What is not covered by DP.** The evaluation reports in sections 4 and 5 are computed on the source and are not differentially private. They are for reviewers and stay internal. The holdout split is by a hash of `person_id`, which is not sensitive.

## 4. How releases are checked

**Holdout.** For the person summary, 30% of people are held out of every release (chosen by a hash of the spec name and `person_id`, so the same person always lands on the same side). They are the real test set for utility and the non-members for the privacy attacks. The trial table keeps no holdout: its parity check compares against the data the synthesizer learned from, and holding out 30% would remove about 8 of its 26 events.

**Fidelity** (`synth/fidelity.py`), on the spec's encoding:

- Total variation distance (TVD) per column and per pair of columns (all 210 pairs). 0 means identical distributions, 1 means no overlap. Pairs show whether relationships survived, including ones the synthesizer was not told about.
- Kolmogorov-Smirnov statistic for numeric columns.
- Correlation gap: mean absolute difference between the two Pearson correlation matrices.
- Read against a **noise floor**: the same measures between two real samples (holdout against training). No release can be expected to beat it.

**Utility.** Train on synthetic, test on real (TSTR): a logistic regression predicting death, trained on the release and scored on held-out real people by AUC (the chance that a random person who died ranks above one who did not; 0.5 is guessing). Compared with the same model trained on real data (TRTR).

**Downstream parity** (`synth/parity.py`). The trial's own propensity-weighted Cox analysis from module 4, unchanged, run on the real trial table and on synthetic ones. One synthetic draw varies like a fresh small sample, so each method and epsilon is redrawn 20 more times with different seeds. Reported: share estimable, share whose 95% interval covers the real hazard ratio, and share showing a spurious effect (an interval excluding 1 when the real interval includes it).

**Privacy attacks** (`synth/privacy.py`). Each compares members (training people) with non-members (held-out people), because what an attacker learns equally about both is population knowledge, which is the purpose of a release.

- Distance to closest record: for 2,000 synthetic rows, is the nearest real record a member or a non-member? 50% means no sign of copying.
- Membership inference: an attacker scores how close a real record sits to the release and guesses that close means member. AUC over 2,000 members and 2,000 non-members; 0.5 is a coin flip.
- Attribute inference: from age group, sex, race, and ethnicity, guess each sensitive flag as the most common value among matching synthetic rows. The leak is how much more accurate this is for members.
- Quasi-identifier uniqueness of the source: the share of people who are the only one with their combination.
- All read against the same attacks on a **plain copy of the training data**, which shows what real leakage looks like.

A failed attack shows only that this attack failed. These checks bound risk from below; differential privacy is the guarantee.

## 5. Results

### Person summary (16,384 training people, 7,036 held out)

| Release | Column TVD mean | Pair TVD mean | Worst pair (TVD) | Correlation gap | TSTR AUC |
|---|---|---|---|---|---|
| Noise floor (real against real) | 0.006 | 0.013 | 0.046 | 0.014 | 0.809 (TRTR) |
| Independent columns, epsilon 1 | 0.005 | 0.071 | age x BMI (0.332) | 0.232 | 0.465 |
| Bayesian network, epsilon 0.25 | 0.020 | 0.056 | age x BMI (0.266) | 0.108 | 0.668 |
| Bayesian network, epsilon 1 | 0.007 | 0.037 | age x BMI (0.254) | 0.087 | 0.685 |
| Bayesian network, epsilon 4 | 0.003 | 0.032 | age x BMI (0.245) | 0.082 | 0.712 |
| VAE, epsilon 1 | 0.046 | 0.082 | age x BMI (0.382) | 0.223 | 0.711 |
| VAE, epsilon 4 | 0.038 | 0.067 | age x BMI (0.272) | 0.122 | 0.733 |

- The Bayesian network matches single columns at the noise floor from epsilon 1 up. Relationships fall short of the floor at every epsilon.
- The worst pair in every release is age x BMI. The spec makes BMI depend only on obesity, and the source includes children, whose BMI depends strongly on age. A declared structure keeps only what it declares.
- The VAE matches single columns worse (DP noise on 63,357 network weights trained from 16,384 people) but predicts death slightly better, because in the Bayesian network death depends on age alone.
- The independent-columns baseline keeps every column and loses every relationship, and predicts death no better than guessing: the checks can tell a useless release from a useful one.

| Release | Nearer a member | Exact match, member / non-member | Membership AUC | Attribute gap, mean / max |
|---|---|---|---|---|
| Copy of the training data | 62.2% | 68.2% / 45.4% | 0.642 | +0.4% / +1.1% |
| Independent columns, epsilon 1 | 51.1% | 2.7% / 2.6% | 0.504 | 0.0% / +0.7% |
| Bayesian network, epsilon 0.25 | 50.3% | 16.1% / 15.7% | 0.506 | 0.0% / +0.6% |
| Bayesian network, epsilon 1 | 51.8% | 20.0% / 18.7% | 0.505 | 0.0% / +0.8% |
| Bayesian network, epsilon 4 | 50.5% | 20.2% / 20.0% | 0.504 | 0.0% / +0.9% |
| VAE, epsilon 1 | 49.7% | 8.7% / 8.8% | 0.502 | 0.0% / +0.7% |
| VAE, epsilon 4 | 50.1% | 19.1% / 19.3% | 0.504 | 0.0% / +0.8% |

- Every release is at chance on every attack; the copy shows the attacks detect leakage when it exists.
- The copy's own numbers are modest because the encoding is coarse: 45% of held-out people have an exact twin among training people on all 21 binned columns. In the source, 2.3% of people are unique on exact age, sex, race, and ethnicity, and 0.1% with age in ten-year groups. With these quasi-identifiers, a linkage attack has almost no one to single out.

### Trial table (1,890 people, 26 events)

The real analysis gives a weighted hazard ratio of 0.97 (95% CI 0.42 to 2.26) for lisinopril against amlodipine, and a crude (unweighted) hazard ratio of 1.22.

| Release | Events | Release HR (95% CI) | Estimable | Covers real HR | Spurious effect | Median HR, 20 draws |
|---|---|---|---|---|---|---|
| Bayesian network, epsilon 1 | 70 | 1.45 (0.85 to 2.47) | 85% | 30% | 55% | 0.67 |
| Bayesian network, epsilon 4 | 34 | 2.54 (1.05 to 6.18) | 90% | 45% | 40% | 0.85 |
| Bayesian network, epsilon 16 | 35 | 4.21 (1.49 to 11.89) | 95% | 90% | 5% | 1.41 |
| Bayesian network, epsilon 1000 (no real privacy) | 26 | 0.63 (0.29 to 1.37) | 100% | 95% | 0% | 1.57 |
| VAE, epsilon 4 | 29 | 2.66 (1.02 to 6.96) | 95% | 95% | 0% | 0.91 |

- With 26 events, DP synthetic tables give confident wrong answers often: more than half of the draws at epsilon 1, and 40% at epsilon 4, show an effect the real data does not.
- Noise is clipped at zero, which can only raise sparse counts: the epsilon 1 release has 70 events against 26 real ones.
- The VAE does well over repeated draws; its stored release happens to be one of the unlucky ones. A single release is not enough to judge a method on a cohort this small.
- Without real privacy (epsilon 1000), the Bayesian network's median drifts above 1. The spec makes the outcome depend only on arm and follow-up, so propensity weighting has nothing to adjust and the synthetic estimate follows the crude association. This is a structure limit, not a privacy one.

## 6. Recommended use

- Releases like these are fit for building, testing, and demonstrating analyses and pipelines without access to the source: schemas, code paths, and failure modes behave as they would on the real data.
- They are not fit for reporting estimates. On small cohorts with rare outcomes, they produce effects that are not there, at rates measured above.
- Each release's data card states its intended use and, for trial tables, the measured rate of spurious effects at its setting.
- For a real source, choose epsilon before looking at results, leave seeds unset, and treat the evaluation reports as internal.

## 7. Limitations

- Synthea output is cleaner and more regular than real records. Fidelity and attack results on real data will differ.
- The source has no location (the module 1 ETL does not load addresses), the strongest quasi-identifier for linkage. The attribute inference attack is weaker than a real one would be.
- The attacks are simple. Stronger ones (for example, density-based membership inference that uses reference data) might do better.
- The Bayesian network keeps only declared relationships, with at most two parents per column.
- The VAE's training settings were not tuned. Tuning on a separate public stand-in would likely improve it.
- On real data only the Bayesian network can run here: the VAE needs a seed, because secure noise for it is not installable (section 3).
- Fidelity is not yet measured by subgroup. DP noise is the same size for every count, so small groups (99 people of 23,420 are recorded as Native American) are distorted most.
- One spec per table kind and one trial protocol; results on other cohorts will differ.

## 8. Reproducing and provenance

```bash
DB_NAME=ehr_rwe_eln_tte uv run python scripts/synthesize.py
DB_NAME=ehr_rwe_eln_tte uv run python scripts/synthesize.py --spec src/ehr_rwe_eln/synth/specs/trial_lisinopril_amlodipine_ckd.yaml
DB_NAME=ehr_rwe_eln_tte uv run python scripts/evaluate_synth.py
DB_NAME=ehr_rwe_eln_tte uv run python scripts/synth_cards.py
```

Each release in `synth.release` records the spec as run, every mechanism's privacy spend, the source database, the training and holdout counts, the seed, and the git version of the code. Each report in `synth.report` records its own code version. The data cards in `data/synth/cards/` are rendered from those two tables only.
